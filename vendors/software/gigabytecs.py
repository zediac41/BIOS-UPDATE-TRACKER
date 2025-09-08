# vendors/software/gigabytecs.py
# GIGABYTE Control Center (GCC) — scrape ONLY the URL you provide in config.yml.
# Finds version from links like: https://download.gigabyte.com/FileList/Utility/GCC_25.08.04.01.zip
# Handles 403/JS rendering by falling back to Playwright (headful).

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

# Optional Playwright import; used only if requests HTML doesn’t contain the link
try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _HAS_PW = True
except Exception:
    _HAS_PW = False

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}

# Look specifically for GCC_<4-part-version> (e.g., GCC_25.08.04.01)
GCC_VER_RX = re.compile(r"(?i)\bGCC[_-]?(\d{1,4}\.\d{1,4}\.\d{1,4}\.\d{1,4})\b")
# Accept 4-part dotted numbers near GCC text as a weaker fallback
VER4_RX    = re.compile(r"\b(\d{1,4}\.\d{1,4}\.\d{1,4}\.\d{1,4})\b")
APP_RX     = re.compile(r"(?i)\b(gcc|control\s*center|control\-center)\b")

def _vkey(v: str):
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))

def _extract_from_html(html: str) -> str | None:
    # Fast path: regex over raw HTML
    m = GCC_VER_RX.search(html)
    if m:
        return m.group(1)

    # Parse DOM and scan anchors
    soup = BeautifulSoup(html, "html.parser")
    exact, near = [], []
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        txt  = a.get_text(" ", strip=True)
        blob = f"{href} {txt}"

        mm = GCC_VER_RX.search(blob)
        if mm:
            exact.append(mm.group(1))
            continue

        if APP_RX.search(blob):
            mm2 = VER4_RX.search(blob)
            if mm2:
                near.append(mm2.group(1))

    if exact:
        return sorted(exact, key=_vkey, reverse=True)[0]
    if near:
        return sorted(near, key=_vkey, reverse=True)[0]
    return None

def _render_with_playwright(url: str) -> str:
    # Render headful to reduce bot-detection
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # headful tends to bypass some bot checks
            args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            user_agent=UA["User-Agent"],
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            java_script_enabled=True,
            extra_http_headers={
                "Accept": UA["Accept"],
                "Accept-Language": UA["Accept-Language"],
                "Upgrade-Insecure-Requests": "1",
            },
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        # Give client scripts time to attach/replace DOM
        for _ in range(3):
            page.wait_for_timeout(800)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        # Try to bring any “Download” button into view
        try:
            page.locator("a:has-text('Download')").first.scroll_into_view_if_needed(timeout=1500)
            page.wait_for_timeout(600)
        except Exception:
            pass
        # If the link is injected later, try waiting specifically for GCC_ anchor
        try:
            page.wait_for_selector("a[href*='GCC_']", timeout=2500)
        except Exception:
            pass

        html = page.content()
        ctx.close()
        browser.close()
        return html

def fetch_latest(name: str, url: str) -> dict:
    # 1) Try normal HTTP first
    try:
        r = requests.get(url, headers=UA, timeout=30)
        # If we get 403 or other error codes, we still want to try Playwright
        if r.status_code == 200:
            ver = _extract_from_html(r.text)
            if ver:
                return {"ok": True, "version": ver, "date": None, "error": None}
    except Exception as e:
        # fall through to Playwright
        last_err = f"GET failed: {e}"
    else:
        last_err = f"HTTP {r.status_code}"

    # 2) Fallback to Playwright render (if installed)
    if not _HAS_PW:
        return {
            "ok": False,
            "version": None,
            "date": None,
            "error": f"{last_err}; Playwright not available",
        }

    try:
        html = _render_with_playwright(url)
        ver = _extract_from_html(html)
        if ver:
            return {"ok": True, "version": ver, "date": None, "error": None}
        return {"ok": False, "version": None, "date": None, "error": "GCC_* link not found after render"}
    except Exception as e:
        return {"ok": False, "version": None, "date": None, "error": f"render failed: {e}"}
