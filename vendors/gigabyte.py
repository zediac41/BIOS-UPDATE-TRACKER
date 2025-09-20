# vendors/gigabyte.py
# GIGABYTE BIOS scraper (latest TWO BIOS versions) using Playwright to bypass 403.
# Parsing tightened to only consider BIOS download links for the model, attach a nearby date,
# filter outliers, and sort by date first (then version) to avoid stray tokens outranking real releases.

import os, re, time, json, sys, datetime as dt
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------- URL helpers ----------
def _slug(s: str) -> str:
    return (
        str(s)
        .strip()
        .replace("/", " ")
        .replace("  ", " ")
        .replace(" ", "-")
    )

def _candidates(model: str):
    slug = _slug(model)
    base = [
        f"https://www.gigabyte.com/Motherboard/{slug}/support#support-dl-bios",
        f"https://www.gigabyte.com/Motherboard/{slug.upper()}/support#support-dl-bios",
        f"https://www.gigabyte.com/Motherboard/{slug.title()}/support#support-dl-bios",
        f"https://www.gigabyte.com/Motherboard/{slug}-rev-1x/support#support-dl-bios",
    ]
    seen = set()
    for u in base:
        if u not in seen:
            seen.add(u); yield u

def _variants(url: str):
    yield url

# ---------- Patterns ----------
# BIOS version tokens: F1..F135 with optional trailing letter (A..Z)
_PAT_F = re.compile(r"\bF(?P<num>[0-9]{1,3})(?P<let>[A-Z])?\b", re.I)

# Dates:
_DATE_YMD = re.compile(r"\b(?P<y>\d{4})[/-](?P<m>\d{2})[/-](?P<d>\d{2})\b")
_DATE_MON = re.compile(
    r"""\b
    (?P<mon>
        Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|
        May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|
        Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?
    )\.?
    \s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})
    \b""",
    re.IGNORECASE | re.VERBOSE,
)
_MON_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12
}

# obvious non-BIOS hints to ignore in the local window
_BAD_NEAR = (
    "driver","utility","audio","realtek","lan","chipset","graphics","vga",
    "raid","sata","wireless","wifi","bluetooth","firmware (non-bios)"
)

# ---------- Helpers ----------
def _bios_root(soup: BeautifulSoup):
    sel = "#support-dl-bios, section#support-dl-bios, [id*='support-dl-bios']"
    root = soup.select_one(sel)
    return root or soup

def _window(txt: str, start: int, end: int, radius: int = 260) -> tuple[str,int]:
    a = max(0, start - radius)
    b = min(len(txt), end + radius)
    return txt[a:b], (start - a)

def _norm_date_from_match_group(gdict) -> str | None:
    try:
        if {"y","m","d"} <= set(gdict):
            y, mo, d = int(gdict["y"]), int(gdict["m"]), int(gdict["d"])
            return dt.date(y, mo, d).isoformat()
        mon_token = gdict["mon"].lower().rstrip(".")
        if mon_token.startswith("september"): mon_token = "sep"
        if mon_token not in _MON_MAP and mon_token.startswith("sep"): mon_token = "sept"
        mo = _MON_MAP.get(mon_token[:4] if mon_token not in _MON_MAP else mon_token, _MON_MAP.get(mon_token[:3], None))
        y = int(gdict["year"]); d = int(gdict["day"])
        return dt.date(y, mo, d).isoformat() if mo else None
    except Exception:
        return None

def _nearest_date_iso(win_text: str, center_idx: int) -> str | None:
    best = None
    def consider(m):
        nonlocal best
        s = m.start()
        dist = abs(s - center_idx)
        iso = _norm_date_from_match_group(m.groupdict())
        if not iso: return
        if (best is None) or (dist < best[0]):
            best = (dist, iso)
    for m in _DATE_YMD.finditer(win_text): consider(m)
    for m in _DATE_MON.finditer(win_text): consider(m)
    return best[1] if best else None

_LETTER_RANK = {c:i for i,c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=1)}
def _version_key(ver: str):
    """
    Key for version tie-breakers:
      F<number><letter?>  -> (number desc, letter_rank desc)
    """
    m = _PAT_F.search(ver.upper())
    if not m:
        return (float("-inf"), float("-inf"))
    num = int(m.group("num"))
    let = m.group("let").upper() if m.group("let") else ""
    lr = _LETTER_RANK.get(let, 0)
    return (-num, -lr)

def _sort_latest(items):
    """
    NEW: sort by date (newest first), then by F-number/letter.
    This prevents a stray big F-number (e.g., F79B) from outranking the real newest (e.g., F8B).
    """
    def k(e):
        d = e.get("date")
        d_ord = -dt.date.fromisoformat(d).toordinal() if (d and re.match(r"^\d{4}-\d{2}-\d{2}$", d)) else float("inf")
        vkey = _version_key(e.get("version",""))
        return (d_ord, vkey)
    return sorted(items, key=k)

def _num_part(ver: str) -> int | None:
    m = _PAT_F.search((ver or "").upper())
    return int(m.group("num")) if m else None

def _filter_outliers(items):
    """
    If there is a tight cluster of small F-numbers (e.g., 7 and 8),
    drop huge outliers (e.g., 79) that are likely from unrelated elements.
    Heuristic: compute median; keep items with num <= median+20 (generous).
    """
    nums = [n for n in (_num_part(x.get("version","")) for x in items) if n is not None]
    if len(nums) < 2:
        return items
    nums_sorted = sorted(nums)
    median = nums_sorted[len(nums_sorted)//2]
    filtered = [x for x in items if (_num_part(x.get("version","")) or 0) <= (median + 20)]
    return filtered if filtered else items

# ---------- Parsing ----------
def _parse_versions(html: str):
    soup = BeautifulSoup(html, "html.parser")
    root = _bios_root(soup)

    results = []

    # (A) Prefer anchors that clearly point to BIOS zip files inside the BIOS section
    anchors = root.select("a[href$='.zip'], a[href*='.zip?']")
    for a in anchors:
        href = a.get("href","")
        low = href.lower()
        if "bios" not in low:  # only BIOS packages
            continue

        # Extract version from filename or surrounding text
        ver = None
        m = _PAT_F.search(href)
        if m:
            ver = m.group(0).upper()

        # Gather local text from a nearby container for date sniffing
        block = a
        blk_text = ""
        for _ in range(3):  # climb a few levels to reach the item row/card
            if block is None: break
            blk_text = block.get_text(" ", strip=True) or blk_text
            block = block.parent

        # Require BIOS/Version context in the text block
        if ("bios" not in blk_text.lower()) and ("version" not in blk_text.lower()):
            continue

        # If version not found in href, try the text block
        if not ver:
            m2 = _PAT_F.search(blk_text)
            if not m2:
                continue
            ver = m2.group(0).upper()

        # Couple to nearest date within the same block text
        idx = blk_text.upper().find(ver)
        if idx < 0:
            idx = max(0, len(blk_text)//2)
        date_iso = _nearest_date_iso(blk_text, idx)
        if not date_iso:
            continue

        # Mark Beta if present near the block text
        if ("beta" in blk_text.lower()) and ("BETA" not in ver):
            ver = f"{ver} (Beta version)"

        results.append({"version": ver, "date": date_iso})

    # (B) Fallback: scan only within the BIOS root (NOT whole page), keeping only tokens near a date
    if not results:
        flat = root.get_text(" ", strip=True)
        flat_low = flat.lower()
        if "bios" in flat_low:
            for m in _PAT_F.finditer(flat):
                win, center = _window(flat, m.start(), m.end(), radius=320)
                date_iso = _nearest_date_iso(win, center)
                if date_iso:
                    ver = m.group(0).upper()
                    results.append({"version": ver, "date": date_iso})

    # De-dup (keep first occurrence)
    seen, uniq = set(), []
    for it in results:
        key = (it["version"].upper(), it.get("date"))
        if key in seen:
            continue
        seen.add(key); uniq.append(it)

    # NEW: prune obvious outliers, then sort (date-first)
    uniq = _filter_outliers(uniq)
    return _sort_latest(uniq)

def _is_block(html: str) -> bool:
    t = (html or "").lower()
    return ("access denied" in t) or ("forbidden" in t and "gigabyte.com" in t)

# ---------- Fetch with Playwright ----------
def _fetch_with_playwright(url: str, headful: bool):
    save_html = bool(os.getenv("GIGABYTE_SAVE_HTML"))
    debug_dir = Path("cache/gigabyte-debug")
    if save_html: debug_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        if headful:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir="source/pw-gigabyte-profile",
                headless=False,
                viewport={"width": 1280, "height": 900},
                user_agent=_UA,
                locale="en-US",
            )
            page = ctx.new_page()
            browser = None
        else:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_UA, locale="en-US", viewport={"width": 1280, "height": 900})
            page = ctx.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)

            # Consent (best-effort)
            for sel in ("text=Accept All", "text=I Agree", "text=Accept", "button:has-text('Accept')"):
                try:
                    page.locator(sel).first.click(timeout=1500); break
                except Exception:
                    pass

            # Ensure BIOS tab is active
            try:
                page.get_by_role("tab", name=re.compile(r"^\s*BIOS\s*$", re.I)).click(timeout=2000)
            except Exception:
                try:
                    page.locator("a[href*='#support-dl-bios']").first.click(timeout=1500)
                except Exception:
                    pass

            page.wait_for_timeout(1800)
            html = page.content()

            if save_html:
                fname = re.sub(r"[^A-Za-z0-9._-]+", "_", url)[:120] + ".html"
                (debug_dir / fname).write_text(html, encoding="utf-8")
            return html
        finally:
            try: ctx.close()
            except Exception: pass
            try:
                if browser: browser.close()
            except Exception:
                pass

# ---------- Public API ----------
def latest_two(model: str, override_url: str = None):
    urls = [override_url] if override_url else list(_candidates(model))
    force_headful = bool(os.getenv("GIGABYTE_FORCE_HEADFUL"))
    last_err = None

    for base in urls:
        for url in _variants(base):
            if not force_headful:
                try:
                    html = _fetch_with_playwright(url, headful=False)
                    if _is_block(html): raise RuntimeError("block-page(headless)")
                    items = _parse_versions(html)
                    if items:
                        return {"vendor":"GIGABYTE","model":model,"url":url,"versions":items[:2],"ok":True}
                except Exception as e:
                    last_err = f"headless:{e}"

            try:
                html = _fetch_with_playwright(url, headful=True)
                if _is_block(html): raise RuntimeError("block-page(headful)")
                items = _parse_versions(html)
                if items:
                    return {"vendor":"GIGABYTE","model":model,"url":url,"versions":items[:2],"ok":True}
            except Exception as e:
                last_err = f"headful:{e}"

            time.sleep(0.8)

    return {
        "vendor":"GIGABYTE","model":model,"url":urls[0] if urls else "",
        "versions":[], "ok":False, "error": (last_err or "fetch/parse failed")[:200]
    }

def latest_one(model: str, override_url: str = None):
    res = latest_two(model, override_url=override_url)
    if res.get("ok") and res.get("versions"):
        res["versions"] = res["versions"][:1]
    return res

__all__ = ["latest_two", "latest_one"]

# ---------- CLI ----------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="GIGABYTE BIOS scraper (prints only the 'versions' list)")
    ap.add_argument("model", help="GIGABYTE model (e.g., 'B650 AORUS ELITE AX')")
    ap.add_argument("--url", dest="url", help="Override support URL (use BIOS tab URL)", default=None)
    args = ap.parse_args()

    res = latest_two(args.model, override_url=args.url)
    print(json.dumps(res.get("versions", []), ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("ok") else 1)
