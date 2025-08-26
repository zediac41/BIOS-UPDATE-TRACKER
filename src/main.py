import requests
from bs4 import BeautifulSoup
import yaml
from datetime import datetime
import os
import sys
import traceback

def fetch_html(url):
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (BIOS-Tracker)"})
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[fetch_html] Error fetching {url}: {e}")
        return ""

def parse_generic(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for tag in soup.find_all(["li","td","div","span","a","p","strong"]):
        text = tag.get_text(strip=True)
        if not text:
            continue
        t = text.lower()
        if "bios" in t or t.replace(".", "").replace("-", "").replace("v", "").isalnum():
            versions.append(text)
    return versions

def parse_versions(vendor, html):
    return parse_generic(html)

def get_latest_two(versions):
    unique = list(dict.fromkeys(versions))
    return unique[:2] if len(unique) >= 2 else unique

def safe_load_config(path="config.yml"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[config] {path} not found in {os.getcwd()}")
        return {"_error": f"{path} not found"}
    except Exception as e:
        print(f"[config] Failed to read {path}: {e}")
        traceback.print_exc()
        return {"_error": f"Failed to read {path}: {e}"}

def build_html(results, notes=None):
    notes = notes or []
    html_out = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>BIOS Tracker</title>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>",
        "<style>",
        "body { font-family: Arial, sans-serif; background: #f9fafb; color: #111; padding: 20px; }",
        "h1 { text-align: center; color: #2c3e50; }",
        ".controls { max-width: 1100px; margin: 0 auto; display: flex; gap: 10px; justify-content: center; align-items: center; flex-wrap: wrap; }",
        "#searchBar { flex: 1 1 420px; padding: 10px; font-size: 16px; border: 1px solid #ccc; border-radius: 6px;}",
        "#vendorFilter { padding: 10px; font-size: 16px; border: 1px solid #ccc; border-radius: 6px;}",
        "table { border-collapse: collapse; margin: 20px auto; width: 95%; max-width: 1100px; background: #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.1);}",
        "th, td { border: 1px solid #ddd; padding: 12px; text-align: center; }",
        "th { background: #2c3e50; color: #fff; }",
        "tr:nth-child(even) { background: #f2f2f2; }",
        "tr:hover { background: #eaf2f8; }",
        "p { text-align: center; margin-top: 20px; font-size: 14px; color: #555; }",
        "a { color: #2980b9; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
        ".note { max-width: 1100px; margin: 0 auto; background: #fff3cd; border: 1px solid #ffeeba; color: #856404; padding: 10px 14px; border-radius: 6px; }",
        "</style>",
        "<script>",
        "function filterTable(){",
        "  var input = document.getElementById('searchBar').value.toUpperCase();",
        "  var vsel = document.getElementById('vendorFilter').value.toUpperCase();",
        "  var table = document.getElementById('biosTable');",
        "  var tr = table.getElementsByTagName('tr');",
        "  for (var i=1; i<tr.length; i++){",
        "    var tds = tr[i].getElementsByTagName('td');",
        "    if (tds.length < 5) continue;",
        "    var vendorText = tds[3].innerText.toUpperCase();",
        "    var rowText = (tds[0].innerText + ' ' + tds[1].innerText + ' ' + tds[2].innerText + ' ' + vendorText).toUpperCase();",
        "    var vendorMatch = (vsel === '' || vendorText === vsel);",
        "    var textMatch = (input === '' || rowText.indexOf(input) > -1);",
        "    tr[i].style.display = (vendorMatch && textMatch) ? '' : 'none';",
        "  }",
        "}",
        "</script>",
        "</head><body>",
        "<h1>Motherboard BIOS Tracker</h1>",
        "<div class='controls'>",
        "<input type='text' id='searchBar' onkeyup='filterTable()' placeholder='Search by board, vendor, or version...'>",
        "<select id='vendorFilter' onchange='filterTable()'>",
        "<option value=''>All Vendors</option>",
        "<option value='Asus'>Asus</option>",
        "<option value='Msi'>Msi</option>",
        "<option value='Gigabyte'>Gigabyte</option>",
        "<option value='Asrock'>Asrock</option>",
        "</select>",
        "</div>"
    ]

    if notes:
        html_out.append("<div class='note'><strong>Notes:</strong><ul>")
        for n in notes:
            html_out.append(f"<li>{n}</li>")
        html_out.append("</ul></div>")

    html_out.append("<table id='biosTable'><tr><th>Board</th><th>Current</th><th>Previous</th><th>Vendor</th><th>Support Page</th></tr>")
    for r in results:
        cur = r["versions"][0] if len(r["versions"]) > 0 else "N/A"
        prev = r["versions"][1] if len(r["versions"]) > 1 else "N/A"
        html_out.append(f"<tr><td>{r['name']}</td><td>{cur}</td><td>{prev}</td><td>{r['vendor']}</td><td><a href='{r['url']}'>Link</a></td></tr>")

    html_out.append("</table>")
    html_out.append(f"<p>Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>")
    html_out.append("</body></html>")
    return "\n".join(html_out)

def main():
    notes = []
    cfg = safe_load_config("config.yml")
    if "_error" in cfg:
        notes.append(cfg["_error"])

    boards = cfg.get("boards", [])
    results = []

    if not boards:
        notes.append("No boards configured in config.yml → showing empty table.")

    for b in boards:
        try:
            vendor = (b.get("vendor") or "").lower()
            url = b.get("url")
            html = fetch_html(url)
            if not html:
                latest_two = []
            else:
                versions = parse_versions(vendor, html)
                latest_two = get_latest_two(versions)
            results.append({
                "name": b.get("name"),
                "vendor": vendor.capitalize(),
                "url": url,
                "versions": latest_two
            })
        except Exception as e:
            print(f"[board] Error processing {b}: {e}")
            traceback.print_exc()
            notes.append(f"Error processing board '{b.get('name','(unknown)')}': {e}")

    html = build_html(results, notes=notes)
    os.makedirs("docs", exist_ok=True)
    with open(os.path.join("docs","index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("[write] Wrote docs/index.html")

if __name__ == "__main__":
    main()
