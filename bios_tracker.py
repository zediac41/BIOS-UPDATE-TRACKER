#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import yaml
import datetime
import html
import time
import sys
import re
import csv
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_FORM_EMBED = "https://docs.google.com/forms/d/e/1FAIpQLSeeu3yf7GYgZbPWPLX_iDzg_ulEfe7FdgiW66Co3QHUKaG7Cw/viewform?embedded=true"
DEFAULT_SHEET_ID   = "1O6A9AI0wMu5vWrtKgvwFAxJFEGu6aznUal2khv_oukI"
DEFAULT_GID        = "1502059609"

# -------------------------------------------------------------------
# Vendor scrapers (your existing modules)
# Each module must expose: latest_two(model_name, override_url=None) -> dict
# -------------------------------------------------------------------
from vendors import asus, msi, gigabyte, asrock

VENDOR_FUNCS = {
    "asus": asus.latest_two,
    "msi": msi.latest_two,
    "gigabyte": gigabyte.latest_two,
    "asrock": asrock.latest_two,
}

# -------------------------------------------------------------------
# Vendor scrapers (your existing modules)
# -------------------------------------------------------------------
from vendors.software import fetch as fetch_software

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
def load_config():
    with open("config.yml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# -------------------------------------------------------------------
# Helpers: Beta label, date parsing, highlight (fresh within 5 days)
# -------------------------------------------------------------------
_BETA_PARENS = re.compile(r"\(\s*beta\s+version\s*\)", re.I)
_BETA_BARE   = re.compile(r"\b(beta(?:\s+version)?)\b", re.I)

def normalize_beta(version: str | None) -> str | None:
    """Normalize any vendor's 'beta version' to '... (Beta)'."""
    if not version:
        return version
    v = _BETA_PARENS.sub("(Beta)", version)
    if "(Beta)" not in v and re.search(_BETA_BARE, v):
        v = _BETA_BARE.sub("", v).strip()
        v = re.sub(r"\s{2,}", " ", v).strip()
        v = f"{v} (Beta)"
    return v

def _parse_date(date_str: str | None) -> datetime.date | None:
    """Parse YYYY-MM-DD or YYYY/MM/DD or YYYY.MM.DD to a date()."""
    if not date_str:
        return None
    s = str(date_str).strip().replace("/", "-").replace(".", "-")
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return datetime.date(y, m, d)
    except Exception:
        return None

def _is_fresh_release(date_str: str | None, today: datetime.date | None = None) -> bool:
    """Fresh means released within the last 5 days."""
    d = _parse_date(date_str)
    if not d:
        return False
    if today is None:
        today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    delta = (today - d).days
    return 0 <= delta <= 5

# -------------------------------------------------------------------
# Card rows & rendering
# -------------------------------------------------------------------
def _row(label: str, version: str | None, date: str | None):
    """One key/value row: label, version, date right-aligned."""
    v_txt = normalize_beta(version)
    v_html = html.escape(v_txt or "—")
    d_html = html.escape(date) if date else ""
    return (
        '<div class="kv">'
        f'  <span class="k">{html.escape(label)}</span>'
        f'  <span class="v">{v_html}</span>'
        f'  <span class="date">{d_html}</span>'
        '</div>'
    )

def build_card(entry, issue_names: set[str] | None = None, today: datetime.date | None = None):
    vendor = entry.get("vendor", "")
    model = entry.get("model", "")
    url = entry.get("url", "#")
    ok = entry.get("ok", False)
    vlist = entry.get("versions", [])[:2]
    err = entry.get("error")

    # Highlight classes
    current_date_str = vlist[0].get("date") if (ok and vlist) else None
    is_issue = bool(issue_names and model in issue_names)
    is_fresh = _is_fresh_release(current_date_str, today=today)

    classes = ["card"]
    if is_issue:
        classes.append("card--issue")  # manual orange wins
    elif is_fresh:
        classes.append("card--fresh")

    parts = []
    parts.append(f'<div class="{" ".join(classes)}" data-vendor="{html.escape(vendor)}">')
    parts.append(f'  <h3>{html.escape(model)} <span class="badge">{html.escape(vendor)}</span></h3>')
    if url:
        parts.append(f'  <div class="meta"><a href="{html.escape(url)}" target="_blank" rel="noreferrer">Vendor page</a></div>')

    if ok and vlist:
        cur_v = vlist[0].get("version") if len(vlist) >= 1 else None
        cur_d = vlist[0].get("date") if len(vlist) >= 1 else None
        parts.append(_row("Current", cur_v, cur_d))
        if len(vlist) >= 2:
            prev_v = vlist[1].get("version")
            prev_d = vlist[1].get("date")
            parts.append(_row("Previous", prev_v, prev_d))
    else:
        parts.append('  <div class="error">Couldn’t fetch versions.</div>')
        if err:
            parts.append(f'  <pre class="meta">{html.escape(str(err))}</pre>')

    parts.append('</div>')
    return "\n".join(parts)
    
# make sure: from vendors.software import fetch as fetch_software ; import html
def _build_software_cards(cfg: dict) -> str:
    items = cfg.get("software") or []
    if not items:
        return "<p>No software configured.</p>"

    rows = []
    for it in items:
        sid   = (it.get("id") or "").strip()
        name  = it.get("name") or sid or "Software"
        vendor = it.get("vendor") or ""
        url   = it.get("url") or "#"

        res = fetch_software(sid, name, url)
        ok, ver, err = res.get("ok"), res.get("version"), res.get("error")

        rows.append(
            '<div class="card" data-vendor="software">'
            f'  <h3 class="card-title">{html.escape(name)}'
            + (f' <span class="badge">{html.escape(vendor.upper())}</span>' if vendor else ' <span class="badge">SOFTWARE</span>')
            + '</h3>'
            f'  <div class="kv"><span class="k">Version</span><span class="v">{html.escape(ver or "—")}</span></div>'
            f'  <div class="meta"><a href="{html.escape(url)}" target="_blank" rel="noreferrer">Official page</a></div>'
            + (f'  <div class="error">{html.escape(err)}</div>' if (not ok and err) else "")
            + '</div>'
        )
    return "\n".join(rows)



def _sort_results_newest_first(results: list[dict]) -> list[dict]:
    """Sort tiles by the 'Current' version release date (newest first)."""
    def key(res):
        versions = res.get("versions") or []
        cur_date_str = versions[0].get("date") if versions else None
        d = _parse_date(cur_date_str)
        return (0, -(d.toordinal())) if d else (1, 0)
    return sorted(results, key=key)

def _escape_multiline(s: str) -> str:
    if not s:
        return ""
    return "<br>".join(html.escape(s).splitlines())
    
def write_software_page(cfg: dict, outdir: Path, css_link: str = '<link rel="stylesheet" href="assets/site.css">'):
    """
    Build docs/software.html and docs/software.json.
    Adds a bright border around any software tile whose version differs from the previous run.
    """
    from html import escape as esc
    outdir.mkdir(parents=True, exist_ok=True)

    # 1) Load previous versions (if any)
    prev_path = outdir / "software.json"
    prev_versions: dict[str, str] = {}
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                prev_versions = {str(k): str(v) for k, v in prev.items()}
            elif isinstance(prev, list):
                # backward-compat: convert list of objects to {id/name: version}
                for it in prev:
                    if isinstance(it, dict):
                        key = str(it.get("id") or it.get("name") or "").strip()
                        ver = str(it.get("version") or "").strip()
                        if key:
                            prev_versions[key] = ver
        except Exception:
            prev_versions = {}

    # 2) Fetch current versions
    items = cfg.get("software") or []
    results = []
    current_versions: dict[str, str] = {}
    for it in items:
        sid    = (it.get("id") or "").strip()
        name   = (it.get("name") or sid or "Software").strip()
        vendor = (it.get("vendor") or "SOFTWARE").strip()
        url    = it.get("url") or "#"

        res = fetch_software(sid, name, url)
        ok, ver, err = res.get("ok"), (res.get("version") or ""), res.get("error")

        key = sid or name  # stable identity across runs
        current_versions[key] = ver

        prev_ver = prev_versions.get(key, "")
        changed  = bool(ok and ver and prev_ver and ver != prev_ver)

        # Build the card with a “changed” class if version differs from last run
        classes = ["card"]
        if changed:
            classes.append("card--swchanged")

        html_card = (
            f'<div class="{" ".join(classes)}" data-vendor="software">'
            f'  <h3 class="card-title">{esc(name)}'
            f'    <span class="badge">{esc(vendor.upper())}</span>'
            f'  </h3>'
            f'  <div class="kv"><span class="k">Version</span><span class="v">{esc(ver or "—")}</span></div>'
            f'  <div class="meta"><a href="{esc(url)}" target="_blank" rel="noreferrer">Official page</a></div>'
            + (f'  <div class="error">{esc(err)}</div>' if (not ok and err) else "")
            + '</div>'
        )
        results.append(html_card)

    body = "\n".join(results) if results else "<p>No software configured.</p>"

    # 3) Write the page (include a tiny style for the “changed” border)
    style = """
<style>
/* highlight: different version than previous run */
.card--swchanged{border:3px solid #38bdf8;box-shadow:0 0 0 2px rgba(56,189,248,.18)}
/* ensure cards/grid look good even if site.css changes */
.grid{display:grid;gap:16px;grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:1200px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:620px){.grid{grid-template-columns:1fr}}
.card{padding:22px 22px;border:0}
.card h3{font-size:16px;line-height:1.25;margin:0 0 6px;display:flex;align-items:baseline;gap:8px}
.card h3 .badge{margin-left:auto}
.kv{display:flex;align-items:baseline;gap:8px}
.kv .k{font-weight:600}
.kv .k::after{content:"\\00a0\\00a0"}
.kv .v{font-weight:400}
.meta{display:flex;align-items:center;gap:10px;margin:8px 0 0}
.button{background:#1b2247;border:1px solid #5a64b5;color:#e6e9f2;padding:8px 12px;border-radius:8px;font-size:13px;text-decoration:none;display:inline-block}
.button:hover{filter:brightness(1.1)}
</style>
""".strip()

    html_page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>QA Software</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{css_link}
{style}
</head>
<body>
  <main class="container">
    <h1 style="margin:16px 0;">QA Software</h1>
    <p style="margin:0 0 10px;font-size:13px;opacity:.85">
      <span style="display:inline-block;border:3px solid #38bdf8;box-shadow:0 0 0 2px rgba(56,189,248,.18);width:14px;height:14px;border-radius:3px;vertical-align:middle;margin-right:6px"></span>
      Highlight = version changed since last run
    </p>
    <div class="grid">{body}</div>
    <p style="margin-top:20px;"><a class="button" href="index.html">← Back to BIOS Tracker</a></p>
  </main>
</body>
</html>"""
    (outdir / "software.html").write_text(html_page, encoding="utf-8")

    # 4) Persist current versions for next comparison
    prev_path.write_text(json.dumps(current_versions, indent=2), encoding="utf-8")




# ===== Motherboard Images (text-only, Name + Date Updated) =====
import csv, html
from pathlib import Path

def _load_images_csv_ordered(csv_path: Path) -> list[dict]:
    """
    Load images.csv in file order; keep rows as-typed.
    Accepts headers like:
      name,date
      title,date
      model,date
      name,Date Updated
    """
    rows = []
    if not csv_path.exists():
        return rows

    # utf-8-sig tolerates BOM
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return rows

        def get(r, *names):
            for n in names:
                if n in r and r[n] is not None:
                    return r[n]
            return ""

        for r in reader:
            name = get(r, "name", "Name", "title", "Title", "model", "Model").strip()
            date = get(r, "date", "Date", "date updated", "Date Updated").strip()
            if not name:
                continue
            rows.append({"name": name, "date": date})

    return rows  # preserve insertion order

def _render_images_html_grouped(rows: list[dict], site_title: str = "Motherboard Images") -> str:
    # Build data rows with inline zebra backgrounds so external CSS cannot override
    if rows:
        parts = []
        for i, r in enumerate(rows, start=1):
            bg = "#0e1530" if (i % 2 == 0) else "#0f1630"  # even / odd
            name = html.escape(r["name"])
            date = html.escape(r.get("date", ""))
            parts.append(
                f'''<div class="row" style="background:{bg};">
                       <div class="cell name">{name}</div>
                       <div class="cell date">{date}</div>
                    </div>'''
            )
        rows_html = "\n".join(parts)
    else:
        rows_html = '''<div class="row" style="background:#0f1630;">
                          <div class="cell name" style="grid-column:1 / span 2;">No entries yet. Edit <code>images.csv</code> to add rows.</div>
                        </div>'''

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{site_title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="assets/site.css?cb=imgzebra">
  <style>
    /* Scope to this page */
    body.images-page .nav-buttons{{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}}
    body.images-page .button{{background:#1b2247;border:1px solid #5a64b5;color:#e6e9f2;padding:8px 12px;border-radius:8px;font-size:13px;text-decoration:none;display:inline-block}}
    body.images-page .button:hover{{filter:brightness(1.1)}}

    /* Sheet frame */
    body.images-page .sheet{{border:1px solid #39407a; background:#0f1630}}

    /* Each row is a 2-col grid: Name | Date */
    body.images-page .row{{display:grid; grid-template-columns:minmax(320px,1fr) 170px}}

    /* Cells are transparent; row carries the zebra background */
    body.images-page .cell{{
      box-sizing:border-box;
      padding:10px 12px;
      border-bottom:1px solid #39407a;
      border-right:1px solid #39407a;
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
      text-align:left;       /* LEFT align both columns */
      line-height:1.35;
      background:transparent;
    }}
    /* Clean outer border */
    body.images-page .row .cell:last-child{{border-right:none}}

    /* Header row */
    body.images-page .row.head{{background:#141b3a}}
    body.images-page .row.head .cell{{font-weight:600}}

    @media (max-width:700px){{
      body.images-page .row{{grid-template-columns:minmax(240px,1fr) 140px}}
    }}
  </style>
</head>
<body class="images-page">
  <main class="container">
    <h1 style="margin:16px 0;">Motherboard Images</h1>
    <div class="nav-buttons">
      <a class="button" href="index.html">← BIOS Tracker</a>
      <a class="button" href="software.html">QA Software</a>
      <a class="button" href="images.html" aria-current="page">Motherboard Images</a>
    </div>

    <div class="sheet">
      <div class="row head">
        <div class="cell name">Name</div>
        <div class="cell date">Date Updated</div>
      </div>
      {rows_html}
    </div>
  </main>
</body>
</html>"""








def write_images_page(outdir: Path, csv_path: Path | None = None):
    """
    Build docs/images.html from images.csv (Name + Date).
    Finds the CSV next to this script by default; preserves row order.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    # Prefer images.csv next to this script; fall back to CWD
    if csv_path is None:
        repo_root = Path(__file__).parent
        candidates = [repo_root / "images.csv", Path.cwd() / "images.csv"]
        csv_path = next((p for p in candidates if p.exists()), candidates[0])

    rows = _load_images_csv_ordered(csv_path)
    html_page = _render_images_html_grouped(rows)
    (outdir / "images.html").write_text(html_page, encoding="utf-8")
    print(f"[images] Loaded {len(rows)} rows from {csv_path}")




# -------------------------------------------------------------------
# Google Form / Sheet comments (Type, Website, Details)
# -------------------------------------------------------------------
def _get_google_comments_cfg(cfg: dict):
    c = (cfg.get("comments_google") or {})
    form = c.get("form_embed") or DEFAULT_FORM_EMBED
    sid  = c.get("sheet_id")   or DEFAULT_SHEET_ID
    gid  = c.get("gid")        or DEFAULT_GID
    return form, sid, gid

def _google_comments_block(cfg: dict) -> str:
    """One button opens the form; render recent submissions (Type, Website, Details) with robust fetch + errors."""
    form_embed, sheet_id, gid = _get_google_comments_cfg(cfg)

    # If placeholders still present, show setup banner
    if "REPLACE_" in form_embed or "REPLACE_" in sheet_id or "REPLACE_" in gid:
        return """
<section class="comments">
  <h2>Report a board</h2>
  <p class="hint">Owner setup required: configure the 3 constants at the top of <code>bios_tracker.py</code>: <code>DEFAULT_FORM_EMBED</code>, <code>DEFAULT_SHEET_ID</code>, <code>DEFAULT_GID</code>.</p>
</section>
"""

    from html import escape as esc
    form_plain = form_embed.replace("/viewform?embedded=true", "/viewform")
    gviz = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json&gid={gid}"
    csv  = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    return f"""
<section class="comments">
  <h2>Report a board</h2>

  <div class="comments__toolbar">
    <a class="button" href="{esc(form_plain)}" target="_blank" rel="noreferrer">
      Report Problem
    </a>
  </div>

  <h3 style="margin-top:14px">Recent submissions</h3>
  <div id="comments-list" class="comment-list">Loading…</div>

  <script>
  (function() {{
    const LIST = document.getElementById('comments-list');
    const GVIZ = {gviz!r};
    const CSV  = {csv!r};

    function esc(s) {{ return String(s||'').replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}})[c] || c); }}
    function pick(obj, keys) {{ const o={{}}; keys.forEach(k=>o[k]=obj[k]??''); return o; }}

    async function load() {{
      try {{
        const items = await fetchGviz();
        render(items);
      }} catch (e1) {{
        console.warn('GViz failed, trying CSV…', e1);
        try {{
          const items = await fetchCsv();
          render(items);
        }} catch (e2) {{
          console.error('CSV failed', e2);
          LIST.innerHTML = '<div class="comment">Failed to load entries.<br><small>'
            + esc(String(e1).slice(0,200)) + '</small></div>';
        }}
      }}
    }}

    async function fetchGviz() {{
      const res = await fetch(GVIZ, {{ headers: {{ 'Accept':'text/plain' }} }});
      if (!res.ok) throw new Error('GViz HTTP ' + res.status);
      const text = await res.text();
      const start = text.indexOf('{{'); const end = text.lastIndexOf('}}');
      if (start < 0 || end < 0) throw new Error('GViz: unexpected response (no JSON found)');
      const json = JSON.parse(text.slice(start, end+2));
      const table = json.table || {{}}; const cols = (table.cols||[]).map(c => c.label || c.id);
      const rows = (table.rows||[]).map(r => {{
        const o = {{}}; (r.c||[]).forEach((cell,i)=>o[cols[i] || ('c'+i)] = cell ? cell.v : ''); return o;
      }});
      const name = n => cols.find(h => (h||'').toLowerCase() === n) || '';
      const H = {{
        ts:   name('timestamp') || cols[0] || 'Timestamp',
        type: name('type')      || 'Type',
        site: name('website')   || 'Website',
        det:  name('details')   || 'Details'
      }};
      const items = rows.map(r => pick(r, [H.ts,H.type,H.site,H.det])).map(r => ({{
        ts: r[H.ts], type: r[H.type], website: r[H.site], details: r[H.det]
      }})).sort((a,b)=> new Date(b.ts||0)-new Date(a.ts||0));
      return items;
    }}

    async function fetchCsv() {{
      const res = await fetch(CSV);
      if (!res.ok) throw new Error('CSV HTTP ' + res.status);
      const text = await res.text();
      const lines = text.split(/\\r?\\n/).filter(Boolean);
      if (!lines.length) return [];
      const headers = lines.shift().split(',').map(h => h.trim().replace(/^"|"$/g,''));
      const idx = (want) => headers.findIndex(h => h.toLowerCase() === want);
      const iTs = idx('timestamp'), iType = idx('type'), iSite = idx('website'), iDet = idx('details');

      function parseRow(line){{
        const cells = parseCsvLine(line);
        return {{
          ts:   cells[iTs]   ?? '',
          type: cells[iType] ?? '',
          website: cells[iSite] ?? '',
          details: cells[iDet] ?? ''
        }};
      }}

      const items = lines.map(parseRow)
        .filter(x => x.ts || x.details || x.type || x.website)
        .sort((a,b)=> new Date(b.ts||0)-new Date(a.ts||0));
      return items;
    }}

    function parseCsvLine(line){{
      const out = []; let cur = ''; let quote = false;
      for (let i=0;i<line.length;i++) {{
        const ch = line[i];
        if (quote) {{
          if (ch === '"') {{
            if (line[i+1] === '"') {{ cur += '"'; i++; }} else {{ quote = false; }}
          }} else cur += ch;
        }} else {{
          if (ch === ',') {{ out.push(cur); cur=''; }}
          else if (ch === '"') quote = true;
          else cur += ch;
        }}
      }}
      out.push(cur);
      return out.map(s => s.trim());
    }}

    function render(items){{
      if (!items.length) {{
        LIST.innerHTML = '<div class="comment">No entries yet.</div>';
        return;
      }}
      LIST.innerHTML = items.map(it => `
        <article class="comment">
          <div class="meta">
            <strong>[${{esc(it.type)}}]</strong>
            <span>${{esc(it.website)}}</span>
            <span>${{esc(it.ts)}}<\/span>
          <\/div>
          <div class="body">${{esc(it.details)}}<\/div>
        <\/article>
      `).join('');
    }}

    load();
  }})();
  </script>
</section>
"""


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    cfg = load_config()
    vendors = (cfg.get("vendors") or {})

    # Manual issue flags (optional)
    issue_names: set[str] = set(map(str, (cfg.get("issues") or [])))
    for vendor_key, boards in vendors.items():
        for b in boards or []:
            if isinstance(b, dict) and b.get("issue"):
                name = str(b.get("name") or b.get("model") or "").strip()
                if name:
                    issue_names.add(name)

    # Optional notes
    notes_text = (cfg.get("notes") or "").strip()

    results: list[dict] = []

    def normalize_model(item):
        if isinstance(item, dict):
            return item.get("name") or item.get("model") or "", item.get("url")
        return str(item), None

    # Scrape vendors
    for vkey, models in vendors.items():
        func = VENDOR_FUNCS.get(vkey.lower())
        if not func:
            print(f"Unknown vendor key: {vkey}", file=sys.stderr)
            continue
        for item in (models or []):
            model, override_url = normalize_model(item)
            print(f"[{vkey}] {model} ...", file=sys.stderr)
            try:
                res = func(model, override_url=override_url)
            except TypeError:
                res = func(model)
            except Exception as e:
                res = {
                    "vendor": vkey.upper(),
                    "model": model,
                    "url": override_url or "",
                    "versions": [],
                    "ok": False,
                    "error": str(e),
                }
            results.append(res)
            time.sleep(0.3)

    # Sort cards by current release date (newest first)
    results = _sort_results_newest_first(results)

    # Build cards
    today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    cards_html = "\n".join(build_card(r, issue_names=issue_names, today=today) for r in results)

    # Comments section (Google Form + Sheet)
    comments_html = _google_comments_block(cfg)

    # Write docs
    docs = Path("docs"); docs.mkdir(parents=True, exist_ok=True)
    idx = docs / "index.html"
    data_path = docs / "data.json"

    now = datetime.datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M %Z")

    header_html = f"""
<header class="page-header">
  <h1>Motherboard BIOS Tracker</h1>
  <div class="search">
    <input type="search" id="search-input" placeholder="Search model…" aria-label="Search models" />
  </div>
  <div class="toolbar">
    <button data-filter="all" class="active">All</button>
    <button data-filter="ASUS">ASUS</button>
    <button data-filter="MSI">MSI</button>
    <button data-filter="GIGABYTE">GIGABYTE</button>
    <button data-filter="ASRock">ASRock</button>
  </div>
</header>
"""

    nav_buttons_html = """
<div class="nav-buttons">
  <a class="button" href="software.html" title="QA Software">QA Software</a>
  <a class="button" href="images.html" title="Motherboard Images">Motherboard Images</a>
</div>
"""


    # Status bar — timestamp left; legend centered via hidden clone
    statusbar_html = f"""
<div class="statusbar" role="note" aria-label="Legend and last updated">
  <div class="last-updated">Last updated: {html.escape(now)}</div>
  <div class="legend">
    <span class="legend-item"><span class="swatch swatch--fresh"></span>New in last 5 days</span>
    <span class="legend-item"><span class="swatch swatch--issue"></span>Manually flagged</span>
  </div>
  <div class="last-updated last-updated--clone" aria-hidden="true">Last updated: {html.escape(now)}</div>
</div>
"""

    # Optional notes
    notes_html = ""
    if notes_text:
        notes_html = f"""
<div class="notice" role="note" aria-label="Site notes">
  <strong>Notes:</strong> {_escape_multiline(notes_text)}
</div>
"""

    # Inline styles (keeps your page layout + comments)
    inline_css = """
<style>
/* wider page */
.container{max-width:1600px;margin:0 auto;padding:0 16px}

/* page header: title | search | filter */
.page-header{
  display:grid;
  grid-template-columns:auto 1fr auto;
  align-items:center;
  gap:12px;
  margin:8px 0 6px
}
.page-header h1{font-size:28px;margin:0}

/* search */
.search input{
  width:100%;
  padding:8px 10px;
  border:1px solid #39407a;
  border-radius:8px;
  background:#0f1630;
  color:#e6e9f2;
  font-size:14px;
}

/* filter bar */
.toolbar{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.toolbar button{
  background:#0f1630;border:1px solid #39407a;color:#e6e9f2;
  padding:6px 10px;border-radius:999px;font-size:13px;cursor:pointer
}
.toolbar button.active{background:#1b2247;border-color:#5a64b5}

/* Status bar with hidden clone for true centering */
.statusbar{
  display:grid;
  grid-template-columns:auto 1fr auto;
  align-items:center;
  width:100%;
  min-height:28px;
  margin:10px 0 12px
}
.statusbar .last-updated{grid-column:1;justify-self:start;align-self:center;font-size:12px;opacity:.85;line-height:1;margin:0}
.statusbar .legend{
  grid-column:2;justify-self:center;align-self:center;display:flex;gap:12px;flex-wrap:wrap;align-items:center;font-size:12px;opacity:.9;margin:0;text-align:center
}
.statusbar .last-updated--clone{grid-column:3;visibility:hidden;pointer-events:none;line-height:1}

/* legend pills & swatches */
.legend .legend-item{display:flex;align-items:center;gap:6px;background:#0f1630;border:1px solid #39407a;border-radius:999px;padding:4px 8px;line-height:1}
.legend .swatch{width:12px;height:12px;border-radius:2px;display:inline-block}
.legend .swatch--fresh{border:2px solid #22c55e;box-shadow:0 0 0 2px rgba(34,197,94,.15) inset}
.legend .swatch--issue{border:2px solid #f97316;box-shadow:0 0 0 2px rgba(249,115,22,.18) inset}

/* notes */
.notice{margin:8px 0 16px;padding:10px 12px;background:#0f1630;border:1px solid #39407a;border-radius:10px;color:#e6e9f2;font-size:14px}

/* cards */
.card{padding:22px 22px;border:0}
.card--fresh{border:3px solid #22c55e;box-shadow:0 0 0 2px rgba(34,197,94,.15)}
.card--issue{border:3px solid #f97316;box-shadow:0 0 0 2px rgba(249,115,22,.18)}
.card h3{font-size:16px;line-height:1.25;margin:0 0 6px;display:flex;align-items:baseline;gap:8px}
.card h3 .badge{margin-left:auto}
.card .meta{display:flex;align-items:center;gap:10px;margin:0 0 10px}
.card .meta a{color:#9fb4ff}

/* kv rows */
.kv{display:flex;align-items:baseline;gap:8px}
.kv .k{font-weight:600}
.kv .k::after{content:"\\00a0\\00a0"} /* two NBSPs */
.kv .v{font-weight:400}
.kv .date{margin-left:auto;white-space:nowrap;opacity:.8}

/* grid: max four per row */
.grid{display:grid;gap:16px;grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:1200px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:620px){
  .grid{grid-template-columns:1fr}
  .page-header{grid-template-columns:1fr;gap:10px}
  .toolbar{justify-content:flex-start}
}

/* comments (Google Form button + list) */
.comments{margin:24px 0 40px}
.comments h2{margin:0 0 8px;font-size:18px}
.comments .hint{opacity:.85}
.comments__toolbar{display:flex;gap:8px;justify-content:flex-end;margin:8px 0}
.comment-list{display:grid;gap:10px;margin-top:8px}
.comment{border:1px solid #39407a;border-radius:10px;padding:10px 12px;background:#0f1630}
.comment .meta{display:flex;gap:10px;align-items:center;font-size:12px;opacity:.85;margin-bottom:6px;flex-wrap:wrap}
.comment .body{white-space:pre-wrap}

/* generic button look to match your UI */
.button{background:#1b2247;border:1px solid #5a64b5;color:#e6e9f2;padding:8px 12px;border-radius:8px;font-size:13px;cursor:pointer;text-decoration:none;display:inline-block}
.button:hover{filter:brightness(1.1)}
/* top nav buttons */
.nav-buttons{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}

</style>
"""

    # Filter + search behavior
    filter_js = """
<script>
document.addEventListener('DOMContentLoaded', () => {
  const buttons = document.querySelectorAll('.toolbar [data-filter]');
  const cards = document.querySelectorAll('.grid .card');
  const search = document.getElementById('search-input');
  let activeFilter = 'all';
  function applyAll(){
    const q = (search.value || '').trim().toLowerCase();
    cards.forEach(c => {
      const v = (c.dataset.vendor || '').toLowerCase();
      const model = (c.querySelector('h3')?.textContent || '').toLowerCase();
      const matchesVendor = (activeFilter === 'all') || (v === activeFilter.toLowerCase());
      const matchesQuery  = !q || model.includes(q);
      c.style.display = (matchesVendor && matchesQuery) ? '' : 'none';
    });
  }
  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      activeFilter = btn.dataset.filter || 'all';
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyAll();
    });
  });
  search.addEventListener('input', applyAll);
});
</script>
"""

    # Final page
    page_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BIOS Tracker</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="assets/site.css?v=6">
  {inline_css}
</head>
<body>
  <div class="container">
    {header_html}
    {nav_buttons_html}
    {statusbar_html}
    {notes_html}
    <div class="grid">
      {cards_html}
    </div>
    {_google_comments_block(cfg)}
  </div>
  {filter_js}
</body>
</html>
"""

    # Write outputs
    idx.write_text(page_html, encoding="utf-8")
    data_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Done. Wrote docs/index.html and docs/data.json")
 
    docs_dir = Path("docs")
    # re-use your real CSS link if you build a cache-busted one; otherwise the default is fine
    write_software_page(cfg, docs_dir)
    write_images_page(docs_dir)



if __name__ == "__main__":
    main()
