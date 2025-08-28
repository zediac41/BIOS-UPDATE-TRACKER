import re
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.asus.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def _generate_support_urls(model: str) -> list:
    """Generate possible support URLs for ASUS ROG motherboards."""
    # Normalize model name for URL construction
    slug = re.sub(r"\s+", "-", model.strip().upper()).rstrip("-")
    slug_variants = [
        slug,
        slug.replace("-GAMING", "").rstrip("-"),
        slug.replace("-WIFI", "").rstrip("-"),
        slug.replace("-PLUS", "").rstrip("-"),
        slug.replace("-GAMING-WIFI", "-WIFI").rstrip("-"),
    ]
    base_urls = [
        "https://www.asus.com/supportonly/{}/HelpDesk_BIOS/",
        "https://www.asus.com/us/supportonly/{}/HelpDesk_BIOS/",
        "https://rog.asus.com/motherboards/rog-strix/{}/helpdesk_bios/",
    ]
    urls = []
    for variant in set(slug_variants):  # Remove duplicates
        for base in base_urls:
            if "rog.asus.com" in base:
                urls.append(base.format(variant.lower()))
            else:
                urls.append(base.format(variant))
    return list(set(urls))  # Ensure unique URLs

def _parse_bios_versions(html: str) -> list:
    """Parse BIOS versions and dates from ASUS support page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    versions = []

    # Target ASUS support page table structures
    for row in soup.select("div.download-item, tr.download-file"):
        version_elem = row.select_one("span.version, td.version, div:contains('Version')")
        date_elem = row.select_one("span.date, td.date, div:contains('/')")

        version = None
        date = None

        if version_elem:
            text = version_elem.get_text(strip=True)
            version_match = re.search(r"(?:Version|BIOS)\s*([\d\.A-Za-z-]+)", text, re.I)
            if version_match:
                version = version_match.group(1).strip()

        if date_elem:
            text = date_elem.get_text(strip=True)
            date_match = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", text)
            if date_match:
                date = date_match.group(1)
                # Normalize date format to YYYY-MM-DD
                try:
                    if "/" in date:
                        date = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
                    else:
                        date = date.replace("/", "-")
                except ValueError:
                    date = None

        if version:
            versions.append({"version": version, "date": date})

    # Fallback: Look for version-like patterns in the page
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
    
    # Sort by version number (assuming higher numbers are newer)
    unique_versions.sort(key=lambda x: x["version"], reverse=True)
    
    return unique_versions

def latest_two(model: str, override_url: str = None) -> dict:
    """Fetch the latest two BIOS versions for an ASUS ROG motherboard."""
    urls = [override_url] if override_url else _generate_support_urls(model)
    
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[403, 429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    for url in urls:
        try:
            print(f"Attempting to fetch: {url}")
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
        except requests.RequestException as e:
            print(f"Error fetching {url}: {str(e)[:200]}")
            continue
        time.sleep(1.5)  # Avoid rate limiting

    return {
        "vendor": "ASUS",
        "model": model,
        "url": urls[0] if urls else None,
        "versions": [],
        "ok": False,
        "error": "Unable to fetch BIOS versions"
    }
