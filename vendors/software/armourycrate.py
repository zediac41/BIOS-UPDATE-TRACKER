# vendors/software/armourycrate.py
# ASUS Armoury Crate — ONLY read the tile titled:
#   "Armoury Crate & Aura Creator Installer"
# Uses your exact URL from config.yml. Static parse first; if needed, Playwright (headful)
# dismisses locale popup and inspects BOTH main page and any IFRAMES.
# Returns version only. Writes debug HTML snapshots to cache/software-debug/.

from __future__ import annotations
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# Optional Playwright fallback
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

TITLE_CANON = "armoury crate & aura creator installer"

def _canon(txt: str) -> str:
    s = (txt or "").lower()
    s = s.replace("\xa0", " ")
    s = s.replace("&amp;", "&").replace("＆", "&")
    s = re.sub(r"\s+", " ", s).strip(" .,:;!-_").strip()
    return s

# Versions
NEAR_VER_RX = re.compile(r"(?i)\bversion\b[^0-9a-z]{0,24}(\d+(?:\.\d+){1,3})")
VER_RX      = re.compile(r"\bv?(\d+(?:\.\d+){1,3})\b")
LINK_VER_RX = re.compile(r"(?i)(?:armou?r?y\s*crate|aura\s*creator|armourycrateinstaller|ac)[^/]*?[_-]v?(\d+(?:\.\d+){1,3})")

def _vkey(v: str):
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))

def _maybe_anchor(url: str) -> str:
    return url if "#" in url else (url + "#utility")

def _requests_html(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.text

def _extract_version_from_text(text: str) -> str | None:
    near = [m.group(1) for m in NEAR_VER_RX.finditer(text)]
    near_pref = [v for v in near if v.count(".") >= 2]
    if near_pref or near:
        arr = near_pref or near
        arr.sort(key=_vkey, reverse=True)
        return arr[0]
    cands = [m.group(1) for m in VER_RX.finditer(text)]
    pref  = [v for v in cands if v.count(".") >= 2]
    if pref or cands:
        arr = pref or cands
        arr.sort(key=_vkey, reverse=True)
        return arr[0]
    return None

def _parse_grid_exact(soup: BeautifulSoup) -> str | None:
    for sec in soup.select("section.spec, .spec"):
        spans = list(sec.find_all("span"))
        if len(spans) < 8:
            continue
        header_idx = None
        for i in range(0, len(spans) - 3):
            hdr = [spans[i+j].get_text(strip=True).lower() for j in range(4)]
            if "title" in hdr[0] and "version" in hdr[1]:
                header_idx = i + 4
                break
        if header_idx is None:
            continue
        data = spans[header_idx:]
        for i in range(0, len(data), 4):
            row = data[i:i+4]
            if len(row) < 2:
                continue
            title_txt = row[0].get_text(strip=True)
            if _canon(title_txt) != TITLE_CANON:
                continue
            ver_cell = row[1].get_text(" ", strip=True)
            v = _extract_version_from_text(ver_cell)
            if v:
                return v
            parent_text = row[1].parent.get_text(" ", strip=True) if hasattr(row[1], "parent") else ver_cell
            v2 = _extract_version_from_text(parent_text)
            if v2:
                return v2
    return None

def _parse_card_exact(soup: BeautifulSoup) -> str | None:
    for sel in ["h1","h2","h3","h4","h5","h6",".title",".card-title",".item-title",".item-name"]:
        for node in soup.select(sel):
            title_txt = node.get_text(" ", strip=True)
            if _canon(title_txt) != TITLE_CANON:
                continue
            parent = node
            for _ in range(6):
                if not getattr(parent, "parent", None):
                    break
                text_len = len(parent.get_text(" ", strip=True))
                if 40 <= text_len <= 8000:
                    break
                parent = parent.parent
            text = parent.get_text(" ", strip=True)
            v = _extract_version_from_text(text)
            if v:
                return v
            found = []
            for a in parent.find_all("a"):
                blob = ((a.get("href") or "") + " " + a.get_text(" ", strip=True)).strip()
                m = LINK_VER_RX.search(blob)
                if m:
                    vv = m.group(1)
                    if vv.count(".") >= 2:
                        found.append(vv)
            if found:
                found.sort(key=_vkey, reverse=True)
                return found[0]
    return None

def _parse_text_window(html: str) -> str | None:
    t = html.replace("\xa0", " ").replace("&amp;", "&").replace("＆", "&")
    t_low = re.sub(r"\s+", " ", t).lower()
    idx = t_low.find(TITLE_CANON)
    if idx == -1:
        return None
    window = t[idx : idx + 1200]
    m = re.search(r"(?i)\bversion\b[^0-9a-z]{0,24}(\d+(?:\.\d+){1,3})", window)
    if m and m.group(1).count(".") >= 2:
        return m.group(1)
    m2 = re.search(r"(?i)(?:armou?r?y\s*crate|aura\s*creator|armourycrateinstaller|ac)[^/]{0,160}?[_-]v?(\d+(?:\.\d+){1,3})", window)
    if m2 and m2.group(1).count(".") >= 2:
        return m2.group(1)
    return None

# ---------- Playwright: main page + IFRAMES ----------

_STAY_BUTTONS = [
    "button:has-text('Stay')",
    "button:has-text('Stay here')",
    "button:has-text('Continue')",
    "button:has-text('Continue on current site')",
    "button:has-text('Stay on current site')",
    "a:has-text('Stay')",
    "a:has-text('Continue')",
]

_JS_EXTRACT = r"""
() => {
  const canon = (s) => (s || "")
    .toLowerCase()
    .replace(/\u00a0/g, " ")
    .replace(/&amp;|＆/g, "&")
    .replace(/\s+/g, " ")
    .replace(/[ .,:;!\-_]+$/g,"")
    .trim();
  const TARGET = "armoury crate & aura creator installer";
  const pickVersion = (txt) => {
    if (!txt) return null;
    // Prefer "Version x.y.z"
    let m = txt.match(/Version[^0-9a-zA-Z]{0,24}(\d+(?:\.\d+){1,3})/i);
    if (m && (m[1].match(/\./g)||[]).length >= 2) return m[1];
    // Fallback: dotted tokens
    const all = Array.from(txt.matchAll(/\b(\d+(?:\.\d+){1,3})\b/g)).map(x=>x[1]);
    const pref = all.filter(v => (v.match(/\./g)||[]).length >= 2);
    const list = pref.length ? pref : all;
    if (!list.length) return null;
    const vkey = (v) => v.split('.').map(x=>parseInt(x,10)||0);
    list.sort((a,b) => {
      const aa=vkey(a), bb=vkey(b);
      for (let i=0;i<Math.max(aa.length,bb.length);i++){
        const d=(bb[i]||0)-(aa[i]||0); if(d) return d;
      }
      return 0;
    });
    return list[0];
  };

  // 1) Find exact-title nodes
  const all = Array.from(document.querySelectorAll('body *'));
  const titleNodes = all.filter(n => canon(n.textContent) === TARGET);
  // 2) If found, walk up to a compact parent that contains both title and version
  if (titleNodes.length) {
    let bestV = null, bestLen = Infinity;
    for (const n of titleNodes) {
      let cur = n;
      for (let up = 0; up < 6 && cur; up++, cur = cur.parentElement) {
        const txt = (cur.innerText || cur.textContent || "").trim();
        const v = pickVersion(txt);
        if (v) {
          if (txt.length < bestLen) { bestLen = txt.length; bestV = v; }
          break;
        }
      }
    }
    if (bestV) return bestV;
  }

  // 3) Fallback: text-window search after the first occurrence of the canonical title
  const whole = (document.body.innerText || document.body.textContent || "").replace(/\s+/g," ");
  const idx = canon(whole).indexOf(TARGET);
  if (idx >= 0) {
    const window = whole.slice(idx, idx + 1500);
    const v = pickVersion(window);
    if (v) return v;
  }
  return null;
}
"""

def _render_and_extract(url: str) -> tuple[str, str | None]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
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

        # Locale modal: stay on current site
        for sel in _STAY_BUTTONS:
            try:
                page.locator(sel).first.click(timeout=1000)
                page.wait_for_timeout(300)
                break
            except Exception:
                pass
        # Generic modal close
        for sel in ["button[aria-label*=close]", ".modal [aria-label*=close]", ".modal .close", ".close"]:
            try:
                page.locator(sel).first.click(timeout=700)
                page.wait_for_timeout(200)
                break
            except Exception:
                pass

        # Ensure downloads/utilities section visible (harmless if already)
        for sel in [
            "a[href*='#utility']",
            "a:has-text('Utility')",
            "a:has-text('Drivers and Tools')",
            "a:has-text('Downloads')",
        ]:
            try:
                page.locator(sel).first.click(timeout=1200)
                page.wait_for_timeout(300)
                break
            except Exception:
                pass

        # Let cards render / lazy-load
        for _ in range(4):
            page.wait_for_timeout(600)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        # 1) Try in main page
        ver = None
        try:
            ver = page.evaluate(_JS_EXTRACT)
        except Exception:
            ver = None

        # 2) If not found, iterate IFRAMES
        if not ver:
            for idx, frame in enumerate(page.frames):
                if frame == page.main_frame:
                    continue
                try:
                    v2 = frame.evaluate(_JS_EXTRACT)
                except Exception:
                    v2 = None
                if v2:
                    ver = v2
                    break

        # Gather HTML snapshots (main + frames) for debugging
        main_html = page.content()
        try:
            out = Path("cache/software-debug")
            out.mkdir(parents=True, exist_ok=True)
            (out / "armoury-crate_main.html").write_text(main_html, encoding="utf-8")
            for i, fr in enumerate(page.frames):
                if fr == page.main_frame:
                    continue
                try:
                    fh = fr.content()
                except Exception:
                    fh = f"<!-- unable to read frame {i} content; url={fr.url} -->"
                (out / f"armoury-crate_frame_{i}.html").write_text(f"<!-- url: {fr.url} -->\n" + fh, encoding="utf-8")
        except Exception:
            pass

        ctx.close(); browser.close()
        return main_html, ver

# ---------------- Entry point ----------------

def fetch_latest(name: str, url: str) -> dict:
    url = _maybe_anchor(url)

    # 1) Static HTML
    try:
        html = _requests_html(url)
        soup = BeautifulSoup(html, "html.parser")
        ver = _parse_grid_exact(soup) or _parse_card_exact(soup) or _parse_text_window(html)
        if ver:
            return {"ok": True, "version": ver, "date": None, "error": None}
        last_err = "version not found in static HTML"
    except Exception as e:
        last_err = f"GET failed: {e}"

    # 2) Playwright: main + iframes
    if not _HAS_PW:
        return {"ok": False, "version": None, "date": None, "error": f"{last_err}; Playwright not available"}

    try:
        main_html, ver = _render_and_extract(url)
        if ver:
            return {"ok": True, "version": ver, "date": None, "error": None}
        # As a second pass, try parsing rendered main HTML (some content may get inlined)
        soup = BeautifulSoup(main_html, "html.parser")
        ver2 = _parse_grid_exact(soup) or _parse_card_exact(soup) or _parse_text_window(main_html)
        if ver2:
            return {"ok": True, "version": ver2, "date": None, "error": None}
        return {"ok": False, "version": None, "date": None, "error": "version not found after render (main + iframes)"}
    except Exception as e:
        return {"ok": False, "version": None, "date": None, "error": f"render failed: {e}"}
