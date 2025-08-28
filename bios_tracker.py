#!/usr/bin/env python3
import json, yaml, datetime, html, time, sys
from pathlib import Path
from vendors import asus, asusrog, msi, gigabyte, asrock

VENDOR_FUNCS = {
    "asus": asus.latest_two,
    "asusrog": asusrog.latest_two,
    "msi": msi.latest_two,
    "gigabyte": gigabyte.latest_two,
    "asrock": asrock.latest_two,
}

def load_config():
    with open("config.yml","r",encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _cell(label, value):
    value = html.escape(value or "—")
    return f'<div class="kv"><span>{label}</span><span>{value}</span></div>'

def build_card(entry):
    vendor = entry.get("vendor","")
    model = entry.get("model","")
    url = entry.get("url","#")
    ok = entry.get("ok", False)
    vlist = entry.get("versions", [])[:2]
    err = entry.get("error")

    if ok and vlist:
        ver_cur = vlist[0].get("version")
        date_cur = vlist[0].get("date")
        ver_prev = vlist[1].get("version") if len(vlist)>1 else None
        date_prev = vlist[1].get("date") if len(vlist)>1 else None

        cur_str = f"{ver_cur or '—'}" + (f" ({date_cur})" if date_cur else "")
        prev_str = f"{ver_prev or '—'}" + (f" ({date_prev})" if date_prev else "")

        parts = []
        parts.append('<div class="card">')
        parts.append(f'  <h3>{html.escape(model)} <span class="badge">{html.escape(vendor)}</span></h3>')
        parts.append(f'  <div class="meta"><a href="{html.escape(url)}" target="_blank" rel="noreferrer">Vendor page</a></div>')
        parts.append(_cell("Current", cur_str))
        parts.append(_cell("Previous", prev_str))
        parts.append('</div>')
        return "\n".join(parts)
    else:
        parts = []
        parts.append('<div class="card">')
        parts.append(f'  <h3>{html.escape(model)} <span class="badge">{html.escape(vendor)}</span></h3>')
        parts.append(f'  <div class="meta"><a href="{html.escape(url)}" target="_blank" rel="noreferrer">Vendor page</a></div>')
        parts.append('  <div class="error">Couldn\'t fetch versions.</div>')
        if err:
            parts.append(f'  <pre class="meta">{html.escape(str(err))}</pre>')
        parts.append('</div>')
        return "\n".join(parts)

def main():
    cfg = load_config()
    vendors = (cfg.get("vendors") or {})
    results = []

    def normalize(item):
        if isinstance(item, dict):
            return item.get("name") or item.get("model") or "", item.get("url")
        return str(item), None

    for vkey, models in vendors.items():
        func = VENDOR_FUNCS.get(vkey.lower())
        if not func:
            print(f"Unknown vendor key: {vkey}", file=sys.stderr); continue
        for item in (models or []):
            model, override_url = normalize(item)
            print(f"[{vkey}] {model} ...", file=sys.stderr)
            try:
                res = func(model, override_url=override_url)
            except TypeError:
                res = func(model)
            except Exception as e:
                res = {"vendor": vkey.upper(), "model": model, "url": override_url or "", "versions":[], "ok":False, "error":str(e)}
            results.append(res)
            time.sleep(0.5)

    cards = "\n".join(build_card(r) for r in results)
    # write docs
    docs = Path("docs"); docs.mkdir(parents=True, exist_ok=True)
    idx = docs / "index.html"
    if not idx.exists():
        idx.write_text("<!doctype html><meta charset='utf-8'><title>BIOS Tracker</title><link rel='stylesheet' href='assets/site.css'><div class='grid'></div>", encoding="utf-8")
    html_src = idx.read_text(encoding="utf-8")
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html_src = html_src.replace("BUILD_TIME", now)
    start = html_src.find('<div class="grid">'); end = html_src.find("</div>", start)
    if start != -1 and end != -1:
        new_html = html_src[:start] + '<div class="grid">\n' + cards + "\n</div>" + html_src[end+6:]
    else:
        new_html = html_src + "\n<div class='grid'>\n" + cards + "\n</div>\n"
    idx.write_text(new_html, encoding="utf-8")
    (docs / "data.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Done. Wrote docs/index.html and docs/data.json")

if __name__ == "__main__":
    main()
