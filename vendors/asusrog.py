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

def _guess_support_url(model: str) -> list:
    """Generate possible support URLs for ROG models."""
    slug = model.strip().replace(" ", "-").replace("--", "-").upper().rstrip("-")
    slug_variants = [
        slug,
        slug.replace("GAMING", "").rstrip("-"),
        slug.replace("WIFI", "").rstrip("-"),
        slug.replace("GAMING-WIFI", "WIFI").rstrip("-"),
        slug.replace("PLUS", "").rstrip("-"),
    ]
    urls = []
    for s in slug_variants:
        urls.extend([
            f"https://www.asus.com/supportonly/{s}/HelpDesk_BIOS/",
            f"https://www.asus.com/us/supportonly/{s}/HelpDesk_BIOS/",
            f"https://rog.asus.com/motherboards/rog-strix/{s.lower()}/helpdesk_bios/",
        ])
    return urls

def _parse_versions_from_html(html: str):
    """Parse BIOS versions from HTML, handling ROG-specific structures."""
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    
    # Try regex for Version/BIOS/Update text
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
    
    # Alternative: Look for numeric versions in common elements
    for element in soup.select("div, td, span, li", string=re.compile(r"\d+\.\d+")):
        text = element.get_text(" ", strip=True)
        m = re.search(r"(\d+\.\d+)", text)
        if m:
            v = m.group(1).strip()
            date = None
            md = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", text)
            if md:
                date = md.group(1)
            versions.append({"version": v, "date": date})
    
    # Remove duplicates
    seen = set()
    out = []
    for x in versions:
        if x["version"] in seen:
            continue
        seen.add(x["version"])
        out.append(x)
    
    # Debug: Print HTML snippet if no versions found
    if not versions:
        print("No versions found. HTML snippet:", html[:1500])
    return out

def latest_two(model: str, override_url: str = None):
    """Fetch the latest two BIOS versions for an ROG motherboard."""
    urls_to_try = [override_url] if override_url else _guess_support_url(model)
    
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
