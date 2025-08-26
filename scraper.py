import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

# ASUS motherboards and BIOS pages
motherboards = {
    "TUF GAMING Z890-PLUS WIFI": "https://www.asus.com/us/motherboards-components/motherboards/tuf-gaming/tuf-gaming-z890-plus-wifi/helpdesk_bios",
    "ROG STRIX Z790-E GAMING WIFI": "https://www.asus.com/us/motherboards-components/motherboards/rog-strix/rog-strix-z790-e-gaming-wifi/helpdesk_bios",
}

# Load existing data
try:
    with open("bios.json", "r") as f:
        old_data = {item["model"]: item for item in json.load(f)}
except FileNotFoundError:
    old_data = {}

bios_data = []

for model, url in motherboards.items():
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # ---- Extract version and release date ----
        latest_version = "N/A"
        release_date = "N/A"

        # Find all BIOS entries
        entries = soup.select("div.ProductSupportDriverBIOS__contentLeft__3F4tG")
        if entries:
            first_entry = entries[0]  # newest BIOS

            # Version
            version_div = first_entry.select_one("div.ProductSupportDriverBIOS__fileInfo__2c5GN > div")
            if version_div:
                latest_version = version_div.get_text(strip=True).replace("Version", "").strip()

            # Release date
            release_div = first_entry.select_one("div.ProductSupportDriverBIOS__releaseDate__3o309")
            if release_div:
                release_date = release_div.get_text(strip=True).replace("/", "-")  # YYYY-MM-DD format

        # ---- Previous version tracking ----
        previous_version = old_data.get(model, {}).get("latest_version", "")
        previous_release_date = old_data.get(model, {}).get("release_date", "")

        if previous_version == latest_version:
            previous_version = old_data.get(model, {}).get("previous_version", "")
            previous_release_date = old_data.get(model, {}).get("previous_release_date", "")

        # ---- Central Time ----
        central_time = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M %Z")

        bios_data.append({
            "model": model,
            "latest_version": latest_version,
            "release_date": release_date,
            "previous_version": previous_version,
            "previous_release_date": previous_release_date,
            "last_checked": central_time
        })

    except Exception as e:
        bios_data.append({
            "model": model,
            "latest_version": "ERROR",
            "release_date": str(e),
            "previous_version": "",
            "previous_release_date": "",
            "last_checked": datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M %Z")
        })

# ---- Sort by newest release date first ----
def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return datetime.min

bios_data.sort(key=lambda x: parse_date(x["release_date"]), reverse=True)

# ---- Save to bios.json ----
with open("bios.json", "w") as f:
    json.dump(bios_data, f, indent=2)


