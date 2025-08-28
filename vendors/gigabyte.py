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
    "Referer": "https://www.gigabyte.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def _guess_support_url(model: str) -> str:
    slug = model.replace(" ", "-")
    return  f"https://www.gigabyte.com/Motherboard/{slug}/support#support-dl-bios",

def _parse_versions_from_html(html:str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for t in soup.find_all(string=re.compile(r"\bF[0-9]{1,3}[a-z]?\b")):
        v = t.strip()
        date=None
        parent=getattr(t, "parent", None)
        if parent:
            s=parent.get_text(" ", strip=True)
            md=re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", s)
            if md: date=md.group(1)
        versions.append({"version": v, "date": date})
    seen=set(); out=[]
    for x in versions:
        if x["version"] in seen: continue
        seen.add(x["version"]); out.append(x)
    return out

def latest_two(model:str, override_url:str=None):
    urls = [override_url] if override_url else list(_candidates(model))
    last_err=None
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code != 200:
                last_err=f"HTTP {r.status_code}"; continue
            vs = _parse_versions_from_html(r.text)
            if vs:
                return {"vendor":"GIGABYTE","model":model,"url":url,"versions":vs[:2],"ok":True}
            else:
                last_err="No versions parsed"
        except Exception as e:
            last_err=str(e)[:200]
    return {"vendor":"GIGABYTE","model":model,"url":urls[0] if urls else "", "versions":[], "ok":False, "error":last_err or "Unknown"}
