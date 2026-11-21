"""Static, sourced lane-sharing records and the board-details dialog."""

import datetime
import html
from pathlib import Path
from urllib.parse import urlsplit

import yaml


def board_key(vendor, model):
    return str(vendor).strip().upper(), " ".join(str(model).split()).casefold()


def load_catalog(path, config):
    path = Path(path)
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if payload.get("schema_version") != 1:
        raise ValueError("lane_sharing.yml: expected schema_version: 1")
    configured = {
        board_key(vendor, item.get("name") or item.get("model") if isinstance(item, dict) else item)
        for vendor, items in (config.get("vendors") or {}).items()
        for item in (items or [])
    }
    catalog = {}
    for record in payload.get("boards", []):
        key = board_key(record.get("vendor", ""), record.get("model", ""))
        label = f"lane_sharing.yml: {record.get('model', 'unnamed board')}"
        if key not in configured or key in catalog:
            raise ValueError(f"{label}: board is unknown or duplicated")
        if record.get("status") not in {"verified", "pending", "no_sharing_documented"}:
            raise ValueError(f"{label}: invalid research status")
        if record["status"] != "pending":
            for field in ("reviewed_on", "revision", "baseline", "gpu_summary", "sources", "slots"):
                if not record.get(field):
                    raise ValueError(f"{label}: missing {field}")
            datetime.date.fromisoformat(str(record["reviewed_on"]))
        source_ids = set()
        for source in record.get("sources", []):
            parsed = urlsplit(source.get("url", ""))
            if (not source.get("id") or source["id"] in source_ids
                    or parsed.scheme != "https" or not parsed.netloc
                    or not source.get("title") or not source.get("section")):
                raise ValueError(f"{label}: invalid or duplicate source")
            source_ids.add(source["id"])
        slot_names = set()
        required = {
            "slots": ("name", "connection", "speed", "note"),
            "rules": ("trigger", "affects", "result", "condition"),
            "cpu_notes": ("text",),
        }
        for group, fields in required.items():
            for item in record.get(group, []):
                if any(not item.get(field) for field in fields):
                    raise ValueError(f"{label}: incomplete {group} entry")
                refs = item.get("sources", [])
                if not refs or any(ref not in source_ids for ref in refs):
                    raise ValueError(f"{label}: missing or unknown source reference in {group}")
                if group == "slots":
                    if item["name"] in slot_names:
                        raise ValueError(f"{label}: duplicate slot {item['name']}")
                    slot_names.add(item["name"])
        catalog[key] = record
    return catalog


def render_details(entry, record):
    esc = lambda value: html.escape(str(value or ""), quote=True)
    if not record or record.get("status") == "pending":
        return (
            '<p class="lane-pending">Lane-sharing research pending.</p>'
            '<p>This board has not been verified yet. Slot conflicts are unknown.</p>'
        )
    source_numbers = {source["id"]: index for index, source in enumerate(record["sources"], 1)}
    sources = {source["id"]: source for source in record["sources"]}

    def refs(item):
        return ' <span class="lane-refs">' + " ".join(
            f'<a href="{esc(sources[ref]["url"])}" target="_blank" rel="noreferrer" '
            f'aria-label="Source {source_numbers[ref]}: {esc(sources[ref]["title"])}">'
            f'[{source_numbers[ref]}]</a>'
            for ref in item["sources"]
        ) + "</span>"

    rows = "".join(
        '<tr>'
        f'<th scope="row">{esc(slot["name"])}</th>'
        f'<td data-label="Connection">{esc(slot["connection"])}</td>'
        f'<td data-label="Maximum link">{esc(slot["speed"])}</td>'
        f'<td data-label="Sharing">{esc(slot["note"])}{refs(slot)}</td>'
        '</tr>' for slot in record["slots"]
    )
    rules = "".join(
        '<li>'
        f'<h4>{esc(rule["trigger"])}</h4>'
        f'<p><strong>{esc(rule["affects"])}</strong>: {esc(rule["result"])}{refs(rule)}</p>'
        f'<p class="lane-condition">{esc(rule["condition"])}</p>'
        '</li>' for rule in record.get("rules", [])
    )
    cpu_notes = "".join(
        f'<li>{esc(note["text"])}{refs(note)}</li>' for note in record.get("cpu_notes", [])
    )
    source_list = "".join(
        f'<li><a href="{esc(source["url"])}" target="_blank" rel="noreferrer">'
        f'{esc(source["title"])}</a><p>{esc(source["section"])}</p></li>'
        for source in record["sources"]
    )
    return (
        f'<p class="lane-scope">{esc(record["revision"])}<br>'
        f'<span>Reviewed {esc(record["reviewed_on"])}</span></p>'
        f'<section class="lane-gpu"><h3>Main GPU slot</h3><p>{esc(record["gpu_summary"])}</p></section>'
        f'<p class="lane-baseline">{esc(record["baseline"])}</p>'
        '<section class="lane-section"><h3>M.2 slots</h3>'
        '<table class="lane-slots"><thead><tr><th>Slot</th><th>Connection</th>'
        f'<th>Maximum link</th><th>Sharing</th></tr></thead><tbody>{rows}</tbody></table></section>'
        '<section class="lane-section"><h3>What changes</h3>'
        + (f'<ul class="lane-rules">{rules}</ul>' if rules else '<p>No sharing documented in the reviewed sources.</p>')
        + '</section>'
        + (f'<section class="lane-section"><h3>CPU restrictions</h3><ul>{cpu_notes}</ul></section>' if cpu_notes else '')
        + '<section class="lane-section lane-sources"><h3>Official sources</h3>'
        f'<ol>{source_list}</ol></section>'
    )


def render_dialog(results, catalog):
    templates = []
    for index, entry in enumerate(results):
        record = catalog.get(board_key(entry.get("vendor"), entry.get("model")))
        templates.append(f'<template id="lane-{index}">{render_details(entry, record)}</template>')
    return "\n".join(templates) + """
<dialog id="lane-dialog" aria-labelledby="lane-title">
  <header class="lane-header">
    <div><p class="lane-eyebrow">M.2 &amp; PCIe lane sharing</p><h2 id="lane-title"></h2></div>
    <button type="button" id="lane-close" aria-label="Close board details" title="Close">&times;</button>
  </header>
  <div id="lane-body" class="lane-body"></div>
  <footer class="lane-footer"><a id="lane-vendor" target="_blank" rel="noreferrer">Vendor BIOS page</a></footer>
</dialog>
"""


STYLES = """
<style>
.card[data-lane-template]{cursor:pointer;position:relative}
.card[data-lane-template]:hover{background:#19203d}
.card h3{align-items:flex-start;overflow-wrap:anywhere}
.card h3 .badge{flex-shrink:0;white-space:nowrap}
.lane-open{font:inherit;font-weight:700;text-align:left;color:inherit;border:0;background:none;padding:0;min-width:0;cursor:pointer;line-height:inherit}
.lane-open:hover{text-decoration:underline;text-underline-offset:3px}
.lane-open:focus-visible{outline:2px solid #93d4c0;outline-offset:5px;border-radius:2px}
.card .lane-status{font-size:12px;margin:10px 0 0;color:#b7c0d1}
.card .lane-status--verified{color:#96dfc8}
#lane-dialog{width:min(920px,calc(100% - 24px));max-width:none;max-height:90dvh;padding:0;border:1px solid #48545c;border-radius:8px;background:#161d23;color:#edf1f3;overflow:auto;box-shadow:0 20px 70px #0008}
#lane-dialog::backdrop{background:#03080cc4}
body:has(#lane-dialog[open]){overflow:hidden}
.lane-header{position:sticky;top:0;z-index:1;display:flex;align-items:flex-start;gap:20px;padding:22px 24px 18px;background:#161d23;border-bottom:1px solid #39444e}
.lane-header>div{min-width:0;flex:1}
.lane-eyebrow{font-size:12px;color:#96dfc8;margin:0 0 7px}
.lane-header h2{font-size:22px;line-height:1.3;overflow-wrap:anywhere;margin:0}
#lane-close{flex:0 0 36px;width:36px;height:36px;border:1px solid #48545c;border-radius:4px;font-size:27px;background:#222d35;color:#fff;cursor:pointer;line-height:1}
#lane-close:hover{background:#35434d}
#lane-dialog :focus-visible{outline:2px solid #96dfc8;outline-offset:3px}
.lane-body{padding:0 24px 24px;font-size:14px;line-height:1.55;overflow-wrap:anywhere}
.lane-body h3{font-size:16px;margin:0 0 12px;color:#f2f6f7}
.lane-body p{margin:0 0 10px}
.lane-scope{padding-top:18px;color:#c2cbd0;font-size:12px}
.lane-scope span{color:#a4b0b9}
.lane-gpu{padding:14px 0 14px 14px;margin:20px 0 12px;border-left:3px solid #e2ae68}
.lane-gpu h3{margin-bottom:6px}.lane-gpu p{margin:0}
.lane-baseline{color:#b9c5cc;font-size:12px}
.lane-section{border-top:1px solid #39444e;margin-top:24px;padding-top:20px}
.lane-slots{width:100%;border-collapse:collapse;table-layout:fixed;font-size:13px}
.lane-slots th,.lane-slots td{text-align:left;vertical-align:top;padding:12px 10px;border-bottom:1px solid #323e47}
.lane-slots thead th{font-weight:500;color:#a9bac4;padding-top:0}
.lane-slots th:first-child{width:14%;padding-left:0}.lane-slots th:nth-child(2){width:13%}.lane-slots th:nth-child(3){width:23%}
.lane-slots tbody th{color:#96dfc8;font-weight:600}
.lane-body a,.lane-footer a{color:#a5d1ed;text-underline-offset:3px}
.lane-refs{font-size:11px;white-space:nowrap}.lane-refs a{text-decoration:none}
.lane-rules{padding:0;list-style:none;margin:0}
.lane-rules>li{margin:0 0 20px;padding:0 0 18px;border-bottom:1px solid #323e47}
.lane-rules>li:last-child{margin-bottom:0;border:0;padding-bottom:0}
.lane-rules h4{font-size:14px;color:#f1d09e;margin:0 0 8px}
.lane-rules p:last-child{margin-bottom:0}.lane-condition{font-size:12px;color:#aebcc6}
.lane-section ul:not(.lane-rules){padding-left:20px}.lane-section li+li{margin-top:10px}
.lane-sources{font-size:12px}.lane-sources ol{padding-left:20px;margin-bottom:0}
.lane-sources p{color:#aebcc6;font-size:12px;margin-top:4px}
.lane-footer{padding:15px 24px;border-top:1px solid #39444e;font-size:13px}
.lane-pending{font-weight:600;color:#f1d09e;padding-top:24px}
@media(max-width:620px){
  .lane-header{padding:16px;gap:12px}.lane-header h2{font-size:18px}
  .lane-body{padding:0 16px 20px}.lane-footer{padding:15px 16px}
  .lane-slots thead{display:none}.lane-slots,.lane-slots tbody,.lane-slots tr{display:block;width:100%}
  .lane-slots tr{padding:12px 0;border-bottom:1px solid #39444e}
  .lane-slots th:first-child{display:block;width:100%;padding:0 0 7px;border:0}
  .lane-slots td{display:grid;grid-template-columns:96px minmax(0,1fr);gap:8px;padding:3px 0;border:0}
  .lane-slots td::before{content:attr(data-label);color:#a9bac4;font-size:12px}
  .lane-slots td .lane-refs{grid-column:2}
}
</style>
"""


SCRIPT = """
<script>
document.addEventListener('DOMContentLoaded', () => {
  const dialog = document.getElementById('lane-dialog');
  const close = document.getElementById('lane-close');
  let returnFocus = null;
  document.querySelectorAll('.card[data-lane-template]').forEach(card => {
    const button = card.querySelector('.lane-open');
    function openDetails() {
      const template = document.getElementById(card.dataset.laneTemplate);
      if (!template) return;
      returnFocus = button;
      document.getElementById('lane-title').textContent = button.textContent.trim();
      document.getElementById('lane-body').replaceChildren(template.content.cloneNode(true));
      const link = card.querySelector('.meta a');
      const vendor = document.getElementById('lane-vendor');
      vendor.hidden = !link;
      if (link) vendor.href = link.href;
      dialog.showModal();
      dialog.scrollTop = 0;
      close.focus();
    }
    button.addEventListener('click', openDetails);
    card.addEventListener('click', event => {
      if (event.target.closest('a,button,summary,details,input,select,textarea')) return;
      if (window.getSelection()?.toString()) return;
      openDetails();
    });
  });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right ||
        event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => returnFocus?.focus({preventScroll:true}));
});
</script>
"""
