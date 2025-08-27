import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
    # Clean and format model name, ensuring uppercase for ROG models
    slug = model.strip().replace(" ", "-").replace("--", "-").upper()
    if model.upper().startswith("ROG"):
        slug = slug.replace("GAMING-", "GAMING-").replace("WIFI", "WIFI").replace("PLUS", "PLUS").rstrip("-")
    return f"https://www.asus.com/supportonly/{slug}/HelpDesk_BIOS/"

def _parse_versions_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    # Broaden search to catch variations in version text
    for t in soup.find_all(string=re.compile(r"(?:Version|BIOS)\s*([0-9A-Za-z._-]+)", re.I)):
        m = re.search(r"(?:Version|BIOS)\s*([0-9A-Za-z._-]+)", t, re.I)
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
    seen = set()
    out = []
    for x in versions:
        if x["version"] in seen:
            continue
        seen.add(x["version"])
        out.append(x)
    # Debug: Print snippet of HTML if no versions found
    if not versions:
        print("No versions found. HTML snippet:", html[:500])
    return out

def latest_two(model: str, override_url: str = None):
    urls_to_try = [override_url] if override_url else []
    if not override_url:
        base_url = _guess_support_url(model)
        urls_to_try.append(base_url)
        if model.upper().startswith("ROG"):
            slug_variants = [
                model.replace(" ", "-").upper().rstrip("-"),
                model.replace(" ", "-").replace("GAMING", "").upper().rstrip("-"),
                model.replace(" ", "-").replace("WIFI", "").upper().rstrip("-"),
                model.replace(" ", "-").replace("GAMING-WIFI", "WIFI").upper().rstrip("-"),
            ]
            urls_to_try.extend([f"https://www.asus.com/supportonly/{slug}/HelpDesk_BIOS/" for slug in slug_variants])

    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    for url in urls_to_try:
        try:
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
    return {"vendor": "ASUS", "model": model, "url": urls_to_try[0], "versions": [], "ok": False, "error": "Couldn't fetch versions"}
