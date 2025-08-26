import re, requests, urllib.parse
from bs4 import BeautifulSoup

HEADERS = {"User-Agent":"Mozilla/5.0"}

def _candidates(model:str):
    slug_pct = urllib.parse.quote(model, safe="")
    yield f"https://www.asrock.com/MB/AllSeries/{slug_pct}/index.asp#BIOS"
    yield f"https://www.asrock.com/mb/AMD/{slug_pct}/index.asp#BIOS"
    yield f"https://www.asrock.com/mb/Intel/{slug_pct}/index.asp#BIOS"

def _parse_versions_from_html(html:str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for t in soup.find_all(string=re.compile(r"(?i)BIOS\s*Version\s*([0-9A-Za-z._-]+)")):
        m = re.search(r"(?i)BIOS\s*Version\s*([0-9A-Za-z._-]+)", t)
        if m:
            v = m.group(1).strip()
            date=None
            parent=getattr(t, "parent", None)
            if parent:
                s=parent.get_text(" ", strip=True)
                md=re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", s)
                if md: date=md.group(1)
            versions.append({"version":v,"date":date})
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
                return {"vendor":"ASRock","model":model,"url":url,"versions":vs[:2],"ok":True}
            else:
                last_err="No versions parsed"
        except Exception as e:
            last_err=str(e)[:200]
    return {"vendor":"ASRock","model":model,"url":urls[0] if urls else "", "versions":[], "ok":False, "error":last_err or "Unknown"}
