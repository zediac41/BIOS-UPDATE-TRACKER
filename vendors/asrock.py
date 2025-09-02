# vendors/asrock.py
# ASRock BIOS scraper (latest TWO BIOS versions) using Playwright.
# - Loads product page BIOS section
# - Parses Version + Date (YYYY/MM/DD or YYYY-MM-DD -> ISO)
# - Sorts all entries by date desc (fallback: numeric version desc), then returns top 2
#
# Env (optional):
#   ASROCK_FORCE_HEADFUL=1  -> visible Chromium with persistent profile (helps for one-time cookie/region)
#   ASROCK_SAVE_HTML=1      -> save rendered HTML to cache/asrock-debug/ for debugging
#
# CLI (prints versions only):
#   python vendors/asrock.py "B660M-HDV" \
#     --url "https://www.asrock.com/mb/Intel/B660M-HDV/index.asp#BIOS"

from __future__ import annotations
import os, re, time, json, sys, datetime as dt
from pathlib import Path
from urllib.parse import quote
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------- URL helpers ----------
def _candidates(model: str):
    slug = quote(model, safe="")
    yield f"https://www.asrock.com/MB/AllSeries/{slug}/index.asp#BIOS"
    yield f"https://www.asrock.com/mb/AMD/{slug}/index.asp#BIOS"
    yield f"https://www.asrock.com/mb/Intel/{slug}/index.asp#BIOS"

def _variants(url: str):
    yield url

# ---------- Parsing ----------
# Version patterns seen on ASRock: 19.03, 2.50, P1.90, L2.31, 3.10A
# (optional leading letter, at least one digit, up to two dot groups, optional trailing letter)
_PAT_VER = re.compile(r"\b([A-Za-z]?\d+(?:\.\d+){0,2}[A-Za-z]?)\b")

# Dates like 2025/07/29 or 2025-07-29
_DATE_YMD = re.compile(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b")

def _bios_root(soup: BeautifulSoup):
    # Try to scope around the BIOS area
    root = soup.select_one("#BIOS, [id*='BIOS' i], [name='BIOS']")
    if root:
        parent = root.find_parent(["section", "div"]) or root
        return parent
    # Heading with 'BIOS'
    for h in soup.find_all(["h1","h2","h3","h4","h5","h6"]):
        if "bios" in (h.get_text(strip=True) or "").lower():
            return h.find_parent(["section","div"]) or h.parent or soup
    return soup

def _norm_date(txt: str | None) -> str | None:
    if not txt:
        return None
    m = _DATE_YMD.search(txt)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d).isoformat()  # YYYY-MM-DD
    except Exception:
        return None

def _looks_like_bios_node(txt: str) -> bool:
    t = txt.lower()
    # keep nodes tied to BIOS; avoid utilities/drivers/ME
    if "bios" not in t:
        return False
    if any(b in t for b in ("intel me", "management engine", "utility", "driver")):
        return False
    return True

def _version_sort_key(ver: str):
    """
    Fallback numeric sort for versions when dates are missing or equal.
    - Strip '(Beta version)'
    - Extract optional prefix letter, numeric groups, optional suffix letter.
    - Higher numbers sort newer.
    """
    base = re.sub(r"\s*\(.*?\)\s*$", "", ver).strip()  # remove " (Beta version)"
    m = re.match(r"^([A-Za-z]?)(\d+(?:\.\d+){0,3})([A-Za-z]?)$", base)
    if not m:
        return (1, base)  # unknown shape -> keep stable order after dated ones
    prefix, nums, suffix = m.groups()
    parts = tuple(int(x) for x in nums.split("."))
    # Prefix/suffix letters only break ties among same numeric; we don't define global letter order
    return (0, parts, prefix.upper(), suffix.upper())

def _sort_latest(items):
    """
    Sort by: (has_date first) -> date desc -> version desc (numeric aware)
    """
    def k(e):
        d = e.get("date")
        if d:
            try:
                y, mo, da = map(int, d.split("-"))
                return (0, -dt.date(y, mo, da).toordinal(), _version_sort_key(e["version"]))
            except Exception:
                pass
        return (1, _version_sort_key(e["version"]))
    return sorted(items, key=k)

def _parse_versions(html: str):
    soup = BeautifulSoup(html, "html.parser")
    root = _bios_root(soup)

    candidates = root.find_all(["tr", "li", "div", "section", "article"], recursive=True)
    results = []

    for node in candidates:
        txt = node.get_text(" ", strip=True)
        if not txt:
            continue

        # Prefer BIOS-marked blocks, but also allow version-pattern blocks to avoid missing latest cards.
        if not (_looks_like_bios_node(txt) or _PAT_VER.search(txt)):
            continue

        mver = _PAT_VER.search(txt)
        if not mver:
            continue

        ver = mver.group(1).strip()
        # Avoid lone year/number (e.g., "2024") that can match _PAT_VER
        if ver.isdigit() and (len(ver) <= 2 or int(ver) > 3000):
            continue

        # Tag beta if present
        if "beta" in txt.lower() and "beta" not in ver.lower():
            ver = f"{ver} (Beta version)"

        date_iso = _norm_date(txt)
        results.append({"version": ver, "date": date_iso})

    # Fallback: global scan
    if not results:
        flat = soup.get_text(" ", strip=True)
        mver = _PAT_VER.search(flat)
        if mver:
            ver = mver.group(1).strip()
            if "beta" in flat.lower() and "beta" not in ver.lower():
                ver = f"{ver} (Beta version)"
            results.append({"version": ver, "date": _norm_date(flat)})

    # De-dup while preserving order of first occurrence
    seen, uniq = set(), []
    for it in results:
        k = it["version"].upper()
        if k in seen: continue
        seen.add(k); uniq.append(it)

    # ---- NEW: sort newest-first and return top 2 ----
    sorted_items = _sort_latest(uniq)
    return sorted_items

def _is_block_page(html: str) -> bool:
    t = (html or "").lower()
    return ("access denied" in t) or ("forbidden" in t and "asrock.com" in t)

# ---------- Fetch with Playwright ----------
def _fetch_with_playwright(url: str, headful: bool):
    save_html = bool(os.getenv("ASROCK_SAVE_HTML"))
    debug_dir = Path("cache/asrock-debug")
    if save_html:
        debug_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        if headful:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir="source/pw-asrock-profile",
                headless=False,
                viewport={"width": 1280, "height": 900},
                user_agent=_UA,
                locale="en-US",
            )
            page = ctx.new_page()
        else:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_UA, locale="en-US", viewport={"width": 1280, "height": 900})
            page = ctx.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)

            # Cookie/consent (best-effort)
            for sel in ("text=Accept", "text=I Agree", "text=OK", "button:has-text('Accept')"):
                try:
                    page.locator(sel).first.click(timeout=1200); break
                except Exception:
                    pass

            # Ensure BIOS anchor is visible
            try:
                page.locator("a[href*='#BIOS']").first.click(timeout=1500)
            except Exception:
                pass

            # Give the list time to populate
            page.wait_for_timeout(2300)
            html = page.content()

            if save_html:
                safe = re.sub(r"[^A-Za-z0-9._-]+", "_", url)[:120] + ".html"
                (debug_dir / safe).write_text(html, encoding="utf-8")
            return html
        finally:
            try: ctx.close()
            except Exception: pass
            try: browser.close()
            except Exception: pass

# ---------- Public API ----------
def latest_two(model: str, override_url: str = None):
    """
    Returns:
      {
        "vendor": "ASRock", "model": <str>, "url": <used_url>,
        "versions": [{"version": "...", "date": "YYYY-MM-DD" | None}, ...],
        "ok": True/False, "error": <str-if-any>
      }
    """
    urls = [override_url] if override_url else list(_candidates(model))
    force_headful = bool(os.getenv("ASROCK_FORCE_HEADFUL"))
    last_err = None

    for base in urls:
        for url in _variants(base):
            if not force_headful:
                try:
                    html = _fetch_with_playwright(url, headful=False)
                    if _is_block_page(html): raise RuntimeError("block-page(headless)")
                    items = _parse_versions(html)
                    if items:
                        items = items[:2]
                        return {"vendor":"ASRock","model":model,"url":url,"versions":items,"ok":True}
                except Exception as e:
                    last_err = f"headless:{e}"

            try:
                html = _fetch_with_playwright(url, headful=True)
                if _is_block_page(html): raise RuntimeError("block-page(headful)")
                items = _parse_versions(html)
                if items:
                    items = items[:2]
                    return {"vendor":"ASRock","model":model,"url":url,"versions":items,"ok":True}
            except Exception as e:
                last_err = f"headful:{e}"

            time.sleep(0.8)

    return {"vendor":"ASRock","model":model,"url":urls[0] if urls else "", "versions":[], "ok":False, "error": (last_err or "fetch/parse failed")[:200]}

def latest_one(model: str, override_url: str = None):
    res = latest_two(model, override_url=override_url)
    if res.get("ok") and res.get("versions"):
        res["versions"] = res["versions"][:1]
    return res

__all__ = ["latest_two", "latest_one"]

# ---------- CLI: print VERSIONS ONLY ----------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ASRock BIOS scraper (prints only the 'versions' list)")
    ap.add_argument("model", help="ASRock model (e.g., 'B660M-HDV')")
    ap.add_argument("--url", dest="url", help="Override support URL (use the BIOS anchor URL)", default=None)
    args = ap.parse_args()

    res = latest_two(args.model, override_url=args.url)
    print(json.dumps(res.get("versions", []), ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("ok") else 1)
