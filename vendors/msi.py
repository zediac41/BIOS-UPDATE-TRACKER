from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ---------- regex patterns ----------
# Date patterns like 2025-08-18 / 2025/08/18 / 2025.08.18
DATE_RX = re.compile(r"\b(\d{4})[./-](\d{2})[./-](\d{2})\b")

# "7D37vB4", "7D98vBD", "7E06vAI", etc.
VERSION_BASE_RX = re.compile(r"\b([A-Za-z0-9]{3,}v[A-Za-z0-9.]+)\b", re.I)

# MSI-style filename versions like "E7D98IMS.BG1"
ALT_VERSION_RX = re.compile(r"\bE[0-9A-Za-z]{4,}IMS\.[A-Za-z0-9]+\b")

# direct BIOS zip links like https://download.msi.com/bos_exe/mb/7D37vB4.zip
MSI_ZIP_RX = re.compile(
    r"https?://(?:[\w.-]+\.)?msi\.com/bos_exe/mb/([A-Za-z0-9._-]+)\.zip",
    re.I,
)


def _norm_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    m = DATE_RX.search(str(s))
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{mo}-{d}"


def _extract_base_version(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = VERSION_BASE_RX.search(str(text))
    if m:
        return m.group(1)
    m2 = ALT_VERSION_RX.search(str(text))
    if m2:
        return m2.group(0)
    return None


def _force_https(url: str) -> str:
    pr = urlparse(url)
    if pr.scheme != "https":
        pr = pr._replace(scheme="https")
    return urlunparse(pr)


def _with_host(url: str, host: str) -> str:
    pr = urlparse(url)
    return urlunparse(pr._replace(netloc=host))


def _ensure_bios_anchor(url: str) -> str:
    pr = urlparse(url)
    frag = pr.fragment or "bios"
    return urlunparse(pr._replace(fragment=frag))


def _slugify_model_for_url(model: str) -> str:
    return (
        (model or "")
        .strip()
        .replace(" ", "-")
        .replace("--", "-")
    )


def _guess_url_from_model(model: str) -> Optional[str]:
    slug = _slugify_model_for_url(model)
    return f"https://www.msi.com/Motherboard/{slug}/support#bios" if slug else None


# NEW: expand candidates for BULK / HS BULK / WIFI 7 wording,
# but do NOT drop "M" from "B760M" -> "B760". That could brick someone.
def _candidate_model_slugs(model: str) -> List[str]:
    raw = model or ""
    variants = set()

    def add_variant(txt: str):
        slug = _slugify_model_for_url(txt)
        if slug:
            variants.add(slug)

    add_variant(raw)  # original string

    # strip "HS BULK"
    add_variant(re.sub(r"\bHS\s*BULK\b", "", raw, flags=re.I))

    # strip plain "BULK"
    add_variant(re.sub(r"\bBULK\b", "", raw, flags=re.I))

    # normalize "WIFI 7" -> "WIFI"
    add_variant(re.sub(r"\bWIFI\s*7\b", "WIFI", raw, flags=re.I))
    add_variant(re.sub(r"\bWIFI7\b", "WIFI", raw, flags=re.I))

    # collapse duplicate spaces
    add_variant(re.sub(r"\s{2,}", " ", raw).strip())

    return list(variants)


def _slugify_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", (model or "msi-board")).strip("-_") or "msi-board"


# ---------- Playwright fetch ----------
def _fetch_html(url: str, timeout_ms: int = 60000) -> str:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # You can force "real browser" mode by default.
    # headless=False tends to bypass MSI's 403 more reliably.
    headful_env = os.getenv("MSIOLD_HEADFUL")
    headful = True if headful_env is None else headful_env.lower() in ("1", "true", "yes")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headful,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=ua,
            locale="en-US",
            timezone_id="America/Chicago",
            viewport={"width": 1400, "height": 1250},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)

        def _load_and_populate(u: str):
            # Force BIOS anchor
            if "#bios" not in u:
                u = u + "#bios"

            # Step 1: navigate and wait for networkidle once
            page.goto(u, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # Step 2: accept cookie banner if present
            try:
                page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
            except Exception:
                pass

            # Step 3: explicitly click BIOS tab again in case MSI lazily loads it
            bios_clicked = False
            for sel in [
                "text=BIOS",
                "a[href*='#bios']",
                "button:has-text('BIOS')",
            ]:
                try:
                    page.locator(sel).first.click(timeout=4000)
                    bios_clicked = True
                    break
                except Exception:
                    continue

            # Step 4: scroll to bottom to trigger lazy load
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            # Step 5 (NEW): wait for some actual BIOS-ish content to land.
            # We're generous here: table headers or a .zip link or "AMI BIOS".
            # We don't assert success (no raise) because not all models expose it.
            try:
                page.wait_for_selector(
                    "text=/AMI\\s+BIOS/i, table th:has-text('Release Date'), a[href*='bos_exe/mb/']",
                    timeout=8000
                )
            except Exception:
                pass

            # Step 6: final networkidle wait to let MSI's JS fetch finish
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

        # Try both www.msi.com and us.msi.com hosts
        url_https = _force_https(url)
        candidates = [
            _ensure_bios_anchor(_with_host(url_https, "www.msi.com")),
            _ensure_bios_anchor(_with_host(url_https, "us.msi.com")),
        ]

        html = ""
        for cand in candidates:
            try:
                _load_and_populate(cand)
                html = page.content()
                break
            except Exception:
                continue

        if not html:
            # last-ditch capture even if we hit exceptions
            html = page.content()

        ctx.close()
        browser.close()
        return html


# ---------- parsing helpers ----------

def _parse_span_lookahead(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Original heuristic: in <section class="spec">, find a span containing "BIOS",
    then grab Version + Date from following spans.
    """
    out: List[Dict[str, Optional[str]]] = []
    for sec in soup.select("section.spec, .spec"):
        spans = sec.find_all("span")
        if not spans:
            continue
        texts = [s.get_text(strip=True) for s in spans]

        bios_idxs = [i for i, t in enumerate(texts) if "bios" in t.lower()]
        for i in bios_idxs:
            ver = None
            dt = None
            for j in range(i + 1, min(i + 12, len(spans))):
                tj = texts[j]
                if ver is None:
                    base = _extract_base_version(tj)
                    if base:
                        ver = base
                if dt is None and DATE_RX.search(tj):
                    dt = _norm_date(tj)
                if ver and dt:
                    break

            if ver or dt:
                out.append({
                    "title": texts[i],
                    "version": ver,
                    "date": dt,
                })

    # dedupe
    uniq: List[Dict[str, Optional[str]]] = []
    seen = set()
    for r in out:
        key = (r.get("version"), r.get("date"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def _parse_grid_sections(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Older retail boards used a span grid with a header row:
    Title | Version | Release Date | File Size
    parsed in 4-span chunks.

    Keep it, but loosen filters:
    - Don't require that row["title"] contains "bios" (some OEM rows already imply BIOS).
    """
    out: List[Dict[str, Optional[str]]] = []
    for sec in soup.select("section.spec, .spec"):
        spans = sec.find_all("span")
        if not spans:
            continue
        texts = [s.get_text(strip=True) for s in spans]

        header_idx = -1
        for i in range(0, len(texts) - 3):
            block = [t.lower() for t in texts[i:i+4]]
            if (
                "title" in block[0]
                and "version" in block[1]
                and "release" in block[2]
                and "date" in block[2]
            ):
                header_idx = i + 4
                break
        if header_idx < 0:
            continue

        data = texts[header_idx:]
        for i in range(0, len(data), 4):
            chunk = data[i:i+4]
            if len(chunk) < 3:
                continue
            title_txt = chunk[0]
            ver_txt = chunk[1]
            date_txt = chunk[2]

            ver = _extract_base_version(ver_txt)
            dt = _norm_date(date_txt)
            if ver or dt:
                out.append({
                    "title": title_txt,
                    "version": ver,
                    "date": dt,
                })
    return out


def _parse_table_rows(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Parse <table> layouts.
    We'll look for any table whose headers include Version and Release Date,
    then scrape the rows.
    """
    out: List[Dict[str, Optional[str]]] = []

    for table in soup.find_all("table"):
        ths = table.find_all("th")
        headers = [th.get_text(strip=True).lower() for th in ths]
        if not headers:
            continue

        # We need "version" and something that looks like a date column.
        if "version" not in headers:
            continue
        # pick best guess date header
        date_col_candidates = [i for i, h in enumerate(headers) if "date" in h]
        if not date_col_candidates:
            continue

        ver_idx = headers.index("version")
        date_idx = date_col_candidates[0]

        # title column guess: prefer one with 'title', else first column
        title_idx = 0
        if "title" in headers:
            title_idx = headers.index("title")

        # walk rows
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all(["td", "th"])
            if len(tds) <= max(title_idx, ver_idx, date_idx):
                continue

            title_txt = tds[title_idx].get_text(strip=True)
            ver_txt = tds[ver_idx].get_text(strip=True)
            date_txt = tds[date_idx].get_text(strip=True)

            ver = _extract_base_version(ver_txt)
            dt = _norm_date(date_txt)

            if ver or dt:
                out.append({
                    "title": title_txt or "BIOS",
                    "version": ver,
                    "date": dt,
                })

    # dedupe
    uniq = []
    seen = set()
    for r in out:
        key = (r["version"], r["date"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


# NEW: last-resort parser: find MSI BIOS zip links in the HTML
# and grab version + nearby date from the same row/div.
def _parse_download_links(soup: BeautifulSoup, html_text: str) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []

    # direct regex over the entire HTML to not miss things in onclick handlers etc.
    for m in MSI_ZIP_RX.finditer(html_text):
        bios_token = m.group(1)  # e.g. "7D37vB4" or "7D98vBD"
        ver = _extract_base_version(bios_token) or bios_token

        # try to find a parent node around the <a> to sniff a date
        # we'll pick the first <a> whose href matches this exact URL
        date_guess = None
        try:
            href_full = m.group(0)
            a_el = soup.find("a", href=lambda h: h and bios_token in h)
            if a_el:
                parent = a_el.find_parent(["tr", "div", "section", "li"])
                if parent:
                    date_guess = _norm_date(parent.get_text(" ", strip=True))
        except Exception:
            pass

        row = {
            "title": "BIOS (download.msi.com)",
            "version": ver,
            "date": date_guess,
        }
        if row not in out:
            out.append(row)

    return out


# NEW: final regex hail-mary for version/date pairs that aren't linked (rare)
def _parse_regex_fallback(html_text: str) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    for m in re.finditer(r"(?:%s|%s)" % (
        VERSION_BASE_RX.pattern,
        ALT_VERSION_RX.pattern,
    ), html_text, flags=re.I):
        ver_candidate = _extract_base_version(m.group(0))
        if not ver_candidate:
            continue

        tail = html_text[m.end(): m.end()+200]
        dm = DATE_RX.search(tail)
        dt = _norm_date(dm.group(0)) if dm else None

        row = {
            "title": "BIOS (fallback)",
            "version": ver_candidate,
            "date": dt,
        }
        if row not in out:
            out.append(row)

    return out


def _parse_bios_rows(html_text: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html_text or "", "html.parser")

    # 1. Original heuristics
    rows = _parse_span_lookahead(soup)
    if rows:
        return rows

    # 2. Grid style
    rows = _parse_grid_sections(soup)
    if rows:
        return rows

    # 3. Modern table style
    rows = _parse_table_rows(soup)
    if rows:
        return rows

    # 4. Direct MSI download links (works on weird BULK pages)
    rows = _parse_download_links(soup, html_text)
    if rows:
        return rows

    # 5. Absolute hail-mary regex
    rows = _parse_regex_fallback(html_text)
    return rows


# ---------- public API ----------
def latest_two(model_name: str, override_url: Optional[str] = None) -> Dict:
    """
    Scrape MSI BIOS info for `model_name` and return latest two entries.

    Behavior:
    - Generate multiple URL slugs:
        e.g. "PRO B760M-VC WIFI BULK" ->
        ["PRO-B760M-VC-WIFI-BULK", "PRO-B760M-VC-WIFI", ...]
      We remove "BULK" / "HS BULK" / "WIFI 7". We DO NOT remove "M".
      This avoids accidentally returning BIOS for a different physical PCB,
      which can brick a board. (Ex: B760M-VC vs B760-VC are not the same
      board and have different BIOS codes like 7D37 vs 7D98.)  <-- safety
    - For each candidate slug, try both www.msi.com and us.msi.com.
    - Force-load the BIOS tab with Playwright, scroll, wait for lazy content.
    - Parse using multiple strategies, including scanning for direct
      download.msi.com/bos_exe/mb/*.zip links (common on BULK/SI boards).
    """

    # Build candidate URLs
    cand_urls: List[str] = []
    if override_url:
        cand_urls.append(override_url)

    for slug in _candidate_model_slugs(model_name):
        cand_urls.append(f"https://www.msi.com/Motherboard/{slug}/support#bios")

    # de-dupe preserving order
    seen = set()
    urls = []
    for u in cand_urls:
        u_https = _force_https(u)
        if u_https not in seen:
            seen.add(u_https)
            urls.append(u_https)

    best_rows: List[Dict[str, Optional[str]]] = []
    best_url: Optional[str] = None
    first_url_for_reporting: Optional[str] = urls[0] if urls else None

    for try_url in urls:
        final_url = _ensure_bios_anchor(_force_https(try_url))
        html_text = _fetch_html(final_url)

        # cache snapshot for debugging
        try:
            Path("cache/msi-debug").mkdir(parents=True, exist_ok=True)
            debug_slug = _slugify_name(model_name) + "__" + _slugify_name(try_url)
            Path(f"cache/msi-debug/{debug_slug}.html").write_text(html_text, encoding="utf-8")
        except Exception:
            pass

        rows = _parse_bios_rows(html_text)
        if rows:
            best_rows = rows
            best_url = final_url
            break

    if not best_rows:
        return {
            "vendor": "MSI",
            "model": model_name,
            "url": first_url_for_reporting or "",
            "ok": False,
            "versions": [],
            "error": "parse:no-versions",
        }

    # sort newest first by date (if any)
    def sort_key(r):
        d = r.get("date")
        # (0,"2025-05-01") should come before (1,"")
        return (0, d) if d else (1, "")

    best_rows_sorted = sorted(best_rows, key=sort_key, reverse=True)

    versions = [
        {
            "version": r.get("version") or "",
            "date": r.get("date"),
        }
        for r in best_rows_sorted[:2]
    ]

    return {
        "vendor": "MSI",
        "model": model_name,
        "url": best_url or (first_url_for_reporting or ""),
        "ok": True,
        "versions": versions,
        "error": None,
    }


if __name__ == "__main__":
    import sys as _sys
    mdl = " ".join(_sys.argv[1:]) or "MAG Z790 TOMAHAWK MAX WIFI"
    print(latest_two(mdl))
