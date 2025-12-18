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

# Typical MSI BIOS version tokens shown on support pages.
# Examples:
#   7D98vBH
#   7D98vBG1(Beta version)
#   7D75v1P3
MSI_BIOS_VER_RX = re.compile(r"\b([0-9A-Z]{4,6}v[0-9A-Z]{1,6}(?:\.[0-9A-Z]+)?)\b", re.I)

# Keep the older permissive token as a fallback (some pages are inconsistent).
VERSION_BASE_RX = re.compile(r"\b([A-Za-z0-9]+v[A-Za-z0-9.]+)\b", re.I)

# MSI internal BIOS file naming sometimes shows up as:
#   E7D98IMS.BG1 / E7C95AMS.2L0 / etc.
MSI_FILE_VER_RX = re.compile(
    r"\b(E[0-9A-Z]{4,6}(?:IMS|AMS|IGD|IZ1)\.[0-9A-Z]{2,4})\b", re.I
)

# Text fallback helper for pages where the DOM structure differs:
#   "Version7D37vB4. Release Date2024-10-15"
MSI_VERSION_RELEASEDATE_RX = re.compile(
    r"Version\s*([0-9A-Za-z.]+(?:\s*\([^)]*\))?)\s*\.?\s*Release\s*Date\s*(\d{4}[./-]\d{2}[./-]\d{2})",
    re.I
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
    """Extract the BIOS version token we want to display."""
    if not text:
        return None
    s = str(text)

    m = MSI_BIOS_VER_RX.search(s)
    if m:
        return m.group(1)

    m = VERSION_BASE_RX.search(s)
    if m:
        return m.group(1)

    m = MSI_FILE_VER_RX.search(s)
    if m:
        return m.group(1)

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

def _guess_url_from_model(model: str) -> Optional[str]:
    slug = (model or "").strip().replace(" ", "-").replace("--", "-")
    return f"https://www.msi.com/Motherboard/{slug}/support#bios" if slug else None

def _slugify_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (model or "").strip()) or "msi-board"

# ---------- playwright fetching ----------

def _fetch_html(url: str, timeout_ms: int = 50000) -> str:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Default headful for local debugging; MSIOLD_HEADFUL=0 to force headless
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

        page = ctx.new_page()

        def _load_once(target_url: str) -> None:
            """Navigate once and wait for the support content to settle."""
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Give scripts time to bootstrap.
            page.wait_for_timeout(1200)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Accept cookies if the banner is present
            for label in ("Accept all", "Accept All", "I Accept", "AGREE"):
                try:
                    page.locator(f"button:has-text('{label}')").click(timeout=2000)
                    break
                except Exception:
                    pass

            # Try to switch to the SUPPORT tab if needed
            try:
                page.locator("a[href*='support']").click(timeout=2000)
            except Exception:
                pass

            # Make sure we're somewhere near BIOS content
            try:
                page.locator("a[href*='#bios']").click(timeout=2500)
            except Exception:
                try:
                    page.locator("a:has-text('BIOS')").click(timeout=2500)
                except Exception:
                    pass

            # Some pages lazy-load the list; scroll a bit and wait.
            page.wait_for_timeout(800)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(900)

            # Wait for any common BIOS markers to appear (best-effort)
            for sel in (
                "section.spec span:has-text('Title')",
                "section.spec span:has-text('Version')",
                "text=Release Date",
                "text=AMI BIOS",
            ):
                try:
                    page.wait_for_selector(sel, timeout=8000)
                    break
                except Exception:
                    continue

        url_https = _force_https(url)
        candidates = [
            _ensure_bios_anchor(_with_host(url_https, "www.msi.com")),
            _ensure_bios_anchor(_with_host(url_https, "us.msi.com")),
        ]

        try:
            for cand in candidates:
                try:
                    _load_once(cand)
                    html = page.content()
                    ctx.close()
                    browser.close()
                    return html
                except Exception:
                    continue

            # If all candidates failed, still return whatever we have
            html = page.content()
            ctx.close()
            browser.close()
            return html
        except Exception:
            # On a hard failure, propagate a minimal error page
            try:
                html = page.content()
            except Exception:
                html = ""
            ctx.close()
            browser.close()
            return html

# ---------- parsing helpers ----------

def _parse_span_lookahead(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Primary: within each section.spec, find a span containing 'BIOS' and scan forward for
    a Version token and a Release Date.
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
            for j in range(i + 1, min(i + 14, len(spans))):
                tj = texts[j]
                if ver is None and ("version" in tj.lower() or MSI_BIOS_VER_RX.search(tj) or VERSION_BASE_RX.search(tj)):
                    ver = _extract_base_version(tj)
                if dt is None and ("date" in tj.lower() or DATE_RX.search(tj)):
                    dt = _norm_date(tj)
                if ver and dt:
                    out.append({"title": texts[i], "version": ver, "date": dt})
                    break
    return out

def _parse_grid_sections(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Secondary: strict grid (Title|Version|Release Date|File Size) for clean pages.
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
            header = [t.lower() for t in texts[i:i + 4]]
            if ("title" in header[0] and
                "version" in header[1] and
                ("date" in header[2] or "release" in header[2])):
                start = i + 4
                break
        if start < 0:
            continue

        data = texts[start:]
        for i in range(0, len(data), 4):
            chunk = data[i:i + 4]
            if len(chunk) < 3:
                continue
            title, ver_raw, date_raw = chunk[0], chunk[1], chunk[2]
            # Only keep items that look like BIOS *and* have a BIOS-ish version token.
            if "bios" not in title.lower():
                continue
            ver = _extract_base_version(ver_raw)
            dt = _norm_date(date_raw)
            if ver and dt:
                out.append({"title": title, "version": ver, "date": dt})
    return out

def _parse_text_fallback(html_text: str) -> List[Dict[str, Optional[str]]]:
    """
    Last-resort parser for odd MSI pages (OEM / regional / BULK) where the DOM structure
    differs and the span/grid parsers miss everything.

    Strategy:
      1) Strip to plain text.
      2) Prefer explicit 'Version ... Release Date ...' pairs.
      3) Otherwise scan for BIOS-like version tokens and pick a nearby date.
    """
    if not html_text:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    full_txt = soup.get_text(" ", strip=True) or ""
    if not full_txt:
        return []

    rows: List[Dict[str, Optional[str]]] = []
    seen: Dict[str, Optional[str]] = {}

    # (1) Label-pair extraction (fixes PRO B760M-VC WIFI BULK style pages)
    keywords = ("bios", "ami", "microcode", "m-flash", "uefi", "me firmware", "file size", "download", "description")
    for m in MSI_VERSION_RELEASEDATE_RX.finditer(full_txt):
        ver_raw = m.group(1)
        dt_raw = m.group(2)

        # Light sanity filter: keep pairs that look BIOS-related in their neighborhood.
        ws = max(0, m.start() - 600)
        we = min(len(full_txt), m.end() + 600)
        window = full_txt[ws:we].lower()
        if not any(k in window for k in keywords):
            continue

        ver = _extract_base_version(ver_raw)
        dt_norm = _norm_date(dt_raw)
        if not ver:
            continue

        prev = seen.get(ver)
        if prev is None or (dt_norm and (prev or "") < dt_norm):
            seen[ver] = dt_norm

    if seen:
        for ver, dt in seen.items():
            rows.append({"title": "BIOS", "version": ver, "date": dt})
        return rows

    # (2) Token scan with looser context rules than the old version.
    for m in MSI_BIOS_VER_RX.finditer(full_txt):
        ver = m.group(1)

        ws = max(0, m.start() - 500)
        we = min(len(full_txt), m.end() + 500)
        window = full_txt[ws:we]

        # Require some BIOS-ish context, but allow pages that don't repeat 'BIOS' near the version.
        wlow = window.lower()
        if not ("bios" in wlow or "release date" in wlow or "ami" in wlow or "microcode" in wlow):
            continue

        dmatch = DATE_RX.search(window)
        dt_norm = _norm_date(dmatch.group(0)) if dmatch else None

        prev = seen.get(ver)
        if prev is None or (dt_norm and (prev or "") < dt_norm):
            seen[ver] = dt_norm

    for ver, dt in seen.items():
        rows.append({"title": "BIOS", "version": ver, "date": dt})

    return rows

def _parse_bios_rows(html_text: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html_text or "", "html.parser")

    # Prefer robust span lookahead (better on busy pages)
    rows = _parse_span_lookahead(soup)
    if rows:
        return rows

    # Next try the strict spec-grid parser
    rows = _parse_grid_sections(soup)
    if rows:
        return rows

    # Last resort: text-only fallback for weird OEM / BULK pages
    return _parse_text_fallback(html_text)

# ---------- public API ----------

def latest_two(model_name: str, override_url: Optional[str] = None) -> Dict:
    """Return the latest two BIOS entries for an MSI board."""
    url0 = override_url or _guess_url_from_model(model_name)
    if not url0:
        return {
            "vendor": "MSI",
            "model": model_name,
            "url": "",
            "ok": False,
            "versions": [],
            "error": "msi: override_url required",
        }

    final_url = _ensure_bios_anchor(_force_https(url0))
    html_text = _fetch_html(final_url)

    # Always dump a debug snapshot locally for tuning
    try:
        Path("cache/msi-debug").mkdir(parents=True, exist_ok=True)
        Path(f"cache/msi-debug/{_slugify_name(model_name)}.html").write_text(html_text, encoding="utf-8")
    except Exception:
        pass

    rows = _parse_bios_rows(html_text)
    if not rows:
        return {
            "vendor": "MSI",
            "model": model_name,
            "url": final_url,
            "ok": False,
            "versions": [],
            "error": "parse:no-versions",
        }

    # Newest first by date if present; otherwise keep order
    def key(r):
        d = r.get("date")
        return (0, d) if d else (1, "")

    rows_sorted = sorted(rows, key=key, reverse=True)

    versions = [
        {"version": r.get("version") or "", "date": r.get("date")}
        for r in rows_sorted[:2]
    ]

    return {
        "vendor": "MSI",  # keep MSI so tiles show under the MSI filter
        "model": model_name,
        "url": final_url,
        "ok": True,
        "versions": versions,
        "error": None,
    }

if __name__ == "__main__":
    import sys as _sys
    mdl = " ".join(_sys.argv[1:]) or "MAG Z790 TOMAHAWK MAX WIFI"
    print(latest_two(mdl, override_url=_guess_url_from_model(mdl)))
