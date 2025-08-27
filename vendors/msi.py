import re
from bs4 import BeautifulSoup
from vendors._utils.fetch import fetch_html
def _candidates(model):
    slug=model.replace(' ','-'); sl={slug, slug.upper(), slug.title().replace(' ','-')}
    for s in sl:
        yield f"https://www.msi.com/Motherboard/{s}/support"
        yield f"https://www.msi.com/Motherboard/{s}/support#down-bios"
def _parse_versions_from_html(html):
    soup=BeautifulSoup(html,'html.parser'); versions=[]
    for t in soup.find_all(string=re.compile(r"(?:Version\s*[0-9A-Za-z._-]+|E?\d{3,6}\w{0,3}\.\w+)")):
        s=t.strip(); m=re.search(r"(E?\d{3,6}\w{0,3}\.\w+|Version\s*[0-9A-Za-z._-]+|v[0-9A-Za-z._-]+)",s)
        if m:
            v=m.group(1).replace('Version','').strip()
            if v and v.lower()!='bios': versions.append({'version':v,'date':None})
    out=[]; seen=set()
    for x in versions:
        if x['version'] in seen: continue
        seen.add(x['version']); out.append(x)
    return out
def latest_two(model, override_url=None):
    urls=[override_url] if override_url else list(_candidates(model)); last_err=None
    for url in urls:
        html,err=fetch_html(url,'MSI',model)
        if html:
            vs=_parse_versions_from_html(html)
            if vs: return {'vendor':'MSI','model':model,'url':url,'versions':vs[:2],'ok':True}
            last_err='No versions parsed'
        else: last_err=err
    return {'vendor':'MSI','model':model,'url':urls[0] if urls else '','versions':[],'ok':False,'error':last_err or 'Unknown'}
