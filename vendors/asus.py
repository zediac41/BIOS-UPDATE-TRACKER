import re, requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent":"Mozilla/5.0"}

def _guess_support_url(model:str)->str:
    slug = model.replace(" ","-")
    return f"https://www.asus.com/supportonly/{slug}/HelpDesk_BIOS/"

def _parse_versions_from_html(html:str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for t in soup.find_all(string=re.compile(r"Version\s*([0-9A-Za-z._-]+)")):
        m = re.search(r"Version\s*([0-9A-Za-z._-]+)", t)
        if m:
            v = m.group(1).strip()
            # find nearby date if available
            date = None
            parent = getattr(t, "parent", None)
            if parent:
                s = parent.get_text(" ", strip=True)
                md = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})", s)
                if md: date = md.group(1)
            versions.append({"version": v, "date": date})
    seen=set(); out=[]
    for x in versions:
        if x["version"] in seen: continue
        seen.add(x["version"]); out.append(x)
    return out

def latest_two(model:str, override_url:str=None):
    url = override_url or _guess_support_url(model)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        vs = _parse_versions_from_html(r.text)
        return {"vendor":"ASUS","model":model,"url":url,"versions":vs[:2],"ok":True}
    except Exception as e:
        return {"vendor":"ASUS","model":model,"url":url,"versions":[],"ok":False,"error":str(e)[:200]}
