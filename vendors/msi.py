# vendors/msi.py
# Playwright MSI BIOS scraper (latest TWO BIOS versions).
# - Grabs dates from a small local window around each BIOS tag to avoid cross-talk
# - Skips windows that smell like drivers/utilities/Intel ME
# - Sorts newest by date; if date missing, uses a version-aware key that considers suffix letters

import os, re, time, json, sys, datetime as dt
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------- URL helpers ----------
def _slug(s: str) -> str:
    return str(s).strip().replace(" ", "-")

def _guess_support_url(model: str) -> str:
    return f"https://us.msi.com/Motherboard/{_slug(model)}/support#down-bios"

def _variants(url: str):
    p = urlparse(url)
    hosts = ["us.msi.com", "www.msi.com"]
    anchors = ["down-bios", "bios", ""]
    seen = set()
    for h in hosts:
        for a in anchors:
            u = urlunparse(p._replace(scheme="https", netloc=h, fragment=a))
            if u not in seen:
                seen.add(u); yield u

# ---------- Patterns ----------
# BIOS tags:
#   - E7D75AMS.1P3 (AMS form)
#   - 7D75v1P3     (v-tag form; require digits on both sides of 'v' to avoid "OVERVIEW")
_PAT_AMS  = re.compile(r"\bE[0-9A-F]{5}AMS\.[0-9A-Z]{2,6}\b", re.I)
_PAT_VTAG = re.compile(r"\b(?=[0-9A-Z]*\d)[0-9A-Z]{4,6}v(?=[0-9A-Z]*\d)[0-9A-Z]{1,5}\b", re.I)

# Dates (MSI shows ISO like 2025-08-04)
_DATE_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Local-window helpers
def _window(txt: str, start: int, end: int, radius: int = 220) -> str:
    a = max(0, start - radius); b = min(len(txt), end + radius)
    return txt[a:b]

_BAD_NEAR = (
    "driver","utility","audio","realtek","lan","chipset","graphics","vga",
    "raid","sata","wireless","wifi","bluetooth","intel me","management engine"
)

def _bios_root(soup: BeautifulSoup):
    # Scope to BIOS area when possible
    root = None
    for id_ in ("down-bios", "bios"):
        root = soup.find(id=id_)
        if root: break
    if not root:
        root = soup.find(lambda t: t.name in ("a","div","section") and (t.get("name") in ("down-bios","bios")))
    return root or soup

def _parse_iso_date(s: str | None) -> dt.date | None:
    if not s: return None
    m = _DATE_ISO.search(s)
    if not m: return None
    try:
        y, mo, d = map(int, m.group(1).split("-"))
        return dt.date(y, mo, d)
    except Exception:
        return None

# ---------- MSI-specific version sort key ----------
# Handles AMS and v-tag forms; letters in suffix (e.g., 1B/1C) are ordered A<B<C...
_LETTER_RANK = {c:i for i,c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=1)}

def _version_key_parts(v: str):
    # Strip any beta label
    base = re.sub(r"\s*\(.*?\)\s*$", "", v).upper()

    # AMS form: ...AMS.<SUFFIX>
    m = re.search(r"AMS\.([0-9A-Z]+)$", base, re.I)
    suffix = None
    if m:
        suffix = m.group(1)
    else:
        # v-tag form: ....v<SUFFIX>
        m2 = re.search(r"V([0-9A-Z]+)$", base, re.I)
        if m2:
            suffix = m2.group(1)

    parts = []
    if suffix:
        # Turn e.g. '1P3' -> [1, 'P', 3]
        i = 0
        while i < len(suffix):
            if suffix[i].isdigit():
                j = i
                while j < len(suffix) and suffix[j].isdigit(): j += 1
                parts.append(int(suffix[i:j])); i = j
            else:
                parts.append(_LETTER_RANK.get(suffix[i], 0)); i += 1
    else:
        # Fallback: all integers in the string
        parts = [int(n) for n in re.findall(r"\d+", base)]

    # For descending sort with Python's ascending sort:
    parts_desc = tuple(-p for p in parts)  # letters already numeric; larger letter = newer
    return parts_desc

def _sort_latest(items):
    """
    Sort by:
      1) has date -> date desc
      2) otherwise -> version key desc (numbers/letters considered)
    """
    def k(e):
        d = _parse_iso_date(e.get("date"))
        if d:
            return (0, -d.toordinal(), _version_key_parts(e["version"]))
        return (1, _version_key_parts(e["version"]))
    return sorted(items, key=k)

# ---------- Core parse ----------
def _extract_versions_from_text(txt: str):
    """Return list of unique BIOS tags found in text, preferring AMS then v-tag."""
    out = []
    out.extend(_PAT_AMS.findall(txt))
    # allow both patterns within same window (so we don't miss form swaps)
    out.extend([t for t in _PAT_VTAG.findall(txt) if t not in out])
    return out

def _parse_versions(html: str):
    soup = BeautifulSoup(html, "html.parser")
    root = _bios_root(soup)

    results = []
    # Work at text level to capture windows cleanly
    for node in root.find_all(["li","div","section","article","tr"], recursive=True):
        block = node.get_text(" ", strip=True)
        if not block:
            continue

        # quick skip: driver/util block with no BIOS mention
        low_block = block.lower()
        if (("driver" in low_block or "utility" in low_block) and "bios" not in low_block):
            continue

        for m in re.finditer(rf"{_PAT_AMS.pattern}|{_PAT_VTAG.pattern}", block, re.I):
            win = _window(block, m.start(), m.end(), 240)
            low = win.lower()

            # Discard local windows that look like drivers/ME (unless they say BIOS)
            if any(x in low for x in _BAD_NEAR) and ("bios" not in low):
                continue

            # Version label (prefer AMS match if both found)
            vers = _extract_versions_from_text(win)
            if not vers:
                continue
            ver = vers[0].upper()

            # Beta tag if nearby
            if "beta" in low and "beta" not in ver.lower():
                ver = f"{ver} (Beta version)"

            # Date only from the local window
            d_obj = _parse_iso_date(win)
            date_iso = d_obj.isoformat() if d_obj else None

            results.append({"version": ver, "date": date_iso})

    # Fallback: whole page scan if nothing found
    if not results:
        whole = root.get_text(" ", strip=True)
        vers = _extract_versions_from_text(whole)
        for v in vers:
            results.append({"version": v.upper(), "date": None})

    # De-dup while preserving first occurrence
    seen, uniq = set(), []
    for it in results:
        k = it["version"].upper()
        if k in seen: continue
        seen.add(k); uniq.append(it)

    # Newest first
    return _sort_latest(uniq)

def _is_block_page(html: str) -> bool:
    t = (html or "").lower()
    return ("access denied" in t) or ("forbidden" in t and "msi.com" in t) or ("edgesuite.net" in t)

# ---------- Fetch with Playwright ----------
def _fetch_with_playwright(url: str, headful: bool):
    save_html = bool(os.getenv("MSI_SAVE_HTML"))
    debug_dir = Path("cache/msi-debug")
    if save_html: debug_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        if headful:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir="source/.pw-msi-profile",
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

            # Best-effort consent click
            for sel in ("text=Accept All", "text=I Agree", "text=Accept", "button:has-text('Accept')"):
                try:
                    page.locator(sel).first.click(timeout=1500); break
                except Exception:
                    pass

            # Ensure BIOS tab active and allow more time to render list
            try:
                page.get_by_role("tab", name=re.compile(r"^\s*BIOS\s*$", re.I)).click(timeout=2000)
            except Exception:
                try:
                    page.locator("a[href*='#down-bios'], a[href*='#bios']").first.click(timeout=1500)
                except Exception:
                    pass

            page.wait_for_timeout(2200)  # extra render time for newest entries
            html = page.content()

            if save_html:
                fname = re.sub(r"[^A-Za-z0-9._-]+", "_", url)[:120] + ".html"
                (debug_dir / fname).write_text(html, encoding="utf-8")
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
        "vendor": "MSI", "model": <str>, "url": <used_url>,
        "versions": [{"version": "...", "date": "YYYY-MM-DD" | None}, ...],
        "ok": True/False, "error": <str-if-any>
      }
    """
    base = override_url or _guess_support_url(model)
    force_headful = bool(os.getenv("MSI_FORCE_HEADFUL"))
    last_err = None

    for url in _variants(base):
        # 1) headless first (fast)
        if not force_headful:
            try:
                html = _fetch_with_playwright(url, headful=False)
                if _is_block_page(html): raise RuntimeError("block-page(headless)")
                items = _parse_versions(html)
                if items:
                    return {"vendor":"MSI","model":model,"url":url,"versions":items[:2],"ok":True}
            except Exception as e:
                last_err = f"headless:{e}"

        # 2) headful fallback (persistent profile keeps consent cookies)
        try:
            html = _fetch_with_playwright(url, headful=True)
            if _is_block_page(html): raise RuntimeError("block-page(headful)")
            items = _parse_versions(html)
            if items:
                return {"vendor":"MSI","model":model,"url":url,"versions":items[:2],"ok":True}
        except Exception as e:
            last_err = f"headful:{e}"

        time.sleep(1.0)

    return {
        "vendor":"MSI","model":model,"url":base,
        "versions":[], "ok":False, "error": (last_err or "fetch/parse failed")[:200]
    }

def latest_one(model: str, override_url: str = None):
    res = latest_two(model, override_url=override_url)
    if res.get("ok") and res.get("versions"):
        res["versions"] = res["versions"][:1]
    return res

__all__ = ["latest_two", "latest_one"]

# ---------- CLI: print VERSIONS ONLY ----------
if __name__ == "__main__":
    import argparse, re as _re
    ap = argparse.ArgumentParser(description="MSI BIOS scraper (prints only the 'versions' list)")
    ap.add_argument("model", help="MSI motherboard model (e.g., 'MAG B650 TOMAHAWK WIFI')")
    ap.add_argument("--url", dest="url", help="Override support URL (use BIOS tab URL)", default=None)
    args = ap.parse_args()

    res = latest_two(args.model, override_url=args.url)
    print(json.dumps(res.get("versions", []), ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("ok") else 1)
