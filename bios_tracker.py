#!/usr/bin/env python3
import json, yaml, datetime, html, time, sys
from pathlib import Path
from vendors import asus, msi, gigabyte, asrock
VENDOR_FUNCS={'asus':asus.latest_two,'msi':msi.latest_two,'gigabyte':gigabyte.latest_two,'asrock':asrock.latest_two}
def load_config():
    with open('config.yml','r',encoding='utf-8') as f: return yaml.safe_load(f) or {}
def _cell(label,value):
    value=html.escape(value or '—'); return f"<div class='kv'><span>{label}</span><span>{value}</span></div>"
def build_card(entry):
    vendor=entry.get('vendor',''); model=entry.get('model',''); url=entry.get('url','#'); ok=entry.get('ok',False)
    vlist=entry.get('versions',[])[:2]; err=entry.get('error')
    if ok and vlist:
        ver_cur=vlist[0].get('version'); date_cur=vlist[0].get('date')
        ver_prev=vlist[1].get('version') if len(vlist)>1 else None; date_prev=vlist[1].get('date') if len(vlist)>1 else None
        cur=f"{ver_cur or '—'}"+(f" ({date_cur})" if date_cur else ''); prev=f"{ver_prev or '—'}"+(f" ({date_prev})" if date_prev else '')
        return "\n".join([
            "<div class='card'>",
            f"  <h3>{html.escape(model)} <span class='badge'>{html.escape(vendor)}</span></h3>",
            f"  <div class='meta'><a href='{html.escape(url)}' target='_blank' rel='noreferrer'>Vendor page</a></div>",
            _cell('Current',cur),
            _cell('Previous',prev),
            "</div>"
        ])
    else:
        parts=[
            "<div class='card'>",
            f"  <h3>{html.escape(model)} <span class='badge'>{html.escape(vendor)}</span></h3>",
            f"  <div class='meta'><a href='{html.escape(url)}' target='_blank' rel='noreferrer'>Vendor page</a></div>",
            "  <div class='error'>Couldn't fetch versions.</div>"
        ]
        if err: parts.append(f"  <pre class='meta'>{html.escape(str(err))}</pre>")
        parts.append("</div>"); return "\n".join(parts)
def main():
    cfg=load_config(); vendors=(cfg.get('vendors') or {}); results=[]
    def norm(item): 
        if isinstance(item,dict): return item.get('name') or item.get('model') or '', item.get('url')
        return str(item), None
    for vkey, models in vendors.items():
        func=VENDOR_FUNCS.get(vkey.lower()); 
        if not func: print(f'Unknown vendor key: {vkey}', file=sys.stderr); continue
        for item in (models or []):
            model, override=norm(item); print(f'[{vkey}] {model} ...', file=sys.stderr)
            try:
                res=func(model, override_url=override)
            except TypeError:
                res=func(model)
            except Exception as e:
                res={'vendor':vkey.upper(),'model':model,'url':override or '','versions':[],'ok':False,'error':str(e)}
            results.append(res); time.sleep(0.6)
    cards="\n".join(build_card(r) for r in results)
    docs=Path('docs'); docs.mkdir(parents=True, exist_ok=True)
    idx=docs/'index.html'
    if not idx.exists(): idx.write_text("<!doctype html><div class='grid'></div>", encoding='utf-8')
    html_src=idx.read_text(encoding='utf-8'); now=datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'); html_src=html_src.replace('BUILD_TIME', now)
    start=html_src.find("<div class='grid'>"); end=html_src.find("</div>", start)
    new_html=html_src[:start]+"<div class='grid'>\n"+cards+"\n</div>"+html_src[end+6:] if (start!=-1 and end!=-1) else (html_src+"\n<div class='grid'>\n"+cards+"\n</div>\n")
    idx.write_text(new_html, encoding='utf-8')
    (docs/'data.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print('Done. Wrote docs/index.html and docs/data.json')
if __name__=='__main__': main()
