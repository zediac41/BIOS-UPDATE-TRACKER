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

# Capture the base BIOS version token, ignoring any trailing " (Beta ...)" text.
# Examples matched (group 1 returned):
#   "7E06vAI"                      -> 7E06vAI
#   "7D75v1P3(Beta version)"       -> 7D75v1P3
#   "7E25vAA1 (Beta)"              -> 7E25vAA1
#   "7E25vAA1  (Beta test build)"  -> 7E25vAA1
VERSION_BASE_RX = re.compile(r"\b([A-Za-z0-9]+v[A-Za-z0-9.]+)\b", re.I)


def _norm_date(s: Optional[str]) -> Optional[str]:
    """Normalize various MSI date formats to YYYY-MM-DD, or return None."""
    if not s:
        return None
    m = DATE_RX.search(str(s))
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{mo}-{d}"


def _extract_base_version(text: Optional[str]) -> Optional[str]:
    """Return a cleaned BIOS version token like 7D98v1F, or None."""
    if not text:
        return None
    m = VERSION_BASE_RX.search(str(text))
    return m.group(1) if m else None


def _force_https(url: str) -> str:
    pr = urlparse(url)
    if pr.scheme != "https":
        pr = pr._replace(scheme="https")
    return urlunparse(pr)


def _with_host(url: str, host: str) -> str:
    pr = urlparse(url)
    return urlunparse(pr._replace(netloc=host))


def _ensure_bios_anchor(url: str) -> str:
    """Ensure the URL has a #bios fragment so MSI lands on the right tab."""
    pr = urlparse(url)
    frag = pr.fragment or "bios"
    return urlunparse(pr._replace(fragment=frag))


def _guess_url_from_model(model: str) -> Optional[str]:
    """Best-effort guess of MSI support URL when override_url is not provided."""
    slug = (model or "").strip().replace(" ", "-").replace("--", "-")
    return f"https://www.msi.com/Motherboard/{slug}/support#bios" if slug else None


def _slugify_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", (model or "msi-board")).strip("-_") or "msi-board"


# ---------- fetch with Playwright (local-friendly) ----------

def _fetch_html(url: str, timeout_ms: int = 50000) -> str:
    """Load an MSI support page with Playwright, trying both www and us hostnames
    and making a best-effort attempt to activate the BIOS tab.
    """
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Default headful for local debugging; MSIOLD_HEADFUL=0 to force headless.
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

        # Reduce chance of being detected as automation.
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)

        def _load_once(u: str) -> None:
            # Always try to land on the BIOS tab.
            if "#bios" not in u.lower():
                if "#" in u:
                    base, _hash = u.split("#", 1)
                    u = base + "#bios"
                else:
                    u = u + "#bios"

            page.goto(u, wait_until="domcontentloaded")

            # Cookie banner
            try:
                page.locator("#onetrust-accept-btn-handler").click(timeout=3000)
            except Exception:
                pass

            # Explicitly click BIOS tab if needed.
            try:
                page.get_by_text("BIOS", exact=False).click(timeout=4000)
            except Exception:
                try:
                    page.locator("a[href*='#bios']").click(timeout=2500)
                except Exception:
                    pass

            # Give MSI's client-side code a chance to render the spec grid.
            page.wait_for_timeout(700)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(900)

            # Wait for spec grid / BIOS-related text, but don't fail the whole fetch if missing.
            try:
                page.wait_for_selector("section.spec span:has-text('Title')", timeout=15000)
            except Exception:
                pass
            try:
                page.wait_for_selector("section.spec span:has-text('BIOS')", timeout=15000)
            except Exception:
                pass

        url_https = _force_https(url)
        candidates = [
            _ensure_bios_anchor(_with_host(url_https, "www.msi.com")),
            _ensure_bios_anchor(_with_host(url_https, "us.msi.com")),
        ]

        html = ""
        for cand in candidates:
            try:
                _load_once(cand)
                html = page.content()
                break
            except Exception:
                # Try next candidate
                continue

        if not html:
            # Last-resort: just load the original URL without host tweaks.
            try:
                _load_once(url_https)
                html = page.content()
            except Exception:
                html = page.content()

        ctx.close()
        browser.close()
        return html


# ---------- parsing ----------

def _parse_span_lookahead(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Primary: within each section.spec, find a '...BIOS' title span and scan forward for
    the next Version (base extracted) and Date. We keep Beta rows but only print base version.
    """
    out: List[Dict[str, Optional[str]]] = []

    for sec in soup.select("section.spec, .spec"):
        spans = sec.find_all("span")
        if not spans:
            continue
        texts = [s.get_text(strip=True) for s in spans]

        bios_idxs = [i for i, t in enumerate(texts) if "bios" in t.lower()]
        for i in bios_idxs:
            ver: Optional[str] = None
            dt: Optional[str] = None

            # Look ahead over the next few spans for Version + Date.
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

    # De-dup by (version, date) while preserving order.
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
    Secondary: strict grid (Title|Version|Release Date|File Size) for clean pages,
    extracting the base version from the Version cell.
    """
    out: List[Dict[str, Optional[str]]] = []

    for sec in soup.select("section.spec, .spec"):
        spans = sec.find_all("span")
        if not spans:
            continue
        texts = [s.get_text(strip=True) for s in spans]

        # Find a proper header row.
        start = -1
        for i in range(0, len(texts) - 3):
            block = [t.lower() for t in texts[i : i + 4]]
            if block == ["title", "version", "release date", "file size"]:
                start = i + 4
                break
        if start < 0:
            continue

        data = texts[start:]
        for i in range(0, len(data), 4):
            chunk = data[i : i + 4]
            if len(chunk) < 3:
                continue
            title, ver_raw, date_raw = chunk[0], chunk[1], chunk[2]
            if "bios" not in title.lower():
                continue
            ver = _extract_base_version(ver_raw)
            dt = _norm_date(date_raw)
            if ver and dt:
                out.append({"title": title, "version": ver, "date": dt})

    # De-dup by (version, date).
    uniq: List[Dict[str, Optional[str]]] = []
    seen = set()
    for r in out:
        key = (r.get("version"), r.get("date"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def _parse_text_fallback(html_text: str) -> List[Dict[str, Optional[str]]]:
    """Loose fallback: scan all text on the page for MSI-style BIOS versions (7D98v1F, etc.)
    and the nearest date. This is used only if the stricter parsers fail, so it mainly helps on
    pages where MSI has changed the markup for the downloads grid (e.g. some BULK / OEM boards).
    """
    if not html_text:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    text = soup.get_text("\n", strip=True)
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[Dict[str, Optional[str]]] = []

    for i, line in enumerate(lines):
        ver = _extract_base_version(line)
        if not ver:
            continue

        # Look at a small context window around this line to ensure it is BIOS-related.
        ctx_start = max(0, i - 3)
        ctx_end = min(len(lines), i + 4)
        ctx_lines = lines[ctx_start:ctx_end]
        ctx_text = " ".join(ctx_lines).lower()
        if not any(key in ctx_text for key in ("bios", "uefi", "firmware")):
            # Probably a driver/utility version; skip it.
            continue

        # Try to find a date on this line or nearby.
        dt = _norm_date(line)
        if not dt:
            for j in range(ctx_start, ctx_end):
                if j == i:
                    continue
                dt = _norm_date(lines[j])
                if dt:
                    break

        if not dt:
            continue

        out.append({"title": "", "version": ver, "date": dt})

    # De-dup by (version, date) while preserving order.
    uniq: List[Dict[str, Optional[str]]] = []
    seen = set()
    for r in out:
        key = (r.get("version"), r.get("date"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def _parse_bios_rows(html_text: str) -> List[Dict[str, Optional[str]]]:
    """Run the structured parsers first, then a very loose text fallback.

    This keeps behaviour for normal MSI pages the same, but allows us to
    still recover BIOS versions from odd OEM / regional layouts that don't
    expose a clean spec grid (like PRO B760M-VC WIFI BULK).
    """
    soup = BeautifulSoup(html_text or "", "html.parser")

    # 1) Primary: robust span lookahead (works on most current MSI pages).
    rows = _parse_span_lookahead(soup)
    if rows:
        return rows

    # 2) Secondary: strict spec-grid parser for older / simpler layouts.
    rows = _parse_grid_sections(soup)
    if rows:
        return rows

    # 3) Last resort: textual scrape of the whole page.
    return _parse_text_fallback(html_text)


# ---------- public API ----------

def latest_two(model_name: str, override_url: Optional[str] = None) -> Dict:
    """Return latest two BIOS entries for a given MSI model.

    The dict structure matches what bios_tracker.py expects:
      {
        "vendor": "MSI",
        "model": "<model name>",
        "url": "<support URL>",
        "ok": True/False,
        "versions": [
            {"version": "<version>", "date": "YYYY-MM-DD"},
            ...
        ],
        "error": "<error string or None>",
      }
    """
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

    # Always dump a debug snapshot locally for tuning.
    try:
        debug_dir = Path("cache/msi-debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_path = debug_dir / f"{_slugify_name(model_name)}.html"
        debug_path.write_text(html_text, encoding="utf-8")
    except Exception:
        # Non-fatal; ignore debug write failures.
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

    # Newest first by date if present; otherwise keep order.
    def _sort_key(r: Dict[str, Optional[str]]):
        d = r.get("date")
        return (0, d) if d else (1, "")

    rows_sorted = sorted(rows, key=_sort_key, reverse=True)

    versions = [
        {"version": r.get("version") or "", "date": r.get("date")}
        for r in rows_sorted[:2]
    ]

    return {
        "vendor": "MSI",
        "model": model_name,
        "url": final_url,
        "ok": True,
        "versions": versions,
        "error": None,
    }


# quick local test
if __name__ == "__main__":
    import sys as _sys

    mdl = " ".join(_sys.argv[1:]) or "MAG Z790 TOMAHAWK MAX WIFI"
    print(latest_two(mdl, override_url=_guess_url_from_model(mdl)))
