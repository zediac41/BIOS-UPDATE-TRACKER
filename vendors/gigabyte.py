import re, requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent":"Mozilla/5.0"}

def _candidates(model:str):
    slug = model.replace(" ","-")
    candidates = [
        f"https://www.gigabyte.com/Motherboard/{slug}/support#support-dl-bios",
        f"https://www.gigabyte.com/Motherboard/{slug.upper()}/support#support-dl-bios",
        f"https://www.gigabyte.com/Motherboard/{slug.title().replace(' ','-')}/support#support-dl-bios",
        f"https://www.gigabyte.com/Motherboard/{slug}-rev-1x/support#support-dl-bios",
    ]
    seen=set()
    for u in candidates:
        if u not in seen:
            seen.add(u); yield u

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
