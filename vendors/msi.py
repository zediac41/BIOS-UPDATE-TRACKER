import re, requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent":"Mozilla/5.0"}

def _guess_support_url(model:str)->str:
    slug = model.replace(" ","-")
    return f"https://www.msi.com/Motherboard/{slug}/support"

def _parse_versions_from_html(html:str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    # Capture common MSI version formats
    for t in soup.find_all(string=re.compile(r"(?i)(BIOS|\bE?\d{3,6}\w{0,3}\.\w+|v[0-9A-Za-z._-]+)")):
        s = t.strip()
        m = re.search(r"(E?\d{3,6}\w{0,3}\.\w+|v[0-9A-Za-z._-]+|\b[0-9A-Za-z._-]{4,}\b)", s)
        if m:
            versions.append({"version": m.group(1)})
    seen=set(); out=[]
    for x in versions:
        v=x["version"]
        if v.lower()=="bios": continue
        if v in seen: continue
        seen.add(v); out.append({"version":v,"date":None})
    return out

def latest_two(model:str):
    url = _guess_support_url(model)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        vs = _parse_versions_from_html(r.text)
        return {"vendor":"MSI","model":model,"url":url,"versions":vs[:2],"ok":True}
    except Exception as e:
        return {"vendor":"MSI","model":model,"url":url,"versions":[],"ok":False,"error":str(e)[:200]}
