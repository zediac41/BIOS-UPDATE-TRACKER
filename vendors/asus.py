from __future__ import annotations
import os, re, json, sys, time, datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Tuple
import requests
from urllib.parse import quote_plus

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
            time.sleep(0.6)
    raise RuntimeError(last_err or "API calls failed")

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
        items, human_url = _call_api(model)
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

__all__ = ["latest_two", "latest_one"]

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

