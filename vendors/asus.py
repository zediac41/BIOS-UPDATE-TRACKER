import re
from bs4 import BeautifulSoup
from vendors._utils.fetch import fetch_html
def _guess_support_url(model): return f"https://www.asus.com/supportonly/{model.replace(' ','-')}/HelpDesk_BIOS/"
def _parse_versions_from_html(html):
    soup=BeautifulSoup(html,'html.parser'); versions=[]
    for t in soup.find_all(string=re.compile(r"Version\s*([0-9A-Za-z._-]+)")):
        m=re.search(r"Version\s*([0-9A-Za-z._-]+)",t)
        if m:
            v=m.group(1).strip(); date=None; par=getattr(t,'parent',None)
            if par:
                s=par.get_text(' ',strip=True)
                md=re.search(r"(\d{4}[/-]\d{2}[/-]\d{2}|\d{2}/\d{2}/\d{4})",s)
                if md: date=md.group(1)
            versions.append({'version':v,'date':date})
    out=[]; seen=set()
    for x in versions:
        if x['version'] in seen: continue
        seen.add(x['version']); out.append(x)
    return out
def latest_two(model, override_url=None):
    url=override_url or _guess_support_url(model); html,err=fetch_html(url,'ASUS',model)
    if html:
        vs=_parse_versions_from_html(html)
        if vs: return {'vendor':'ASUS','model':model,'url':url,'versions':vs[:2],'ok':True}
        else: return {'vendor':'ASUS','model':model,'url':url,'versions':[],'ok':False,'error':'No versions parsed'}
    return {'vendor':'ASUS','model':model,'url':url,'versions':[],'ok':False,'error':err or 'Unknown'}
