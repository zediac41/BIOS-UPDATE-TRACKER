import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Comprehensive headers to mimic a browser
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
        # Handle common ROG suffixes and variations
        slug = slug.replace("GAMING-", "GAMING-").replace("WIFI", "WIFI").replace("PLUS", "PLUS")
        # Remove trailing hyphens or redundant terms if needed
        slug = slug.rstrip("-")
    return f"https://www.asus.com/supportonly/{slug}/HelpDesk_BIOS/"

def _parse_versions_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for t in soup.find_all(string=re.compile(r"Version\s*([0-9A-Za-z._-]+)")):
        m = re.search(r"Version\s*([0-9A-Za-z._-]+)", t)
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
    return out

def latest_two(model: str, override_url: str = None):
    url = override_url or _guess_support_url(model)
    
    # Set up session with retries
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    
    try:
        r = session.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        vs = _parse_versions_from_html(r.text)
        return {"vendor": "ASUS", "model": model, "url": url, "versions": vs[:2], "ok": True}
    except Exception as e:
        return {"vendor": "ASUS", "model": model, "url": url, "versions": [], "ok": False, "error": str(e)[:200]}
