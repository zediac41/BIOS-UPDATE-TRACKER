from __future__ import annotations
import os, re, json, sys, time, datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Tuple
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Accept Y/M/D with -, /, or . and normalize to YYYY-MM-DD
_DATE_YMD = re.compile(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b")

# NEW: BIOS versions on ASUS are typically numeric like 1606, 2006, 3607.
# Require 3–5 digits exactly (filters out Intel ME like 19.0.5.1992v2_S).
_BIOS_VER_NUMERIC = re.compile(r"^\d{3,5}$")

def _guess_support_url(model: str) -> str:
    slug = (
        model.strip()
        .lower()
        .replace(" ", "-")
        .replace("/", "-")
    )
    return f"https://www.asus.com/supportonly/{slug}/helpdesk_bios/"

def _normalize_iso(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip()
    # normalize 2025/07/29 or 2025.07.29 -> 2025-07-29
    s = s.replace("/", "-").replace(".", "-")
    m = _DATE_YMD.search(s)
    if not m:
        # also catch already-normalized forms like "2025-07-29"
        m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
        if not m:
            return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d).isoformat()  # -> YYYY-MM-DD
    except Exception:
        return None

def _dedupe_keep_order(items: List[Dict[str, Any]], key=lambda x: x["version"].upper()):
    seen = set()
    out = []
    for it in items:
        k = key(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out

def _pick_two_sorted(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Sort by date desc when available; undated keep original order and go last
    def k(e):
        d = e.get("date")
        if not d:
            return (1, 0)
        try:
            y, mo, da = map(int, d.split("-"))
            return (0, -dt.date(y, mo, da).toordinal())
        except Exception:
            return (1, 0)
    items_sorted = sorted(items, key=k)
    return items_sorted[:2]

def _save_debug_json(model: str, host: str, website: str, payload: Dict[str, Any]):
    if not os.getenv("ASUS_SAVE_JSON"):
        return
    dbg = Path("cache/asus-debug")
    dbg.mkdir(parents=True, exist_ok=True)
    name = f"{host}_{website}_{quote_plus(model)}.json"
    (dbg / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _save_debug_html(model: str, html_text: str):
    if not os.getenv("ASUS_SAVE_HTML"):
        return
    dbg = Path("cache/asus-debug")
    dbg.mkdir(parents=True, exist_ok=True)
    name = f"support_{quote_plus(model)}.html"
    (dbg / name).write_text(html_text, encoding="utf-8")

def _looks_like_bios_version(version_raw: str) -> bool:
    """
    Minimal, reliable BIOS gate for ASUS: version string must be 3–5 digits only.
    Examples that pass: 902, 1202, 1606, 2006, 3607
    Examples that fail: 19.0.5.1992v2_S, 19.0.5.1992V2, "Intel ME", etc.
    """
    return bool(_BIOS_VER_NUMERIC.fullmatch(version_raw.strip()))

def _call_api(model: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Try a few host/website combos. Return (items, used_url_for_card)
    """
    hosts = ["www.asus.com", "rog.asus.com"]
    websites = ["global", "us"]
    session = requests.Session()
    session.headers.update({
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.asus.com/",
        "Origin": "https://www.asus.com",
    })

    last_err = None
    for host in hosts:
        for website in websites:
            url = f"https://{host}/support/api/product.asmx/GetPDBIOS"
            params = {"website": website, "model": model}
            try:
                r = session.get(url, params=params, timeout=20)
                r.raise_for_status()
                data = r.json()
                _save_debug_json(model, host, website, data)

                items = _extract_versions_from_api(data)
                if items:
                    return items, _guess_support_url(model)
                last_err = f"no items from {host} website={website}"
            except Exception as e:
                last_err = f"{host} {website}: {e}"
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if status_code == 403:
                    raise RuntimeError(last_err) from e
            time.sleep(0.6)
    raise RuntimeError(last_err or "API calls failed")

def _support_urls(model: str, override_url: str | None = None):
    seen = set()
    for url in (override_url, _guess_support_url(model)):
        if url and url not in seen:
            seen.add(url)
            yield url

def _call_support_page(model: str, override_url: str | None = None) -> Tuple[List[Dict[str, Any]], str]:
    """
    Fallback for when ASUS' product API is unavailable. The support pages include
    the BIOS list as visible page text, so parse that before the Firmware section.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    last_err = None
    for url in _support_urls(model, override_url):
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            _save_debug_html(model, r.text)
            items = _extract_versions_from_support_html(r.text)
            if items:
                return items, url
            last_err = f"no BIOS items found on {url}"
        except Exception as e:
            last_err = f"{url}: {e}"
    raise RuntimeError(last_err or "support page fetch failed")

def _extract_versions_from_api(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Walk the ASUS payload and pick BIOS Version + Release Date only.
    We keep entries whose Version is strictly numeric (3–5 digits).
    """
    results: List[Dict[str, Any]] = []

    def visit(obj: Any):
        if isinstance(obj, dict):
            if "Version" in obj and isinstance(obj.get("Version"), str):
                version_raw = obj["Version"].strip()
                # --- BIOS-only: require numeric-only version ---
                if not _looks_like_bios_version(version_raw):
                    # skip Intel ME etc.
                    pass
                else:
                    version = version_raw  # we may append (Beta version) below
                    title = (obj.get("Title") or obj.get("title") or "")
                    is_beta = "beta" in str(title).lower() or "beta" in version_raw.lower()
                    if is_beta and "beta" not in version.lower():
                        version = f"{version} (Beta version)"

                    # dates like 2025/07/29 -> normalize to ISO
                    date_raw = (
                        obj.get("ReleaseDate") or obj.get("releaseDate") or
                        obj.get("Date") or obj.get("date") or
                        obj.get("DateTime") or obj.get("datetime")
                    )
                    date_iso = _normalize_iso(str(date_raw) if date_raw is not None else "")
                    if not date_iso:
                        date_iso = _normalize_iso(json.dumps(obj, ensure_ascii=False))

                    results.append({"version": version, "date": date_iso})

            # Recurse
            for v in obj.values():
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)

    visit(payload)

    # de-dupe keep order
    return _dedupe_keep_order(results)

def _extract_versions_from_support_html(html_text: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    results: List[Dict[str, Any]] = []
    in_bios_section = False

    for i, line in enumerate(lines):
        low = line.lower()

        if low == "bios":
            in_bios_section = True
            continue

        if not in_bios_section:
            continue

        if results and low in {"firmware", "driver & tools", "need help?", "shop and learn"}:
            break

        if not line.lower().startswith("version "):
            continue

        version_raw = line.split(" ", 1)[1].strip()
        if not _looks_like_bios_version(version_raw):
            continue

        lookahead = []
        for next_line in lines[i + 1:i + 14]:
            if next_line.lower().startswith("version "):
                break
            lookahead.append(next_line)

        date_iso = None
        for next_line in lookahead:
            date_iso = _normalize_iso(next_line)
            if date_iso:
                break

        version = version_raw
        if any("beta" in next_line.lower() for next_line in lookahead[:4]):
            version = f"{version} (Beta version)"

        results.append({"version": version, "date": date_iso})

    return _dedupe_keep_order(results)

# ---------- Public API ----------
def latest_two(model: str, override_url: str | None = None):
    """
    Returns:
      {
        "vendor": "ASUS", "model": <str>, "url": <human_support_url>,
        "versions": [{"version": "...", "date": "YYYY-MM-DD" | None}, ...],
        "ok": True/False, "error": <str-if-any>
      }
    """
    try:
        try:
            items, human_url = _call_api(model)
        except Exception as api_error:
            try:
                items, human_url = _call_support_page(model, override_url=override_url)
            except Exception as page_error:
                raise RuntimeError(f"api failed: {api_error}; support page failed: {page_error}") from page_error
        top2 = _pick_two_sorted(items)
        return {
            "vendor": "ASUS",
            "model": model,
            "url": override_url or human_url,
            "versions": top2,
            "ok": True
        }
    except Exception as e:
        return {
            "vendor": "ASUS",
            "model": model,
            "url": override_url or _guess_support_url(model),
            "versions": [],
            "ok": False,
            "error": str(e)[:200]
        }

def latest_one(model: str, override_url: str | None = None):
    res = latest_two(model, override_url=override_url)
    if res.get("ok") and res.get("versions"):
        res["versions"] = res["versions"][:1]
    return res

def latest_many(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    workers_raw = os.getenv("ASUS_WORKERS", "4")
    try:
        max_workers = max(1, int(workers_raw))
    except ValueError:
        max_workers = 4

    results: List[Dict[str, Any] | None] = [None] * len(items)

    def run_one(index: int, item: Dict[str, Any]):
        model = str(item.get("model") or "").strip()
        override_url = item.get("url")
        return index, latest_two(model, override_url=override_url)

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(items)))) as pool:
        futures = {
            pool.submit(run_one, index, item): (index, item)
            for index, item in enumerate(items)
        }
        for future in as_completed(futures):
            index, item = futures[future]
            try:
                _, result = future.result()
                results[index] = result
            except Exception as e:
                model = str(item.get("model") or "").strip()
                results[index] = {
                    "vendor": "ASUS",
                    "model": model,
                    "url": item.get("url") or _guess_support_url(model),
                    "versions": [],
                    "ok": False,
                    "error": str(e)[:200],
                }

    return [result for result in results if result is not None]

__all__ = ["latest_two", "latest_one", "latest_many"]

# ---------- CLI: print VERSIONS ONLY ----------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ASUS/ROG BIOS scraper (official API; prints only 'versions')")
    ap.add_argument("model", help="ASUS/ROG model, e.g. 'ROG STRIX B650E-F GAMING WIFI'")
    ap.add_argument("--url", dest="url", help="Override support URL for display", default=None)
    args = ap.parse_args()

    out = latest_two(args.model, override_url=args.url)
    print(json.dumps(out.get("versions", []), ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)
