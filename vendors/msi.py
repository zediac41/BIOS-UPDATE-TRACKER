import re, requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent":"Mozilla/5.0"}

def _candidates(model:str):
    slug = model.replace(" ","-")
    slugs = {slug, slug.upper(), slug.title().replace(" ","-")}
    for s in slugs:
        yield f"https://www.msi.com/Motherboard/{s}/support"
        yield f"https://www.msi.com/Motherboard/{s}/support#down-bios"

def _parse_versions_from_html(html:str):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for t in soup.find_all(string=re.compile(r"(?:Version\s*[0-9A-Za-z._-]+|E?\d{3,6}\w{0,3}\.\w+)")):
        s = t.strip()
        m = re.search(r"(E?\d{3,6}\w{0,3}\.\w+|Version\s*[0-9A-Za-z._-]+|v[0-9A-Za-z._-]+)", s)
        if m:
            v = m.group(1).replace("Version","").strip()
            if v and v.lower()!="bios":
                versions.append({"version": v, "date": None})
    seen=set(); out=[]
    for x in versions:
        v=x["version"]
        if v in seen: continue
        seen.add(v); out.append(x)
    return out

def latest_two(model:str, override_url:str=None):
    urls = [override_url] if override_url else list(_candidates(model))
    last_err = None
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"; continue
            vs = _parse_versions_from_html(r.text)
            if vs:
                return {"vendor":"MSI","model":model,"url":url,"versions":vs[:2],"ok":True}
            else:
                last_err = "No versions parsed"
        except Exception as e:
            last_err = str(e)[:200]
    return {"vendor":"MSI","model":model,"url":urls[0] if urls else "", "versions":[], "ok":False, "error":last_err or "Unknown"}
