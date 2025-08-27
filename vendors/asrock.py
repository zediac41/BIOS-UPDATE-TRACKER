import re
from bs4 import BeautifulSoup
from vendors._utils.fetch import fetch_html
def _candidates(model):
    from urllib.parse import quote
    slug=quote(model,safe='')
    yield f"https://www.asrock.com/MB/AllSeries/{slug}/index.asp#BIOS"
    yield f"https://www.asrock.com/mb/AMD/{slug}/index.asp#BIOS"
    yield f"https://www.asrock.com/mb/Intel/{slug}/index.asp#BIOS"
def _parse_versions_from_html(html):
    soup=BeautifulSoup(html,'html.parser'); versions=[]
    for t in soup.find_all(string=re.compile(r"(?i)BIOS\s*Version\s*([0-9A-Za-z._-]+)")):
        m=re.search(r"(?i)BIOS\s*Version\s*([0-9A-Za-z._-]+)",t)
        if m:
            v=m.group(1).strip(); date=None; par=getattr(t,'parent',None)
            if par:
                s=par.get_text(' ',strip=True); md=re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})",s)
                if md: date=md.group(1)
            versions.append({'version':v,'date':date})
    out=[]; seen=set()
    for x in versions:
        if x['version'] in seen: continue
        seen.add(x['version']); out.append(x)
    return out
def latest_two(model, override_url=None):
    urls=[override_url] if override_url else list(_candidates(model)); last_err=None
    for url in urls:
        html,err=fetch_html(url,'ASRock',model)
        if html:
            vs=_parse_versions_from_html(html)
            if vs: return {'vendor':'ASRock','model':model,'url':url,'versions':vs[:2],'ok':True}
            last_err='No versions parsed'
        else: last_err=err
    return {'vendor':'ASRock','model':model,'url':urls[0] if urls else '','versions':[],'ok':False,'error':last_err or 'Unknown'}
