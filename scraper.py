import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

# List of motherboards + their BIOS page URLs
motherboards = {
    "TUF GAMING Z890-PLUS WIFI": "https://www.asus.com/us/motherboards-components/motherboards/tuf-gaming/tuf-gaming-z890-plus-wifi/helpdesk_bios",
    "ROG STRIX Z790-E GAMING WIFI": "https://www.asus.com/us/motherboards-components/motherboards/rog-strix/rog-strix-z790-e-gaming-wifi/helpdesk_bios",
}

bios_data = []

for model, url in motherboards.items():
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # Grab BIOS version & release date (selectors may need tweaks)
        version = soup.select_one(".Version").get_text(strip=True) if soup.select_one(".Version") else "N/A"
        release_date = soup.select_one(".ReleaseDate").get_text(strip=True) if soup.select_one(".ReleaseDate") else "N/A"

        bios_data.append({
            "model": model,
            "latest_version": version,
            "release_date": release_date,
            "last_checked": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        })
    except Exception as e:
        bios_data.append({
            "model": model,
            "latest_version": "ERROR",
            "release_date": str(e),
            "last_checked": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        })

# Save results to bios.json
with open("bios.json", "w") as f:
    json.dump(bios_data, f, indent=2)
