import requests
from bs4 import BeautifulSoup
import yaml
from datetime import datetime

def fetch_html(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return ""

def parse_versions_asus(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for tag in soup.find_all(["td", "div", "span", "a"]):
        text = tag.get_text(strip=True)
        if text and ("BIOS" in text.upper() or text.replace(".", "").isdigit()):
            versions.append(text)
    return versions

def parse_versions_msi(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for tag in soup.find_all(["td", "div", "span", "a"]):
        text = tag.get_text(strip=True)
        if text and ("bios" in text.lower() or text.replace(".", "").isdigit()):
            versions.append(text)
    return versions

def parse_versions_gigabyte(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for tag in soup.find_all(["li", "td", "div", "span", "a"]):
        text = tag.get_text(strip=True)
        if text and ("bios" in text.lower() or text.replace(".", "").isdigit()):
            versions.append(text)
    return versions

def parse_versions_asrock(html):
    soup = BeautifulSoup(html, "html.parser")
    versions = []
    for tag in soup.find_all(["td", "div", "span", "a"]):
        text = tag.get_text(strip=True)
        if text and ("bios" in text.lower() or text.replace(".", "").isdigit()):
            versions.append(text)
    return versions

def get_latest_two(versions):
    unique = list(dict.fromkeys(versions))
    return unique[:2] if len(unique) >= 2 else unique

def main():
    config = yaml.safe_load(open("config.yml"))
    boards = config.get("boards", [])
    results = []

    for b in boards:
        vendor = b.get("vendor").lower()
        url = b.get("url")
        html = fetch_html(url)
        if not html:
            continue

        if vendor == "asus":
            versions = parse_versions_asus(html)
        elif vendor == "msi":
            versions = parse_versions_msi(html)
        elif vendor == "gigabyte":
            versions = parse_versions_gigabyte(html)
        elif vendor == "asrock":
            versions = parse_versions_asrock(html)
        else:
            versions = []

        latest_two = get_latest_two(versions)
        results.append({
            "name": b.get("name"),
            "vendor": vendor,
            "url": url,
            "versions": latest_two
        })

    html_out = ["<h1>Motherboard BIOS Tracker</h1>"]
    html_out.append("<table border='1' cellpadding='6'>")
    html_out.append("<tr><th>Board</th><th>Current</th><th>Previous</th><th>Vendor</th></tr>")

    for r in results:
        cur = r["versions"][0] if len(r["versions"]) > 0 else "N/A"
        prev = r["versions"][1] if len(r["versions"]) > 1 else "N/A"
        html_out.append(f"<tr><td>{r['name']}</td><td>{cur}</td><td>{prev}</td><td>{r['vendor']}</td></tr>")

    html_out.append("</table>")
    html_out.append(f"<p>Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write("\n".join(html_out))

if __name__ == "__main__":
    main()
