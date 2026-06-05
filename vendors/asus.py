from __future__ import annotations
import os, re, json, sys, time, datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Tuple
import requests
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Accept Y/M/D with -, /, or . and normalize to YYYY-MM-DD
_DATE_YMD = re.compile(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b")

# NEW: BIOS versions on ASUS are typically numeric like 1606, 2006, 3607.
# Require 3–5 digits exactly (filters out Intel ME like 19.0.5.1992v2_S).
_BIOS_VER_NUMERIC = re.compile(r"^\d{3,5}$")
_BIOS_VER_IN_TEXT = re.compile(r"\b(\d{3,5})\b")

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

def _support_version_from_text(text: str) -> str | None:
    m = _BIOS_VER_IN_TEXT.search(str(text or ""))
    return m.group(1) if m else None

def _short_error(error: Exception | str, limit: int = 600) -> str:
    text = str(error)
    return text if len(text) <= limit else text[:limit - 3] + "..."

def _looks_blocked_html(html_text: str) -> bool:
    text = BeautifulSoup(html_text or "", "html.parser").get_text(" ", strip=True).lower()
    return any(token in text for token in (
        "access denied",
        "request blocked",
        "forbidden",
        "captcha",
        "verify you are human",
    ))

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
            if _looks_blocked_html(r.text):
                last_err = f"blocked by ASUS support page on {url}"
            else:
                last_err = f"no BIOS items found on {url}"
        except Exception as e:
            last_err = f"{url}: {e}"
    raise RuntimeError(last_err or "support page fetch failed")

def _new_browser_context(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        user_agent=_UA,
        locale="en-US",
        timezone_id="America/Chicago",
        viewport={"width": 1366, "height": 1200},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    _block_heavy_assets(ctx)
    return browser, ctx, ctx.new_page()

def _block_heavy_assets(ctx):
    def route_handler(route):
        if route.request.resource_type in {"image", "media", "font"}:
            route.abort()
        else:
            route.continue_()
    ctx.route("**/*", route_handler)

def _load_support_with_page(page, url: str) -> str:
    timeout_ms = int(os.getenv("ASUS_TIMEOUT_MS", "35000"))
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    for label in ("Accept All", "I Agree", "Accept"):
        try:
            page.get_by_text(label, exact=False).click(timeout=1200)
            break
        except Exception:
            pass

    try:
        page.wait_for_selector("text=Version", timeout=15000)
    except Exception:
        pass

    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1200)
    return page.content()

def _call_support_page_browser(
    model: str,
    override_url: str | None = None,
    page=None,
) -> Tuple[List[Dict[str, Any]], str]:
    last_err = None

    def use_page(active_page):
        nonlocal last_err
        for url in _support_urls(model, override_url):
            try:
                html_text = _load_support_with_page(active_page, url)
                _save_debug_html(model, html_text)
                items = _extract_versions_from_support_html(html_text)
                if items:
                    return items, url
                if _looks_blocked_html(html_text):
                    last_err = f"blocked by ASUS support page in browser on {url}"
                else:
                    last_err = f"no BIOS items found in browser on {url}"
            except Exception as e:
                last_err = f"{url}: {e}"
        raise RuntimeError(last_err or "browser support page fetch failed")

    if page is not None:
        return use_page(page)

    with sync_playwright() as p:
        browser, ctx, browser_page = _new_browser_context(p)
        try:
            return use_page(browser_page)
        finally:
            ctx.close()
            browser.close()

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

        if low == "bios" or low.startswith("bios &"):
            in_bios_section = True
            continue

        if not in_bios_section:
            continue

        if results and low in {"firmware", "driver & tools", "need help?", "shop and learn"}:
            break

        if low == "version" and i + 1 < len(lines):
            version_raw = lines[i + 1].strip()
        elif line.lower().startswith("version "):
            version_raw = line.split(" ", 1)[1].strip()
        else:
            continue

        version_clean = _support_version_from_text(version_raw)
        if not version_clean or not _looks_like_bios_version(version_clean):
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

        version = version_clean
        if any("beta" in next_line.lower() for next_line in lookahead[:4]):
            version = f"{version} (Beta version)"

        results.append({"version": version, "date": date_iso})

    return _dedupe_keep_order(results)

# ---------- Public API ----------
def _success_result(model: str, override_url: str | None, human_url: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "vendor": "ASUS",
        "model": model,
        "url": override_url or human_url,
        "versions": _pick_two_sorted(items),
        "ok": True,
    }

def _error_result(model: str, override_url: str | None, error: Exception | str) -> Dict[str, Any]:
    return {
        "vendor": "ASUS",
        "model": model,
        "url": override_url or _guess_support_url(model),
        "versions": [],
        "ok": False,
        "error": _short_error(error),
    }

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
                try:
                    items, human_url = _call_support_page_browser(model, override_url=override_url)
                except Exception as browser_error:
                    raise RuntimeError(
                        f"api failed: {api_error}; support page failed: {page_error}; "
                        f"browser page failed: {browser_error}"
                    ) from browser_error
        return _success_result(model, override_url, human_url, items)
    except Exception as e:
        return _error_result(model, override_url, e)

def latest_one(model: str, override_url: str | None = None):
    res = latest_two(model, override_url=override_url)
    if res.get("ok") and res.get("versions"):
        res["versions"] = res["versions"][:1]
    return res

def latest_many(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any] | None] = [None] * len(items)
    browser_fallbacks: List[Tuple[int, str, str | None, Exception, Exception]] = []

    for index, item in enumerate(items):
        model = str(item.get("model") or "").strip()
        override_url = item.get("url")
        try:
            api_items, human_url = _call_api(model)
            results[index] = _success_result(model, override_url, human_url, api_items)
            continue
        except Exception as api_error:
            try:
                page_items, human_url = _call_support_page(model, override_url=override_url)
                results[index] = _success_result(model, override_url, human_url, page_items)
                continue
            except Exception as page_error:
                browser_fallbacks.append((index, model, override_url, api_error, page_error))

    if browser_fallbacks:
        try:
            with sync_playwright() as p:
                browser, ctx, page = _new_browser_context(p)
                try:
                    for index, model, override_url, api_error, page_error in browser_fallbacks:
                        try:
                            browser_items, human_url = _call_support_page_browser(
                                model,
                                override_url=override_url,
                                page=page,
                            )
                            results[index] = _success_result(model, override_url, human_url, browser_items)
                        except Exception as browser_error:
                            results[index] = _error_result(
                                model,
                                override_url,
                                f"api failed: {api_error}; support page failed: {page_error}; "
                                f"browser page failed: {browser_error}",
                            )
                finally:
                    ctx.close()
                    browser.close()
        except Exception as setup_error:
            for index, model, override_url, api_error, page_error in browser_fallbacks:
                results[index] = _error_result(
                    model,
                    override_url,
                    f"api failed: {api_error}; support page failed: {page_error}; "
                    f"browser setup failed: {setup_error}",
                )

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
