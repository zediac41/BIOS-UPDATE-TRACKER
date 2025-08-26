import requests
from bs4 import BeautifulSoup
import yaml
from datetime import datetime
import os

def fetch_html(url):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return ""

def parse_generic(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for tag in soup.find_all(["li","td","div","span","a"]):
        text = tag.get_text(strip=True)
        if not text: 
            continue
        t = text.lower()
        if "bios" in t or t.replace(".", "").replace("-", "").replace("v", "").isalnum():
            versions.append(text)
    return versions

def parse_versions(vendor, html):
    # simple vendor switch if you later want vendor-specific tweaks
    return parse_generic(html)

def get_latest_two(versions):
    unique = list(dict.fromkeys(versions))
    return unique[:2] if len(unique) >= 2 else unique

def main():
    cfg = yaml.safe_load(open("config.yml", "r", encoding="utf-8"))
    boards = cfg.get("boards", [])
    results = []

    for b in boards:
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

    # Styled HTML + search/filter
    html_out = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>BIOS Tracker</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; background: #f9fafb; color: #111; padding: 20px; }",
        "h1 { text-align: center; color: #2c3e50; }",
        ".controls { max-width: 1000px; margin: 0 auto; display: flex; gap: 10px; justify-content: center; align-items: center; flex-wrap: wrap; }",
        "#searchBar { flex: 1 1 420px; padding: 10px; font-size: 16px; border: 1px solid #ccc; border-radius: 6px;}",
        "#vendorFilter { padding: 10px; font-size: 16px; border: 1px solid #ccc; border-radius: 6px;}",
        "table { border-collapse: collapse; margin: 20px auto; width: 95%; max-width: 1000px; background: #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.1);}",
        "th, td { border: 1px solid #ddd; padding: 12px; text-align: center; }",
        "th { background: #2c3e50; color: #fff; }",
        "tr:nth-child(even) { background: #f2f2f2; }",
        "tr:hover { background: #eaf2f8; }",
        "p { text-align: center; margin-top: 20px; font-size: 14px; color: #555; }",
        "a { color: #2980b9; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
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
        "</div>",
        "<table id='biosTable'><tr><th>Board</th><th>Current</th><th>Previous</th><th>Vendor</th><th>Support Page</th></tr>"
    ]

    for r in results:
        cur = r["versions"][0] if len(r["versions"]) > 0 else "N/A"
        prev = r["versions"][1] if len(r["versions"]) > 1 else "N/A"
        html_out.append(f"<tr><td>{r['name']}</td><td>{cur}</td><td>{prev}</td><td>{r['vendor']}</td><td><a href='{r['url']}'>Link</a></td></tr>")

    html_out.append("</table>")
    html_out.append(f"<p>Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>")
    html_out.append("</body></html>")

    os.makedirs("public", exist_ok=True)
    with open(os.path.join("public","index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(html_out))

if __name__ == "__main__":
    main()
