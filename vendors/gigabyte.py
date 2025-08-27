import re
from bs4 import BeautifulSoup
from vendors._utils.fetch import fetch_html
def _candidates(model):
    slug=model.replace(' ','-')
    yield f"https://www.gigabyte.com/Motherboard/{slug}/support#support-dl-bios"
    yield f"https://www.gigabyte.com/Motherboard/{slug.upper()}/support#support-dl-bios"
    yield f"https://www.gigabyte.com/Motherboard/{slug.title().replace(' ','-')}/support#support-dl-bios"
    yield f"https://www.gigabyte.com/Motherboard/{slug}-rev-1x/support#support-dl-bios"
def _parse_versions_from_html(html):
    soup=BeautifulSoup(html,'html.parser'); versions=[]
    for t in soup.find_all(string=re.compile(r"\bF[0-9]{1,3}[a-z]?\b")):
        v=t.strip(); date=None; par=getattr(t,'parent',None)
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
        html,err=fetch_html(url,'GIGABYTE',model)
        if html:
            vs=_parse_versions_from_html(html)
            if vs: return {'vendor':'GIGABYTE','model':model,'url':url,'versions':vs[:2],'ok':True}
            last_err='No versions parsed'
        else: last_err=err
    return {'vendor':'GIGABYTE','model':model,'url':urls[0] if urls else '','versions':[],'ok':False,'error':last_err or 'Unknown'}
