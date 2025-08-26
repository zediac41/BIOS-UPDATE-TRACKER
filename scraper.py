import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

# Add your ASUS motherboards and their BIOS pages here
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

        # Grab BIOS version & release date (adjust selectors if needed)
        version_tag = soup.select_one(".Version")
        release_tag = soup.select_one(".ReleaseDate")
        latest_version = version_tag.get_text(strip=True) if version_tag else "N/A"
        release_date = release_tag.get_text(strip=True) if release_tag else "N/A"

        # Track previous version
        previous_version = old_data.get(model, {}).get("latest_version", "")
        previous_release_date = old_data.get(model, {}).get("release_date", "")

        if previous_version == latest_version:
            previous_version = old_data.get(model, {}).get("previous_version", "")
            previous_release_date = old_data.get(model, {}).get("previous_release_date", "")

        # Central Time for last_checked
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

# Function to parse release dates for sorting
def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return datetime.min  # invalid/missing dates go to bottom

# Sort by newest release first
bios_data.sort(key=lambda x: parse_date(x["release_date"]), reverse=True)

# Save updated JSON
with open("bios.json", "w") as f:
    json.dump(bios_data, f, indent=2)


