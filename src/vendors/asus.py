import requests
from bs4 import BeautifulSoup
from ..utils import best_effort_versions_and_dates, clean_text

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
}

def fetch(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text

def scrape_generic(url: str):
    html = fetch(url)
    entries = best_effort_versions_and_dates(html)
    # Return top 2 unique with non-empty versions
    out = []
    seen = set()
    for e in entries:
        v = e.get("version")
        if not v or v in seen:
            continue
        seen.add(v)
        out.append({"version": v, "date": e.get("date")})
        if len(out) == 2:
            break
    return out


def get_last_two_versions(support_url: str):
    # ASUS pages vary; try generic heuristic parser
    return scrape_generic(support_url)
