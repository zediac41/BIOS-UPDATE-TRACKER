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
    parts.append(
        '  <h3>'
        f'{html.escape(model)} '
        f'<span class="badge">{html.escape(vendor)}</span>'
        '  </h3>'
    )
    # vendor link + report button row
    parts.append(
        '  <div class="meta">'
        f'    <a href="{html.escape(url)}" target="_blank" rel="noreferrer">Vendor page</a>'
        f'    <button class="report-btn" data-vendor="{html.escape(vendor)}" data-model="{html.escape(model)}" type="button">Report</button>'
        '  </div>'
    )

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

def main():
    cfg = load_config()
    vendors = (cfg.get("vendors") or {})

    # Manual issue flags
    issue_names: set[str] = set(map(str, (cfg.get("issues") or [])))
    for vendor_key, boards in vendors.items():
        for b in boards or []:
            if isinstance(b, dict) and b.get("issue"):
                name = str(b.get("name") or b.get("model") or "").strip()
                if name:
                    issue_names.add(name)

    # Reporting config
    report_cfg = (cfg.get("report") or {})
    report_mode = (report_cfg.get("mode") or ("github" if report_cfg.get("github_repo") else "mailto")).lower()
    github_repo = (report_cfg.get("github_repo") or "").strip()
    github_labels = report_cfg.get("labels") or ["report"]
    mailto_addr = (report_cfg.get("mailto") or "").strip()

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
    <button id="report-missing" class="report-global" type="button" title="Report a missing board">Report missing board</button>
  </div>
</header>
"""

    # Status bar (timestamp left, legend centered with hidden clone on right)
    statusbar_html = f"""
<div class="statusbar" role="note" aria-label="Legend and last updated">
  <div class="last-updated">Last updated: {html.escape(now)}</div>
  <div class="legend">
    <span class="legend-item"><span class="swatch swatch--fresh"></span>New in last 7 days</span>
    <span class="legend-item"><span class="swatch swatch--issue"></span>Manually flagged</span>
  </div>
  <div class="last-updated last-updated--clone" aria-hidden="true">Last updated: {html.escape(now)}</div>
</div>
"""

    # Styles (includes report button + modal + statusbar alignment)
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

/* report buttons */
.report-global, .report-btn{
  background:#1b2247;border:1px solid #5a64b5;color:#e6e9f2;
  padding:6px 10px;border-radius:8px;font-size:12px;cursor:pointer
}
.report-btn{margin-left:auto}

/* Status bar with hidden clone to keep legend truly centered */
.statusbar{
  display: grid;
  grid-template-columns: auto 1fr auto;   /* left content | centered area | right clone */
  align-items: center;
  width: 100%;
  min-height: 28px;
  margin: 10px 0 16px;
  box-sizing: border-box;
}
.statusbar .last-updated{
  grid-column: 1;
  justify-self: start;
  align-self: center;
  font-size: 12px;
  opacity: .85;
  line-height: 1;
  margin: 0;
}
.statusbar .legend{
  grid-column: 2;
  justify-self: center;
  align-self: center;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  font-size: 12px;
  opacity: .9;
  margin: 0;
  text-align: center;
}
.statusbar .last-updated--clone{
  grid-column: 3;
  visibility: hidden;
  pointer-events: none;
  line-height: 1;
}

/* legend pills */
.legend .legend-item{
  display:flex; align-items:center; gap:6px;
  background:#0f1630; border:1px solid #39407a;
  border-radius:999px; padding:4px 8px; line-height:1
}
.legend .swatch{
  width:12px; height:12px; border-radius:2px; display:inline-block
}
.legend .swatch--fresh{border:2px solid #22c55e; box-shadow:0 0 0 2px rgba(34,197,94,.15) inset}
.legend .swatch--issue{border:2px solid #f97316; box-shadow:0 0 0 2px rgba(249,115,22,.18) inset}

/* small screens: stack the statusbar */
@media (max-width:700px){
  .statusbar{grid-template-columns: 1fr; row-gap:6px; min-height:unset}
  .statusbar .last-updated{grid-column:1; justify-self:center; text-align:center}
  .statusbar .legend{grid-column:1; justify-self:center}
  .statusbar .last-updated--clone{display:none}
}

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

/* meta row: link left, report button right */
.card .meta{
  display:flex; align-items:center; gap:10px; margin:0 0 10px
}
.card .meta a{color:#9fb4ff}

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

/* --- Modal --- */
.modal{position:fixed; inset:0; display:none}
.modal.is-open{display:block}
.modal__backdrop{
  position:absolute; inset:0; background:rgba(0,0,0,.55)
}
.modal__dialog{
  position:absolute; left:50%; top:50%; transform:translate(-50%,-50%);
  width:min(640px, 92vw);
  background:#0f1630; border:1px solid #39407a; border-radius:12px;
  padding:16px 16px 12px; color:#e6e9f2;
  box-shadow:0 10px 30px rgba(0,0,0,.35)
}
.modal__dialog h2{margin:0 0 10px; font-size:18px}
.form-row{display:grid; grid-template-columns:1fr 1fr; gap:10px}
label{display:block; font-size:12px; opacity:.9; margin:6px 0 4px}
input[type="text"], select, textarea{
  width:100%; padding:8px 10px; border:1px solid #39407a; border-radius:8px;
  background:#0a122c; color:#e6e9f2; font-size:14px
}
textarea{resize:vertical; min-height:100px}
.modal__actions{display:flex; gap:8px; justify-content:flex-end; margin-top:12px}
.button{background:#1b2247;border:1px solid #5a64b5;color:#e6e9f2;padding:8px 12px;border-radius:8px;font-size:13px;cursor:pointer}
.button--secondary{background:transparent}
</style>
"""

    # Scripts: filter/search + report modal
    # (We embed config values so no extra HTTP round-trips)
    js_repo = json.dumps(github_repo)
    js_labels = json.dumps(github_labels)
    js_mode = json.dumps(report_mode)
    js_mailto = json.dumps(mailto_addr)

    filter_and_report_js = f"""
<script>
document.addEventListener('DOMContentLoaded', () => {{
  // --- Filter + search ---
  const buttons = document.querySelectorAll('.toolbar [data-filter]');
  const cards = document.querySelectorAll('.grid .card');
  const search = document.getElementById('search-input');
  let activeFilter = 'all';
  function applyAll(){{
    const q = (search.value || '').trim().toLowerCase();
    cards.forEach(c => {{
      const v = (c.dataset.vendor || '').toLowerCase();
      const model = (c.querySelector('h3')?.textContent || '').toLowerCase();
      const matchesVendor = (activeFilter === 'all') || (v === activeFilter.toLowerCase());
      const matchesQuery  = !q || model.includes(q);
      c.style.display = (matchesVendor && matchesQuery) ? '' : 'none';
    }});
  }}
  buttons.forEach(btn => {{
    btn.addEventListener('click', () => {{
      activeFilter = btn.dataset.filter || 'all';
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyAll();
    }});
  }});
  search.addEventListener('input', applyAll);

  // --- Report modal ---
  const REPORT_MODE = {js_mode};  // 'github' or 'mailto'
  const GH_REPO = {js_repo};      // 'owner/repo'
  const REPORT_LABELS = {js_labels}; // array of labels (['report'])
  const MAILTO = {js_mailto};     // fallback email

  const modal = document.getElementById('report-modal');
  const dlg = modal?.querySelector('.modal__dialog');
  const typeEl = document.getElementById('report-type');
  const vendorEl = document.getElementById('report-vendor');
  const modelEl = document.getElementById('report-model');
  const detailsEl = document.getElementById('report-details');
  const cancelBtn = document.getElementById('report-cancel');
  const form = document.getElementById('report-form');

  function openReport(init) {{
    typeEl.value = init?.type || 'missing';
    vendorEl.value = init?.vendor || '';
    modelEl.value = init?.model || '';
    detailsEl.value = init?.details || '';
    modal.classList.add('is-open');
    detailsEl.focus();
  }}
  function closeReport(){{
    modal.classList.remove('is-open');
  }}

  // Per-card Report buttons
  document.querySelectorAll('.report-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      openReport({{ type: 'problem', vendor: btn.dataset.vendor || '', model: btn.dataset.model || '' }});
    }});
  }});

  // Global Report missing board
  const globalBtn = document.getElementById('report-missing');
  if (globalBtn) {{
    globalBtn.addEventListener('click', () => openReport({{ type: 'missing' }}));
  }}

  // Close actions
  cancelBtn?.addEventListener('click', closeReport);
  modal?.addEventListener('click', (e) => {{
    if (e.target === modal) closeReport();
  }});
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape' && modal.classList.contains('is-open')) closeReport();
  }});

  // Submit -> open GitHub Issue or mailto
  form?.addEventListener('submit', (e) => {{
    e.preventDefault();
    const type = typeEl.value || 'other';
    const vendor = vendorEl.value.trim() || '(unknown)';
    const model = modelEl.value.trim() || '(missing board)';
    const details = detailsEl.value.trim() || '(no details provided)';

    const typeLabel = ({{missing:'Missing board', problem:'Not working properly', other:'Other'}})[type] || 'Other';
    const title = `[Report] ${{vendor}} - ${{model}} - ${{typeLabel}}`;

    const body = [
      `**Type:** ${{typeLabel}}`,
      `**Vendor:** ${{vendor}}`,
      `**Model:** ${{model}}`,
      '',
      '### Details',
      details,
      '',
      `Submitted from BIOS Tracker on {html.escape(now)}`
    ].join('\\n');

    let url = '';
    if (REPORT_MODE === 'github' && GH_REPO) {{
      const labels = (REPORT_LABELS || []).join(',');
      const params = new URLSearchParams({{
        title: title,
        body: body
      }});
      if (labels) params.set('labels', labels);
      url = `https://github.com/${{GH_REPO}}/issues/new?${{params.toString()}}`;
    }} else {{
      const to = MAILTO || '';
      const params = new URLSearchParams({{
        subject: title,
        body: body
      }});
      url = `mailto:${{to}}?${{params.toString()}}`;
    }}

    window.open(url, '_blank', 'noopener');
    closeReport();
  }});
}});
</script>
"""

    # Modal markup
    modal_html = """
<div id="report-modal" class="modal" aria-hidden="true">
  <div class="modal__backdrop"></div>
  <div class="modal__dialog" role="dialog" aria-modal="true" aria-labelledby="report-title">
    <h2 id="report-title">Report an issue</h2>
    <form id="report-form">
      <label for="report-type">Type</label>
      <select id="report-type">
        <option value="missing">Missing board</option>
        <option value="problem">Not working properly</option>
        <option value="other">Other</option>
      </select>
      <div class="form-row">
        <div>
          <label for="report-vendor">Vendor</label>
          <input id="report-vendor" type="text" placeholder="MSI / ASUS / GIGABYTE / ASRock" />
        </div>
        <div>
          <label for="report-model">Model</label>
          <input id="report-model" type="text" placeholder="e.g., PRO Z790-P WIFI" />
        </div>
      </div>
      <label for="report-details">Details</label>
      <textarea id="report-details" rows="6" placeholder="Describe what's missing or what's wrong…"></textarea>
      <div class="modal__actions">
        <button type="button" id="report-cancel" class="button button--secondary">Cancel</button>
        <button type="submit" id="report-submit" class="button">Submit</button>
      </div>
    </form>
  </div>
</div>
"""

    # Assemble page
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
  </div>
  {filter_and_report_js}
  {modal_html}
</body>
</html>
"""

    idx.write_text(page_html, encoding="utf-8")
    data_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Done. Wrote docs/index.html and docs/data.json")

if __name__ == "__main__":
    main()
