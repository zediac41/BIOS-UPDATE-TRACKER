import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from datetime import datetime
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.asus.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def _search_product_page(model: str) -> str:
    """Search for the ASUS product page using the global search API."""
    search_url = "https://www.asus.com/us/support/api/search"
    query = model.strip().replace(" ", "+")
    params = {
        "q": query,
        "category": "motherboards",
        "page": 1,
        "size": 10
    }
    
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    
    try:
        response = session.get(search_url, headers=HEADERS, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        # Look for a matching motherboard result
        for result in data.get("hits", []):
            if "motherboards" in result.get("category", "").lower():
                product_url = result.get("url")
                if product_url:
                    # Ensure the URL points to the BIOS section
                    if not product_url.endswith("HelpDesk_BIOS/"):
                        product_url = product_url.rstrip("/") + "/HelpDesk_BIOS/"
                    return product_url
    except Exception as e:
        print(f"Search failed: {str(e)[:200]}")
    
    # Fallback to constructed URL if search fails
    slug = re.sub(r"\s+", "-", model.strip().upper()).rstrip("-")
    return f"https://www.asus.com/us/supportonly/{slug}/HelpDesk_BIOS/"

def _parse_bios_versions(html: str) -> list:
    """Parse BIOS versions and dates from the product page."""
    soup = BeautifulSoup(html, "html.parser")
    versions = []

    # Target BIOS download sections
    bios_sections = soup.select("div.download-item, tr.download-file, div[id*='BIOS']")
    
    for section in bios_sections:
        version = None
        date = None
        
        # Extract version
        version_elem = section.select_one("span.version, td.version, div:contains('Version'), span:contains('BIOS')")
        if version_elem:
            text = version_elem.get_text(strip=True)
            version_match = re.search(r"(?:Version|BIOS)\s*([\d\.A-Za-z-]+)", text, re.I)
            if version_match:
                version = version_match.group(1).strip()
        
        # Extract date
        date_elem = section.select_one("span.date, td.date, div:contains('/')")
        if date_elem:
            text = date_elem.get_text(strip=True)
            date_match = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", text)
            if date_match:
                date = date_match.group(1)
                try:
                    if "/" in date:
                        date = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
                    else:
                        date = date.replace("/", "-")
                except ValueError:
                    date = None
        
        if version:
            versions.append({"version": version, "date": date})
    
    # Fallback: Broad search for version-like patterns
    if not versions:
        for element in soup.find_all(string=re.compile(r"\d+\.\d+")):
            text = element.get_text(strip=True)
            version_match = re.search(r"(\d+\.\d+)", text)
            if version_match:
                version = version_match.group(1).strip()
                date_match = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", text)
                date = None
                if date_match:
                    date = date_match.group(1)
                    try:
                        if "/" in date:
                            date = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
                        else:
                            date = date.replace("/", "-")
                    except ValueError:
                        date = None
                versions.append({"version": version, "date": date})

    # Remove duplicates and sort by version (descending)
    seen = set()
    unique_versions = []
    for v in versions:
        if v["version"] not in seen:
            seen.add(v["version"])
            unique_versions.append(v)
    
    unique_versions.sort(key=lambda x: x["version"], reverse=True)
    return unique_versions

def latest_two(model: str, override_url: str = None) -> dict:
    """Fetch the latest two BIOS versions for an ASUS ROG motherboard."""
    url = override_url or _search_product_page(model)
    
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    try:
        print(f"Fetching BIOS from: {url}")
        response = session.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        versions = _parse_bios_versions(response.text)
        if versions:
            return {
                "vendor": "ASUS",
                "model": model,
                "url": url,
                "versions": versions[:2],
                "ok": True
            }
        else:
            print(f"No BIOS versions found at: {url}")
            return {
                "vendor": "ASUS",
                "model": model,
                "url": url,
                "versions": [],
                "ok": False,
                "error": "No BIOS versions found"
            }
    except requests.RequestException as e:
        print(f"Error fetching {url}: {str(e)[:200]}")
        return {
            "vendor": "ASUS",
            "model": model,
            "url": url,
            "versions": [],
            "ok": False,
            "error": f"Failed to fetch page: {str(e)[:200]}"
        }
    finally:
        time.sleep(1.5)  # Avoid rate limiting
