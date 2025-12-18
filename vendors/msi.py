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

# Base MSI BIOS tokens like 7D37vB7, 7D75v1P3, 7E25vAA1, etc.
VERSION_BASE_RX = re.compile(r"\b([A-Za-z0-9]+v[A-Za-z0-9.]+)\b", re.I)

# Explicit label-pair form frequently seen on MSI support pages (including BULK/OEM variants):
#   "Version7D37vB7. Release Date2025-09-23"
#   "Version 7D37vB6 (Beta version) Release Date 2025/08/29"
MSI_VERSION_RELEASEDATE_RX = re.compile(
    r"Version\s*([0-9A-Za-z.]+(?:\s*\([^)]*\))?)\s*\.?\s*Release\s*Date\s*(\d{4}[./-]\d{2}[./-]\d{2})",
    re.I,
)


def _norm_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    m = DATE_RX.search(str(s))
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{mo}-{d}"


def _extract_base_version(text: Optional[str]) -> Optional[str]:
    """Return the MSI BIOS token (without any trailing '(Beta ...)' text)."""
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
    pr = urlparse(url)
    frag = pr.fragment or "bios"
    return urlunparse(pr._replace(fragment=frag))


def _guess_url_from_model(model: str) -> Optional[str]:
    slug = (model or "").strip().replace(" ", "-").replace("--", "-")
    return f"https://www.msi.com/Motherboard/{slug}/support#bios" if slug else None


def _slugify_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (model or "").strip()) or "msi-board"


# ---------- playwright fetching ----------

def _fetch_html(url: str, timeout_ms: int = 60000) -> str:
    """
    Fetch the MSI support page with Playwright and return a *combined* string containing:
      - page.content() (DOM HTML)
      - page.inner_text('body') (visible text)
      - a small set of captured JSON/XHR responses (when available)

    This combo is important for BULK/OEM pages where the BIOS list is produced via XHR and
    the DOM can be sparse or the text ends up in client-side templates.
    """
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Default to headless for CI (GitHub Actions). Set MSI_HEADFUL=1 for local debugging.
    # Back-compat: if MSIOLD_HEADFUL exists, honor it.
    headful_env = os.getenv("MSI_HEADFUL")
    if headful_env is None:
        headful_env = os.getenv("MSIOLD_HEADFUL")
    headful = True if (headful_env and headful_env.lower() in ("1", "true", "yes")) else False

    captured: List[str] = []

    def _should_capture(resp_url: str, content_type: str) -> bool:
        u = (resp_url or "").lower()
        ct = (content_type or "").lower()
        if "application/json" in ct:
            return True
        # MSI often uses non-json CTs even for structured payloads; capture likely endpoints
        return any(k in u for k in ("/api/", "support", "download", "bios", "drivers", "utilities"))

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

        page = ctx.new_page()

        # Capture XHR/JSON responses that may contain BIOS rows.
        def _on_response(resp):
            try:
                ct = ""
                try:
                    ct = resp.headers.get("content-type", "")
                except Exception:
                    ct = ""
                if not _should_capture(resp.url, ct):
                    return
                # Avoid huge payloads
                txt = resp.text()
                if not txt:
                    return
                if ("Release Date" in txt) or ("AMI BIOS" in txt) or ("Version" in txt and DATE_RX.search(txt)):
                    captured.append(txt[:400000])
            except Exception:
                return

        page.on("response", _on_response)

        def _dismiss_overlays() -> None:
            # Cookie banners / overlays
            for label in ("Accept all", "Accept All", "I Accept", "AGREE", "Accept", "OK", "Close"):
                try:
                    page.locator(f"button:has-text('{label}')").first.click(timeout=1200)
                    break
                except Exception:
                    pass

            # Location switch overlays (these show up as "switchLocationNotice" on some regions)
            for label in (
                "Continue",
                "Stay",
                "Stay Here",
                "Stay on",
                "I understand",
                "Got it",
                "Confirm",
            ):
                try:
                    page.locator(f"button:has-text('{label}')").first.click(timeout=1200)
                except Exception:
                    pass

        def _scroll_nudge() -> None:
            try:
                page.evaluate(
                    "(() => { window.scrollTo(0, 0); })()"
                )
            except Exception:
                pass
            page.wait_for_timeout(300)
            for _ in range(3):
                try:
                    page.evaluate(
                        "(() => { window.scrollBy(0, Math.max(600, window.innerHeight)); })()"
                    )
                except Exception:
                    pass
                page.wait_for_timeout(400)

            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(600)

        def _go_to_bios_tab() -> None:
            # Force hash and try several click strategies
            try:
                page.evaluate("(() => { location.hash = '#bios'; window.dispatchEvent(new HashChangeEvent('hashchange')); })()")
            except Exception:
                pass

            for sel in (
                "a[href*='#bios']",
                "button:has-text('BIOS')",
                "a:has-text('BIOS')",
                "text=BIOS",
            ):
                try:
                    page.locator(sel).first.click(timeout=1800)
                    break
                except Exception:
                    pass

        def _load_once(target_url: str) -> str:
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1200)
            _dismiss_overlays()

            # Let client scripts do their thing
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

            # Some pages need a nudge to land on support + BIOS
            try:
                page.locator("a[href*='support']").first.click(timeout=1500)
            except Exception:
                pass

            _go_to_bios_tab()
            page.wait_for_timeout(800)
            _scroll_nudge()

            # Best-effort: wait for any BIOS-ish markers to show up
            for marker in ("Release Date", "AMI BIOS", "File Size", "Download"):
                try:
                    page.locator(f"text={marker}").first.wait_for(timeout=15000)
                    break
                except Exception:
                    continue

            html = ""
            visible = ""
            try:
                html = page.content()
            except Exception:
                html = ""
            try:
                visible = page.inner_text("body")
            except Exception:
                visible = ""

            combo = html + "\n\n<!--VISIBLE_TEXT-->\n" + (visible or "")
            if captured:
                combo += "\n\n<!--CAPTURED_RESPONSES-->\n" + "\n\n".join(captured[:6])
            return combo

        url_https = _force_https(url)
        candidates = [
            _ensure_bios_anchor(_with_host(url_https, "us.msi.com")),
            _ensure_bios_anchor(_with_host(url_https, "www.msi.com")),
        ]

        try:
            last = ""
            for cand in candidates:
                try:
                    last = _load_once(cand)
                    # If we already see Version/Release Date in the combined text, we're good.
                    if "Release Date" in last and "Version" in last:
                        ctx.close()
                        browser.close()
                        return last
                except Exception:
                    continue

            ctx.close()
            browser.close()
            return last
        except Exception:
            try:
                last = page.content()
            except Exception:
                last = ""
            ctx.close()
            browser.close()
            return last


# ---------- parsing helpers ----------

def _parse_span_lookahead(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Primary: within each section.spec, find a '...BIOS' title span and scan forward for
    the next Version token and Date.
    """
    out: List[Dict[str, Optional[str]]] = []
    for sec in soup.select("section.spec, .spec"):
        spans = sec.find_all("span")
        if not spans:
            continue
        texts = [s.get_text(strip=True) for s in spans]

        bios_idxs = [i for i, t in enumerate(texts) if "bios" in t.lower()]
        for i in bios_idxs:
            ver = None
            dt = None
            for j in range(i + 1, min(i + 14, len(spans))):
                tj = texts[j]
                if ver is None and ("version" in tj.lower() or VERSION_BASE_RX.search(tj)):
                    ver = _extract_base_version(tj)
                if dt is None and ("date" in tj.lower() or DATE_RX.search(tj)):
                    dt = _norm_date(tj)
                if ver and dt:
                    out.append({"title": texts[i], "version": ver, "date": dt})
                    break
    return out


def _parse_grid_sections(soup: BeautifulSoup) -> List[Dict[str, Optional[str]]]:
    """
    Secondary: strict grid (Title|Version|Release Date|File Size) in spans.
    """
    out: List[Dict[str, Optional[str]]] = []
    for sec in soup.select("section.spec, .spec"):
        spans = sec.find_all("span")
        if not spans:
            continue
        texts = [s.get_text(strip=True) for s in spans]

        # find a header row
        start = -1
        for i in range(0, len(texts) - 3):
            header = [t.lower() for t in texts[i:i + 4]]
            if ("title" in header[0] and
                "version" in header[1] and
                ("date" in header[2] or "release" in header[2])):
                start = i + 4
                break
        if start < 0:
            continue

        data = texts[start:]
        for i in range(0, len(data), 4):
            chunk = data[i:i + 4]
            if len(chunk) < 3:
                continue
            title, ver_raw, date_raw = chunk[0], chunk[1], chunk[2]
            if "bios" not in title.lower():
                continue
            ver = _extract_base_version(ver_raw)
            dt = _norm_date(date_raw)
            if ver and dt:
                out.append({"title": title, "version": ver, "date": dt})
    return out


def _parse_text_fallback(html_text: str) -> List[Dict[str, Optional[str]]]:
    """
    Fallback for MSI pages that don't match the span/grid structure.

    We prioritize explicit pairs:
      Version <X> ... Release Date <YYYY-MM-DD>

    This is exactly the format MSI uses on many support pages, including
    PRO B760M-VC WIFI BULK.
    """
    if not html_text:
        return []

    soup = BeautifulSoup(html_text or "", "html.parser")
    full_txt = soup.get_text(" ", strip=True) or ""
    if not full_txt:
        return []

    rows: List[Dict[str, Optional[str]]] = []
    seen: Dict[str, Optional[str]] = {}

    # (1) Label-pair extraction
    for m in MSI_VERSION_RELEASEDATE_RX.finditer(full_txt):
        ver_raw = m.group(1)
        dt_raw = m.group(2)
        ver = _extract_base_version(ver_raw)
        dt = _norm_date(dt_raw)
        if not ver:
            continue
        prev = seen.get(ver)
        if prev is None or (dt and (prev or "") < dt):
            seen[ver] = dt

    if seen:
        for ver, dt in seen.items():
            rows.append({"title": "BIOS", "version": ver, "date": dt})
        return rows

    # (2) Token scan with a wider context window (handles pages missing the 'Version' label)
    for m in VERSION_BASE_RX.finditer(full_txt):
        ver = m.group(1)
        ws = max(0, m.start() - 650)
        we = min(len(full_txt), m.end() + 650)
        window = full_txt[ws:we].lower()

        # require some BIOS-ish context
        if not ("bios" in window or "release date" in window or "ami" in window):
            continue

        dmatch = DATE_RX.search(window)
        dt = _norm_date(dmatch.group(0)) if dmatch else None
        prev = seen.get(ver)
        if prev is None or (dt and (prev or "") < dt):
            seen[ver] = dt

    for ver, dt in seen.items():
        rows.append({"title": "BIOS", "version": ver, "date": dt})

    return rows


def _parse_bios_rows(html_text: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html_text or "", "html.parser")

    rows = _parse_span_lookahead(soup)
    if rows:
        return rows

    rows = _parse_grid_sections(soup)
    if rows:
        return rows

    return _parse_text_fallback(html_text)


# ---------- public API ----------

def latest_two(model_name: str, override_url: Optional[str] = None) -> Dict:
    """Return the latest two BIOS entries for an MSI board."""
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
    combo_text = _fetch_html(final_url)

    # Always dump a debug snapshot locally for tuning
    try:
        Path("cache/msi-debug").mkdir(parents=True, exist_ok=True)
        slug = _slugify_name(model_name)
        Path(f"cache/msi-debug/{slug}.html").write_text(combo_text, encoding="utf-8")
        # Also dump the extracted plain text for easy inspection
        soup = BeautifulSoup(combo_text or "", "html.parser")
        Path(f"cache/msi-debug/{slug}.txt").write_text(soup.get_text("\n", strip=True), encoding="utf-8")
    except Exception:
        pass

    rows = _parse_bios_rows(combo_text)
    if not rows:
        return {
            "vendor": "MSI",
            "model": model_name,
            "url": final_url,
            "ok": False,
            "versions": [],
            "error": "parse:no-versions",
        }

    # Newest first by date if present; otherwise keep order
    def key(r):
        d = r.get("date")
        return (0, d) if d else (1, "")

    rows_sorted = sorted(rows, key=key, reverse=True)

    versions = [
        {"version": (r.get("version") or ""), "date": r.get("date")}
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


if __name__ == "__main__":
    import sys as _sys
    mdl = " ".join(_sys.argv[1:]) or "PRO B760M-VC WIFI BULK"
    print(latest_two(mdl, override_url="https://us.msi.com/Motherboard/PRO-B760M-VC-WIFI-BULK/support#bios"))
