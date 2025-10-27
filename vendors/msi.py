from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ---------- regex patterns ----------

# Dates like 2025-08-18 / 2025/08/18 / 2025.08.18
DATE_RX = re.compile(r"\b(\d{4})[./-](\d{2})[./-](\d{2})\b")

# Retail / OEM MSI BIOS versions like:
#   7D37vB4
#   7D98vBD
#   7E06vAI
#   7E06v1P3
VERSION_BASE_RX = re.compile(r"\b([A-Za-z0-9]{3,}v[A-Za-z0-9.]+)\b", re.I)

# Alternative MSI BIOS filenames like:
#   E7D98IMS.BG1
#   E7D37IMS.B40
ALT_VERSION_RX = re.compile(r"\bE[0-9A-Za-z]{4,}IMS\.[A-Za-z0-9]+\b")

# Direct BIOS zip links from MSI CDN:
#   https://download.msi.com/bos_exe/mb/7D37vB4.zip
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
    """
    Return a string that *looks like* an MSI BIOS version or filename.
    Rejects random strings like "msiNav02.min.css" or "Geneva"
    because they won't match these patterns.
    """
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

def _candidate_model_slugs(model: str) -> List[str]:
    """
    Generate safe fallback slugs for BULK / HS BULK / WIFI 7 wording.
    We *do not* remove the 'M' from 'B760M', because that could point to a
    totally different PCB/BIOS and brick someone's board.
    """
    raw = model or ""
    variants = set()

    def add_variant(txt: str):
        slug = _slugify_model_for_url(txt)
        if slug:
            variants.add(slug)

    add_variant(raw)  # original

    # strip "HS BULK"
    add_variant(re.sub(r"\bHS\s*BULK\b", "", raw, flags=re.I))

    # strip "BULK"
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
    """
    Loads the MSI support page, forces the BIOS tab open,
    scrolls to trigger lazy-load, waits for network idle,
    then returns the final DOM as HTML.
    """
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Default to headful (less likely to get 403 / antibot)
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

            # Navigate
            page.goto(u, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # Cookie banner
            try:
                page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
            except Exception:
                pass

            # Click BIOS tab (lazy loads content on BULK boards)
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

            # Scroll to bottom to trigger lazy loads
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            # Wait for anything that looks BIOS-y:
            # - 'AMI BIOS'
            # - an MSI BIOS zip link
            # - a table with 'Release Date'
            try:
                page.wait_for_selector(
                    "text=/AMI\\s+BIOS/i, a[href*='bos_exe/mb/'], table th:has-text('Release Date')",
                    timeout=8000,
                )
            except Exception:
                pass

            # One more networkidle
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

        # Try both www.msi.com and us.msi.com
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
            # best-effort capture even if something threw
            html = page.content()

        ctx.close()
        browser.close()
        return html

# ---------- parsing helpers ----------

def _row_looks_like_bios(title_txt: str, ver_txt: str, row_html: str) -> bool:
    """
    Decide if a row is actually a BIOS row, not some random resource table.
    We accept the row if ANY of these are true:
    - title mentions 'bios' (e.g. 'AMI BIOS', 'BIOS (Beta)')
    - version text matches an MSI BIOS pattern (7D37vB4 / E7D98IMS.BG1)
    - row contains a direct MSI BIOS zip link (bos_exe/mb/*.zip)
    """
    title_lower = (title_txt or "").lower()
    ver_match = _extract_base_version(ver_txt) is not None
    link_match = MSI_ZIP_RX.search(row_html or "") is not None
    bios_word = "bios" in title_lower  # catches 'ami bios', 'bios (beta)', etc.

    return bios_word or ver_match or link_match

def _parse_span_lookahead(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Heuristic for older MSI layouts:
    - Find spans in <section class="spec"> that contain "BIOS".
    - Look ahead in nearby spans for version + date.

    Tightened:
    - Only include the row if we actually got a valid BIOS-looking version string.
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

            # REQUIRE a version that looks like a BIOS version.
            if ver:
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
    Retail-style grid of spans:
    Header row looks like: Title | Version | Release Date | File Size
    Then rows in 4-span chunks.

    Tightened:
    - We only keep a row if _row_looks_like_bios(...) says it's BIOS-y.
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
            # Be flexible: we just need to identify Version and Release Date cols
            if (
                "version" in block[1]
                and "release" in block[2]
                and "date" in block[2]
            ):
                header_idx = i + 4
                break
        if header_idx < 0:
            continue

        data = texts[header_idx:]
        # We'll also grab the raw HTML chunks in parallel so we can check for zip links
        span_htmls = [str(s) for s in spans[header_idx:]]

        for i in range(0, len(data), 4):
            chunk = data[i:i+4]
            html_chunk = "".join(span_htmls[i:i+4])
            if len(chunk) < 3:
                continue

            title_txt = chunk[0]
            ver_txt   = chunk[1]
            date_txt  = chunk[2]

            if not _row_looks_like_bios(title_txt, ver_txt, html_chunk):
                continue

            ver = _extract_base_version(ver_txt)
            dt  = _norm_date(date_txt)

            if ver or dt:
                out.append({
                    "title": title_txt or "BIOS",
                    "version": ver,
                    "date": dt,
                })
    return out

def _parse_table_rows(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Parse <table> layouts used on some MSI pages (especially BULK / OEM).
    We ONLY keep rows that actually look like BIOS, using _row_looks_like_bios().
    """
    out: List[Dict[str, Optional[str]]] = []

    for table in soup.find_all("table"):
        ths = table.find_all("th")
        headers = [th.get_text(strip=True).lower() for th in ths]
        if not headers:
            continue

        # We need a "version" column or similar.
        if "version" not in headers:
            continue

        # Pick date column: any header that has the word "date"
        date_cols = [i for i, h in enumerate(headers) if "date" in h]
        if not date_cols:
            continue
        date_idx = date_cols[0]

        # Version col
        ver_idx = headers.index("version")

        # Title col guess
        title_idx = 0
        if "title" in headers:
            title_idx = headers.index("title")

        # Process each row
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all(["td", "th"])
            if len(tds) <= max(title_idx, ver_idx, date_idx):
                continue

            title_txt = tds[title_idx].get_text(strip=True)
            ver_txt   = tds[ver_idx].get_text(strip=True)
            date_txt  = tds[date_idx].get_text(strip=True)
            row_html  = str(tr)

            # BIOS row filter
            if not _row_looks_like_bios(title_txt, ver_txt, row_html):
                continue

            ver = _extract_base_version(ver_txt)
            dt  = _norm_date(date_txt)

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

def _parse_download_links(soup: BeautifulSoup, html_text: str) -> List[Dict[str, Optional[str]]]:
    """
    Fallback for BULK / OEM pages:
    - Look for MSI BIOS zip links.
    - Infer version from the filename.
    - Try to sniff a nearby date.
    """
    out: List[Dict[str, Optional[str]]] = []

    for m in MSI_ZIP_RX.finditer(html_text):
        bios_token = m.group(1)  # e.g. "7D37vB4"
        ver = _extract_base_version(bios_token) or bios_token

        # Try to grab a nearby date from the parent row/div
        date_guess = None
        try:
            href_piece = m.group(0)
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

def _parse_regex_fallback(html_text: str) -> List[Dict[str, Optional[str]]]:
    """
    Absolute last resort:
    - Find text that looks like a BIOS version (7D37vB4 / E7D37IMS.B40)
    - Look up to ~200 chars after it for a date.
    """
    out: List[Dict[str, Optional[str]]] = []
    for m in re.finditer(r"(?:%s|%s)" % (
        VERSION_BASE_RX.pattern,
        ALT_VERSION_RX.pattern,
    ), html_text, flags=re.I):

        ver_candidate = _extract_base_version(m.group(0))
        if not ver_candidate:
            continue

        tail = html_text[m.end(): m.end() + 200]
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

    # 1. Classic span layout (strict now)
    rows = _parse_span_lookahead(soup)
    if rows:
        return rows

    # 2. Retail grid spans (strict now)
    rows = _parse_grid_sections(soup)
    if rows:
        return rows

    # 3. Table layout (strict BIOS filter)
    rows = _parse_table_rows(soup)
    if rows:
        return rows

    # 4. Direct MSI download links (fallback for BULK boards)
    rows = _parse_download_links(soup, html_text)
    if rows:
        return rows

    # 5. Regex hail-mary
    rows = _parse_regex_fallback(html_text)
    return rows

# ---------- public API ----------

def latest_two(model_name: str, override_url: Optional[str] = None) -> Dict:
    """
    Scrape MSI BIOS info for `model_name` and return latest two entries.

    Steps:
    - Build multiple slug guesses (strip BULK / HS BULK / WIFI 7, but DO NOT
      remove 'M' from 'B760M' etc. to avoid crossing to a different PCB).
    - For each slug, try www.msi.com and us.msi.com.
    - Force-load BIOS tab in Playwright and wait for lazy content.
    - Parse using layered heuristics.
    - Filter out junk rows that aren't real BIOS (like msiNav02.min.css).
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

        # Save debug snapshot so you can open it in a browser
        try:
            Path("cache/msi-debug").mkdir(parents=True, exist_ok=True)
            debug_slug = _slugify_name(model_name) + "__" + _slugify_name(try_url)
            Path(f"cache/msi-debug/{debug_slug}.html").write_text(
                html_text, encoding="utf-8"
            )
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

    # Sort newest first by date if we have dates
    def sort_key(r):
        d = r.get("date")
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
