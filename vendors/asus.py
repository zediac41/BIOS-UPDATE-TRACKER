import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.asus.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def _guess_support_url(model: str) -> str:
    # Clean and format model name
    slug = model.strip().replace(" ", "-").replace("--", "-").upper()
    if model.upper().startswith("ROG"):
        slug = slug.replace("GAMING-", "GAMING-").replace("WIFI", "WIFI").replace("PLUS", "PLUS").rstrip("-")
    # Try both global and US domains
    return [
        f"https://www.asus.com/supportonly/{slug}/HelpDesk_BIOS/",
        f"https://www.asus.com/us/supportonly/{slug}/HelpDesk_BIOS/",
    ]

def _parse_versions_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    # Broaden regex to catch various BIOS version formats
    for t in soup.find_all(string=re.compile(r"(?:Version|BIOS|Update)\s*([0-9A-Za-z._-]+)", re.I)):
        m = re.search(r"(?:Version|BIOS|Update)\s*([0-9A-Za-z._-]+)", t, re.I)
        if m:
            v = m.group(1).strip()
            date = None
            parent = getattr(t, "parent", None)
            if parent:
                s = parent.get_text(" ", strip=True)
                md = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", s)
                if md:
                    date = md.group(1)
            versions.append({"version": v, "date": date})
    # Alternative: Check for BIOS versions in specific HTML elements
    for element in soup.select("div, td, span", string=re.compile(r"\d+\.\d+")):
        text = element.get_text(" ", strip=True)
        m = re.search(r"(\d+\.\d+)", text)
        if m:
            v = m.group(1).strip()
            date = None
            md = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", text)
            if md:
                date = md.group(1)
            versions.append({"version": v, "date": date})
    seen = set()
    out = []
    for x in versions:
        if x["version"] in seen:
            continue
        seen.add(x["version"])
        out.append(x)
    if not versions:
        print("No versions found. HTML snippet:", html[:1000])  # Extended snippet for debugging
    return out

def latest_two(model: str, override_url: str = None):
    urls_to_try = [override_url] if override_url else []
    if not override_url:
        base_urls = _guess_support_url(model)
        urls_to_try.extend(base_urls)
        if model.upper().startswith("ROG"):
            slug_variants = [
                model.replace(" ", "-").upper().rstrip("-"),
                model.replace(" ", "-").replace("GAMING", "").upper().rstrip("-"),
                model.replace(" ", "-").replace("WIFI", "").upper().rstrip("-"),
                model.replace(" ", "-").replace("GAMING-WIFI", "WIFI").upper().rstrip("-"),
            ]
            for slug in slug_variants:
                urls_to_try.extend([
                    f"https://www.asus.com/supportonly/{slug}/HelpDesk_BIOS/",
                    f"https://www.asus.com/us/supportonly/{slug}/HelpDesk_BIOS/",
                ])

    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    for url in urls_to_try:
        try:
            print(f"Trying URL: {url}")
            r = session.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            vs = _parse_versions_from_html(r.text)
            if vs:
                return {"vendor": "ASUS", "model": model, "url": url, "versions": vs[:2], "ok": True}
            else:
                print(f"No versions found for URL: {url}")
        except Exception as e:
            print(f"Failed URL: {url}, Error: {str(e)[:200]}")
            continue
        time.sleep(1)  # Avoid rate limiting
    return {"vendor": "ASUS", "model": model, "url": urls_to_try[0], "versions": [], "ok": False, "error": "Couldn't fetch versions"}
