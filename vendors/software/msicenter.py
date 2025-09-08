# vendors/software/msicenter.py
# MSI Center — parse ONLY the provided motherboard page (e.g., .../support#utility).
# No OS selection or "expand" clicks. We strictly read the Utilities block.
# If the grid is JS-rendered, we render with Playwright and extract from the live DOM.
# Returns only the version string (no dates).

from __future__ import annotations
import re
import os
import requests
from bs4 import BeautifulSoup

# Playwright only if static HTML lacks the grid/content
try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _HAS_PW = True
except Exception:
    _HAS_PW = False

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Strict title for the utility row
MSI_TITLE_EXACT = re.compile(r"(?i)^\s*msi\s*center\s*$")
# Filter misleading titles
BAD_TITLE = re.compile(r"(?i)\b(google|play|gpg|sdk|extension|plugin)\b")

# Dotted versions; prefer 3–4 segments
VER_RX      = re.compile(r"\bv?(\d+(?:\.\d+){1,3})\b")
NEAR_VER_RX = re.compile(r"(?i)version[^0-9a-z]{0,20}(\d+(?:\.\d+){1,3})")

def _maybe_anchor(url: str) -> str:
    # Keep it simple: nudge to utilities anchor if absent.
    return url if "#" in url else (url + "#utility")

def _vkey(v: str):
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))

def _requests_html(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.text

def _parse_utilities_grid(soup: BeautifulSoup) -> str | None:
    """
    Look for a 4-col grid like: Title | Version | Release Date | File Size
    Return the best version in the row whose Title is exactly 'MSI Center'.
    """
    for sec in soup.select("section.spec, .spec"):
        spans = [s.get_text(strip=True) for s in sec.find_all("span")]
        if len(spans) < 8:
            continue

        # Find header: ['Title', 'Version', ...]
        hdr = None
        for i in range(0, len(spans) - 3):
            header = [t.lower() for t in spans[i:i+4]]
            if "title" in header[0] and "version" in header[1]:
                hdr = i + 4
                break
        if hdr is None:
            continue

        # Parse rows of 4
        data = spans[hdr:]
        found_versions = []
        for i in range(0, len(data), 4):
            row = data[i:i+4]
            if len(row) < 2:
                continue
            title_txt = row[0]
            ver_cell  = row[1]

            if not MSI_TITLE_EXACT.search(title_txt):
                continue
            if BAD_TITLE.search(title_txt):
                continue

            # Prefer "Version x.y.z" phrasing inside version cell
            near = [m.group(1) for m in NEAR_VER_RX.finditer(ver_cell)]
            near = [v for v in near if v.count(".") >= 2]
            if near:
                found_versions.extend(near)
                continue

            # Otherwise, any dotted token in version cell; prefer 3–4 segments
            cands = [m.group(1) for m in VER_RX.finditer(ver_cell)]
            cands = [v for v in cands if v.count(".") >= 2] or cands
            found_versions.extend(cands)

        if found_versions:
            return sorted(found_versions, key=_vkey, reverse=True)[0]

    # Fallback: tables with headers "Title" and "Version"
    for table in soup.select("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")]
        if headers and "title" in headers[0] and "version" in headers[1]:
            for tr in table.select("tbody tr, tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.select("th,td")]
                if len(cells) < 2:
                    continue
                title_txt, ver_cell = cells[0], cells[1]
                if not MSI_TITLE_EXACT.search(title_txt) or BAD_TITLE.search(title_txt):
                    continue

                near = [m.group(1) for m in NEAR_VER_RX.finditer(ver_cell)]
                near = [v for v in near if v.count(".") >= 2]
                if near:
                    return sorted(near, key=_vkey, reverse=True)[0]

                cands = [m.group(1) for m in VER_RX.finditer(ver_cell)]
                cands = [v for v in cands if v.count(".") >= 2] or cands
                if cands:
                    return sorted(cands, key=_vkey, reverse=True)[0]

    return None

# ---- Playwright helpers (only if needed) ----

_JS_GET_VERSION = r"""
() => {
  const norm = (el) => (el ? (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim() : '');
  const all  = Array.from(document.querySelectorAll('body *'));
  // Find nodes that mention "MSI Center" (exact-ish)
  const candidates = all.filter(n => /\bmsi\s*center\b/i.test(norm(n)) && !/\b(google|play|gpg|sdk|extension|plugin)\b/i.test(norm(n)));
  if (candidates.length === 0) return null;

  // Pick the smallest container that also mentions "Version"
  let winner = null;
  let bestLen = 1e12;
  for (const n of candidates) {
    let node = n;
    for (let up=0; up<6 && node; up++, node = node.parentElement) {
      const txt = norm(node);
      if (/version/i.test(txt)) {
        if (txt.length < bestLen) {
          bestLen = txt.length;
          winner = node;
        }
        break;
      }
    }
  }
  if (!winner) winner = candidates.sort((a,b)=>norm(a).length - norm(b).length)[0];

  const txt = norm(winner);
  // Prefer "Version ... x.y.z" (3–4 segments)
  let m = txt.match(/Version[^0-9a-zA-Z]{0,20}(\d+(?:\.\d+){1,3})/i);
  if (m && (m[1].match(/\./g) || []).length >= 2) return m[1];

  // Otherwise, any dotted token (prefer 3–4 segments)
  const allVers = Array.from(txt.matchAll(/\b(\d+(?:\.\d+){1,3})\b/g)).map(x => x[1]);
  const prefer  = allVers.filter(v => (v.match(/\./g) || []).length >= 2);
  const list    = (prefer.length ? prefer : allVers);

  if (!list.length) return null;

  const vkey = (v) => v.split('.').map(x => parseInt(x,10)||0);
  list.sort((a,b) => {
    const aa = vkey(a), bb = vkey(b);
    for (let i=0;i<Math.max(aa.length,bb.length);i++){
      const d = (bb[i]||0) - (aa[i]||0);
      if (d) return d;
    }
    return 0;
  });
  return list[0];
}
"""

def _playwright_html_and_version(url: str) -> tuple[str, str | None]:
    from pathlib import Path
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # headful reduces bot checks
            args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            user_agent=UA["User-Agent"],
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            java_script_enabled=True,
            extra_http_headers={"Accept": UA["Accept"], "Accept-Language": UA["Accept-Language"]},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")

        # Ensure Utilities tab is visible/active (harmless if already on it)
        try:
            page.locator("a[href*='#utility']").first.click(timeout=1200)
            page.wait_for_timeout(500)
        except Exception:
            pass

        # Give time for the grid to render; scroll to trigger lazy content
        for _ in range(4):
            page.wait_for_timeout(700)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        # Try DOM-level version extraction near "MSI Center"
        try:
            ver = page.evaluate(_JS_GET_VERSION)
        except Exception:
            ver = None

        html = page.content()
        ctx.close(); browser.close()

        # Write a debug snapshot you can inspect locally
        try:
            outdir = Path("cache/software-debug")
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "msi-center.html").write_text(html, encoding="utf-8")
        except Exception:
            pass

        return html, ver

# ---------------- Entry point ----------------

def fetch_latest(name: str, url: str) -> dict:
    url = _maybe_anchor(url)

    # 1) Static HTML
    try:
        html = _requests_html(url)
        soup = BeautifulSoup(html, "html.parser")
        ver = _parse_utilities_grid(soup)
        if ver:
            return {"ok": True, "version": ver, "date": None, "error": None}
        last_err = "version not found in static HTML"
    except Exception as e:
        last_err = f"GET failed: {e}"

    # 2) Playwright fallback
    if not _HAS_PW:
        return {"ok": False, "version": None, "date": None, "error": f"{last_err}; Playwright not available"}

    try:
        html, ver = _playwright_html_and_version(url)
        if not ver:
            # As a secondary pass, try the grid parser on the rendered DOM
            soup = BeautifulSoup(html, "html.parser")
            ver = _parse_utilities_grid(soup)
        if ver:
            return {"ok": True, "version": ver, "date": None, "error": None}
        return {"ok": False, "version": None, "date": None, "error": "version not found after render"}
    except Exception as e:
        return {"ok": False, "version": None, "date": None, "error": f"render failed: {e}"}
