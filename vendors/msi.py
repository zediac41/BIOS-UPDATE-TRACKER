from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ---------- patterns ----------
# Dates like: 2025-08-18 / 2025/08/18 / 2025.08.18
DATE_RX = re.compile(r"\b(\d{4})[./-](\d{2})[./-](\d{2})\b")

# Capture the base BIOS version at the start, ignoring any trailing " (Beta ...)" text.
# Examples matched (group 1 returned):
#   "7E06vAI"                      -> 7E06vAI
#   "7D75v1P3(Beta version)"       -> 7D75v1P3
#   "7E25vAA1 (Beta)"              -> 7E25vAA1
#   "7E25vAA1  (Beta test build)"  -> 7E25vAA1
VERSION_BASE_RX = re.compile(r"\b([A-Za-z0-9]+v[A-Za-z0-9.]+)\b", re.I)

# Some MSI BIOS filenames are like "E7D98IMS.BG1" (no "v"). We'll allow those too.
ALT_VERSION_RX = re.compile(r"\bE[0-9A-Za-z]{4,}IMS\.[A-Za-z0-9]+\b")

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
    # try standard "7D75v1P3" style first
    m = VERSION_BASE_RX.search(str(text))
    if m:
        return m.group(1)
    # then try "E7D98IMS.BG1" style
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
    return (model or "").strip().replace(" ", "-").replace("--", "-")

def _guess_url_from_model(model: str) -> Optional[str]:
    """
    Best-effort 'main' guess from the raw model string.
    """
    slug = _slugify_model_for_url(model)
    return f"https://www.msi.com/Motherboard/{slug}/support#bios" if slug else None

# NEW: generate multiple fallback slugs for BULK / HS BULK / WIFI 7, etc.
def _candidate_model_slugs(model: str) -> List[str]:
    raw = model or ""
    variants = set()

    def add_variant(txt: str):
        slug = _slugify_model_for_url(txt)
        if slug:
            variants.add(slug)

    # original
    add_variant(raw)

    # strip "HS BULK"
    add_variant(re.sub(r"\bHS\s*BULK\b", "", raw, flags=re.I))

    # strip "BULK"
    add_variant(re.sub(r"\bBULK\b", "", raw, flags=re.I))

    # normalize "WIFI 7" -> "WIFI"
    add_variant(re.sub(r"\bWIFI\s*7\b", "WIFI", raw, flags=re.I))

    # normalize both "WIFI7" -> "WIFI"
    add_variant(re.sub(r"\bWIFI7\b", "WIFI", raw, flags=re.I))

    # collapse multiple spaces
    cleaned_more = re.sub(r"\s{2,}", " ", raw).strip()
    add_variant(cleaned_more)

    return list(variants)

def _slugify_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", (model or "msi-board")).strip("-_") or "msi-board"

# ---------- fetch with Playwright (local-friendly) ----------
def _fetch_html(url: str, timeout_ms: int = 50000) -> str:
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

    # Default headful for local debugging; MSIOLD_HEADFUL=0 to force headless
    headful_env = os.getenv("MSIOLD_HEADFUL")
    headful = True if headful_env is None else headful_env.lower() in ("1", "true", "yes")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headful,
            args=["--disable-blink-features=AutomationControlled"]
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

        def _load_once(u: str):
            # force #bios
            if "#bios" not in u:
                u = u + "#bios"
            page.goto(u, wait_until="domcontentloaded")

            # Cookie banner
            try:
                page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
            except Exception:
                pass

            # Ensure BIOS tab is active
            try:
                page.get_by_text("BIOS", exact=False).click(timeout=4000)
            except Exception:
                try:
                    page.locator("a[href*='#bios']").click(timeout=2500)
                except Exception:
                    pass

            page.wait_for_timeout(700)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(900)

            # Wait for spec grid / BIOS text
            try:
                page.wait_for_selector("section.spec span:has-text('Title')",
                                       timeout=15000)
            except Exception:
                pass
            try:
                page.wait_for_selector("section.spec span:has-text('BIOS')",
                                       timeout=15000)
            except Exception:
                pass

        # Try both www.msi.com and us.msi.com, like before
        url_https = _force_https(url)
        candidates = [
            _ensure_bios_anchor(_with_host(url_https, "www.msi.com")),
            _ensure_bios_anchor(_with_host(url_https, "us.msi.com")),
        ]
        for cand in candidates:
            try:
                _load_once(cand)
                html = page.content()
                ctx.close(); browser.close()
                return html
            except Exception:
                continue

        # last ditch even if failures
        html = page.content()
        ctx.close(); browser.close()
        return html

# ---------- parsing helpers ----------

def _parse_span_lookahead(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    OLD PRIMARY:
    Scan each section.spec (or .spec) for a span that contains 'BIOS',
    then look ahead up to ~12 spans for Version and Release Date text.

    Keeps Beta rows, but version text is cleaned to base version.
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
            dt  = None
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

            if ver and dt:
                out.append({"title": texts[i], "version": ver, "date": dt})

    # de-dup (version, date)
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
    OLD SECONDARY:
    Look for a strict span-grid like:
    Title | Version | Release Date | File Size
    and then rows in chunks of four spans.
    """
    out: List[Dict[str, Optional[str]]] = []
    for sec in soup.select("section.spec, .spec"):
        spans = sec.find_all("span")
        if not spans:
            continue
        texts = [s.get_text(strip=True) for s in spans]

        # find a proper header row
        start = -1
        for i in range(0, len(texts) - 3):
            block = [t.lower() for t in texts[i:i+4]]
            if block == ["title", "version", "release date", "file size"]:
                start = i + 4
                break
        if start < 0:
            continue

        data = texts[start:]
        for i in range(0, len(data), 4):
            chunk = data[i:i+4]
            if len(chunk) < 3:
                continue
            title, ver_raw, date_raw = chunk[0], chunk[1], chunk[2]
            if "bios" not in title.lower():
                continue
            ver = _extract_base_version(ver_raw)
            dt  = _norm_date(date_raw)
            if ver and dt:
                out.append({"title": title, "version": ver, "date": dt})
    return out

# NEW: table parser for layouts that use <table><thead><th>Title ...>
def _parse_table_rows(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []

    for table in soup.find_all("table"):
        # collect headers
        ths = table.find_all("th")
        headers = [th.get_text(strip=True).lower() for th in ths]
        if not headers:
            continue

        # We only care if table looks like it has BIOS downloads
        # Usually something like Title | Version | Release Date | File Size
        wanted = ["title", "version", "release date"]
        if not all(w in headers for w in wanted):
            continue

        # map columns
        try:
            idx_title = headers.index("title")
        except ValueError:
            continue
        try:
            idx_ver = headers.index("version")
        except ValueError:
            continue
        try:
            idx_date = headers.index("release date")
        except ValueError:
            continue

        # rows after header
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(idx_title, idx_ver, idx_date):
                continue

            title_txt = cells[idx_title].get_text(strip=True)
            ver_txt   = cells[idx_ver].get_text(strip=True)
            date_txt  = cells[idx_date].get_text(strip=True)

            # filter only BIOS rows
            if "bios" not in title_txt.lower():
                continue

            ver = _extract_base_version(ver_txt)
            dt  = _norm_date(date_txt)
            if ver and dt:
                out.append({
                    "title": title_txt,
                    "version": ver,
                    "date": dt,
                })

    # de-dupe
    uniq = []
    seen = set()
    for r in out:
        key = (r["version"], r["date"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq

# NEW: very last-resort regex scrape of rendered HTML
def _parse_regex_fallback(html_text: str) -> List[Dict[str, Optional[str]]]:
    """
    Super noisy fallback:
    - Find a version-looking token (7D98v1P3 or E7D98IMS.BG1)
    - Look up to ~200 chars after it for a date
    - Keep a couple of best guesses
    """
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
        if not dm:
            continue

        dt = _norm_date(dm.group(0))
        if not dt:
            continue

        row = {
            "title": "BIOS (fallback)",
            "version": ver_candidate,
            "date": dt,
        }
        # Dedup
        if row not in out:
            out.append(row)

    return out

def _parse_bios_rows(html_text: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html_text or "", "html.parser")

    # Prefer the robust span lookahead (old layout)
    rows = _parse_span_lookahead(soup)
    if rows:
        return rows

    # Fall back to strict grid (old retail layout)
    rows = _parse_grid_sections(soup)
    if rows:
        return rows

    # NEW: Try table-based layouts (some BULK / OEM pages)
    rows = _parse_table_rows(soup)
    if rows:
        return rows

    # NEW: regex hail-mary so we almost never return 0 silently
    rows = _parse_regex_fallback(html_text)
    return rows

# ---------- public API ----------
def latest_two(model_name: str, override_url: Optional[str] = None) -> Dict:
    """
    Returns latest two BIOS entries (Beta allowed, but version printed without Beta tag).

    Improvements:
    - Try multiple slugs for BULK / HS BULK / WIFI 7 variants before giving up.
    - Use new parsers that understand <table> layouts.
    """

    # Build candidate URLs in priority order
    cand_urls: List[str] = []
    if override_url:
        cand_urls.append(override_url)

    # Generate slugs
    for slug in _candidate_model_slugs(model_name):
        cand_urls.append(f"https://www.msi.com/Motherboard/{slug}/support#bios")

    # Deduplicate but preserve order
    seen_url = set()
    cand_urls_unique: List[str] = []
    for u in cand_urls:
        u_https = _force_https(u)
        if u_https not in seen_url:
            seen_url.add(u_https)
            cand_urls_unique.append(u_https)

    best_rows: List[Dict[str, Optional[str]]] = []
    best_url: Optional[str] = None
    first_url_for_reporting: Optional[str] = cand_urls_unique[0] if cand_urls_unique else None

    for try_url in cand_urls_unique:
        final_url = _ensure_bios_anchor(_force_https(try_url))
        html_text = _fetch_html(final_url)

        # ALWAYS dump debug snapshot (now include slug fragment for clarity)
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

    # Newest first by date if present; otherwise keep order
    def key(r):
        d = r.get("date")
        return (0, d) if d else (1, "")
    rows_sorted = sorted(best_rows, key=key, reverse=True)

    versions = [
        {"version": r.get("version") or "", "date": r.get("date")}
        for r in rows_sorted[:2]
    ]

    return {
        "vendor": "MSI",   # keep MSI so tiles show under the MSI filter
        "model": model_name,
        "url": best_url or (first_url_for_reporting or ""),
        "ok": True,
        "versions": versions,
        "error": None,
    }

# quick local test:
if __name__ == "__main__":
    import sys as _sys
    mdl = " ".join(_sys.argv[1:]) or "MAG Z790 TOMAHAWK MAX WIFI"
    print(latest_two(mdl))
