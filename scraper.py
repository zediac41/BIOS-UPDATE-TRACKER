import json
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

# ASUS motherboard BIOS URLs
motherboards = {
    "TUF GAMING Z890-PLUS WIFI": "https://www.asus.com/us/motherboards-components/motherboards/tuf-gaming/tuf-gaming-z890-plus-wifi/helpdesk_bios",
    "ROG STRIX Z790-E GAMING WIFI": "https://www.asus.com/us/motherboards-components/motherboards/rog-strix/rog-strix-z790-e-gaming-wifi/helpdesk_bios",
}

# Initialize Playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    bios_data = []

    for model, url in motherboards.items():
        page.goto(url)
        page.wait_for_selector("div.ProductSupportDriverBIOS__contentLeft__3F4tG")

        # Extract the latest BIOS version and release date
        latest_version = page.query_selector("div.ProductSupportDriverBIOS__contentLeft__3F4tG div.ProductSupportDriverBIOS__fileInfo__2c5GN > div")
        release_date = page.query_selector("div.ProductSupportDriverBIOS__contentLeft__3F4tG div.ProductSupportDriverBIOS__releaseDate__3o309")

        latest_version = latest_version.inner_text().replace("Version", "").strip() if latest_version else "N/A"
        release_date = release_date.inner_text().replace("/", "-") if release_date else "N/A"

        # Get the previous version and release date from bios.json if available
        try:
            with open("bios.json", "r") as f:
                old_data = {item["model"]: item for item in json.load(f)}
        except FileNotFoundError:
            old_data = {}

        previous_version = old_data.get(model, {}).get("latest_version", "N/A")
        previous_release_date = old_data.get(model, {}).get("release_date", "N/A")

        # Get the current time in Central Time
        central_time = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M %Z")

        bios_data.append({
            "model": model,
            "latest_version": latest_version,
            "release_date": release_date,
            "previous_version": previous_version,
            "previous_release_date": previous_release_date,
            "last_checked": central_time
        })

    browser.close()

# Sort the data by release date, newest first
bios_data.sort(key=lambda x: datetime.strptime(x["release_date"], "%Y-%m-%d") if x["release_date"] != "N/A" else datetime.min, reverse=True)

# Save the data to bios.json
with open("bios.json", "w") as f:
    json.dump(bios_data, f, indent=2)



