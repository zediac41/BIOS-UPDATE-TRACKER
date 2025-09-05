#!/usr/bin/env python3
import json, yaml, datetime, html, time, sys, re
from pathlib import Path
from zoneinfo import ZoneInfo

# vendor modules
from vendors import asus, msi, gigabyte, asrock

VENDOR_FUNCS = {
    "asus": asus.latest_two,
    "msi": msi.latest_two,
    "gigabyte": gigabyte.latest_two,
    "asrock": asrock.latest_two,
}

def load_config():
    with open("config.yml","r",encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# --- Normalize any vendor's beta label to "(Beta)" ---
_BETA_PARENS = re.compile(r"\(\s*beta\s+version\s*\)", re.I)
_BETA_BARE   = re.compile(r"\b(beta(?:\s+version)?)\b", re.I)

def normalize_beta(version: str | None) -> str | None:
    if not version:
        return version
    v = version
    v = _BETA_PARENS.sub("(Beta)", v)
    if "(Beta)" not in v and re.search(_BETA_BARE, v):
        v = _BETA_BARE.sub("", v).strip()
        v = re.sub(r"\s{2,}", " ", v).strip()
        v = f"{v} (Beta)"
    return v

# ---- Parse YYYY-MM-DD or YYYY/MM/DD (or YYYY.MM.DD) into a date() ----
def _parse_date(date_str: str | None) -> datetime.date | None:
    if not date_str:
        return None
    s = str(date_str).strip().replace("/", "-").replace(".", "-")
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return datetime.date(y, m, d)
    except Exception:
        return None

# ---- Freshness window (last 7 days) ----
def _is_fresh_release(date_str: str | None, today: datetime.date | None = None) -> bool:
    d = _parse_date(date_str)
    if not d:
        return False
    if today is None:
        today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    delta = (today - d).days
    return 0 <= delta <= 7

# Row helper: label | (two spaces via CSS) | version | date right-aligned
def _row(label: str, version: str | None, date: str | None):
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
    vendor = entry.get("vendor","")
    model = entry.get("model","")
    url = entry.get("url","#")
    ok = entry.get("ok", False)
    vlist = entry.get("versions", [])[:2]
    err = entry.get("error")

    # Decide highlight class:
    current_date_str = vlist[0].get("date") if (ok and vlist) else None
    is_issue = bool(issue_names and model in issue_names)
    is_fresh = _is_fresh_release(current_date_str, today=today)

    classes = ["card"]
    if is_issue:
        classes.append("card--issue")    # manual orange wins over auto green
    elif is_fresh:
        classes.append("card--fresh")

    parts = []
    parts.append(f'<div class="{" ".join(classes)}" data-vendor="{html.escape(vendor)}">')
    parts.append(f'  <h3>{html.escape(model)} <span class="badge">{html.escape(vendor)}</span></h3>')
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
        parts.append('  <div class="error">Couldn\'t fetch versions.</div>')
        if err:
            parts.append(f'  <pre class="meta">{html.escape(str(err))}</pre>')

    parts.append('</div>')
    return "\n".join(parts)

def _sort_results_newest_first(results: list[dict]) -> list[dict]:
    """
    Sort tiles by the 'Current' version release date (newest first).
    Entries without a valid date go last (stable among themselves).
    """
    def key(res):
        versions = res.get("versions") or []
        cur_date_str = versions[0].get("date") if versions else None
        d = _parse_date(cur_date_str)
        return (0, -(d.toordinal())) if d else (1, 0)
    return sorted(results, key=key)

def _comments_block(cfg: dict | None = None) -> str:
    """Embed giscus comments (fixed settings)."""
    return """
<section class="comments">
  <h2>Comments & Requests</h2>
  <script src="https://giscus.app/client.js"
          data-repo="zediac41/BIOS-UPDATE-TRACKER"
          data-repo-id="R_kgDOPkR12A"
          data-category="General"
          data-category-id="DIC_kwDOPkR12M4Cu6A0"
          data-mapping="pathname"
          data-strict="0"
          data-reactions-enabled="1"
          data-emit-metadata="0"
          data-input-position="top"
          data-theme="preferred_color_scheme"
          data-lang="en"
          data-loading="lazy"
          crossorigin="anonymous"
          async>
  </script>
  <noscript>Please enable JavaScript to view the comments.</noscript>
</section>
"""

def main():
    cfg = load_config()
    vendors = (cfg.get("vendors") or {})

    # Collect manual issue flags
    issue_names: set[str] = set(map(str, (cfg.get("issues") or [])))
    for vendor_key, boards in vendors.items():
        for b in boards or []:
            if isinstance(b, dict) and b.get("issue"):
                name = str(b.get("name") or b.get("model") or "").strip()
                if name:
                    issue_names.add(name)

    results = []

    def normalize_model(item):
        if isinstance(item, dict):
            return item.get("name") or item.get("model") or "", item.get("url")
        return str(item), None

    for vkey, models in vendors.items():
        func = VENDOR_FUNCS.get(vkey.lower())
        if not func:
            print(f"Unknown vendor key: {vkey}", file=sys.stderr); continue
        for item in (models or []):
            model, override_url = normalize_model(item)
            print(f"[{vkey}] {model} ...", file=sys.stderr)
            try:
                res = func(model, override_url=override_url)
            except TypeError:
                res = func(model)
            except Exception as e:
                res = {"vendor": vkey.upper(), "model": model, "url": override_url or "", "versions":[], "ok":False, "error":str(e)}
            results.append(res)
            time.sleep(0.3)

    # Sort cards by current release date (newest first)
    results = _sort_results_newest_first(results)

    # Build cards HTML (with highlight logic)
    today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    cards_html = "\n".join(build_card(r, issue_names=issue_names, today=today) for r in results)

    # Adding Comments
    comments_html = _comments_block(cfg)

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

    # NEW: status bar — left aligned timestamp, legend centered on the same line
    statusbar_html = f"""
<div class="statusbar" role="note" aria-label="Legend and last updated">
  <div class="last-updated">Last updated: {html.escape(now)}</div>
  <div class="legend">
    <span class="legend-item"><span class="swatch swatch--fresh"></span>Updated within a week</span>
    <span class="legend-item"><span class="swatch swatch--issue"></span>Updating incorrectly</span>
  </div>
</div>
"""

    # Styles (includes left-fixed timestamp + centered legend)
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

/* NEW: statusbar line — keep timestamp at left, legend centered.
   Use position:relative and absolutely center the legend, so it stays centered
   regardless of the timestamp width. */
.statusbar{
  position:relative;
  min-height:28px;
  margin:10px 0 16px;
}
.statusbar .last-updated{
  position:relative;               /* normal flow at left */
  font-size:12px; opacity:.85;
}
.statusbar .legend{
  position:absolute;               /* center independently of left content */
  left:50%; transform:translateX(-50%);
  display:flex; gap:12px; flex-wrap:wrap; align-items:center;
  font-size:12px; opacity:.9;
}
.legend .legend-item{
  display:flex; align-items:center; gap:6px;
  background:#0f1630; border:1px solid #39407a;
  border-radius:999px; padding:4px 8px
}
.legend .swatch{
  width:12px; height:12px; border-radius:2px; display:inline-block
}
.legend .swatch--fresh{border:2px solid #22c55e; box-shadow:0 0 0 2px rgba(34,197,94,.15) inset}
.legend .swatch--issue{border:2px solid #f97316; box-shadow:0 0 0 2px rgba(249,115,22,.18) inset}

/* small screens: stack nicely */
@media (max-width: 700px){
  .statusbar{display:grid; row-gap:6px}
  .statusbar .legend{position:static; transform:none; justify-content:center}
  .statusbar .last-updated{text-align:center}
}

.last-updated{opacity:.75}

/* cards */
.card{padding:22px 22px; border:0}
.card--fresh{
  border:3px solid #22c55e;
  box-shadow:0 0 0 2px rgba(34,197,94,.15);
}
.card--issue{
  border:3px solid #f97316;
  box-shadow:0 0 0 2px rgba(249,115,22,.18);
}
.card h3{font-size:16px;line-height:1.25;margin:0 0 6px;display:flex;align-items:baseline;gap:8px}
.card h3 .badge{margin-left:auto}

/* kv rows: version normal weight, date at right, two spaces after label */
.kv{display:flex;align-items:baseline;gap:8px}
.kv .k{font-weight:600}
.kv .k::after{content:"\\00a0\\00a0"} /* two NBSPs */
.kv .v{font-weight:400}
.kv .date{margin-left:auto;white-space:nowrap;opacity:.8}

/* grid cap */
.grid{display:grid;gap:16px;grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:1200px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:620px){
  .grid{grid-template-columns:1fr}
  .page-header{grid-template-columns:1fr;gap:10px}
  .toolbar{justify-content:flex-start}
}
</style>
"""

    # Combined vendor+search filtering
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

page_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BIOS Tracker</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="assets/site.css">
  {inline_css}
</head>
<body>
  <div class="container">
    {header_html}
    {statusbar_html}
    <div class="grid">
      {cards_html}
    </div>
    {comments_html}  <!-- ← add this -->
  </div>
  {filter_js}
</body>
</html>
"""


    idx.write_text(page_html, encoding="utf-8")
    data_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Done. Wrote docs/index.html and docs/data.json")

if __name__ == "__main__":
    main()
