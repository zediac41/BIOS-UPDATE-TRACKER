import requests
from bs4 import BeautifulSoup
import json
import yaml
import time

# Load configuration
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

bios_data = {}

def scrape_asus(model):
    try:
        url = f"https://www.asus.com/supportonly/{model.replace(' ', '%20')}/HelpDesk_BIOS/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        versions = []
        # Adjust selectors based on ASUS site (approximate)
        for row in soup.select('table tr')[1:6]:  # Latest 5 versions
            cells = row.find_all('td')
            if len(cells) >= 3:
                version = cells[0].text.strip()
                date = cells[2].text.strip()
                versions.append({'version': version, 'date': date})
        return versions
    except Exception as e:
        print(f"Error scraping ASUS {model}: {e}")
        return []

def scrape_msi(model):
    try:
        url = f"https://www.msi.com/Motherboard/{model.replace(' ', '-')}/Support"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        versions = []
        # Adjust selectors for MSI (approximate)
        bios_section = soup.find('div', id='bios')
        if bios_section:
            for item in bios_section.find_all('li')[:5]:
                version = item.find('span', class_='version')
                date = item.find('span', class_='date')
                if version and date:
                    versions.append({'version': version.text.strip(), 'date': date.text.strip()})
        return versions
    except Exception as e:
        print(f"Error scraping MSI {model}: {e}")
        return []

def scrape_gigabyte(model):
    try:
        url = f"https://www.gigabyte.com/Motherboard/{model.replace(' ', '-')}/support#support-dl-bios"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        versions = []
        # Adjust selectors for Gigabyte (approximate)
        for row in soup.select('#bios-table tr')[1:6]:
            cells = row.find_all('td')
            if len(cells) >= 3:
                version = cells[0].text.strip()
                date = cells[2].text.strip()
                versions.append({'version': version, 'date': date})
        return versions
    except Exception as e:
        print(f"Error scraping Gigabyte {model}: {e}")
        return []

def scrape_asrock(model):
    try:
        url = f"https://www.asrock.com/mb/index.asp#BIOS?Model={model.replace(' ', '%20')}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        versions = []
        # Adjust selectors for ASRock (approximate)
        for row in soup.select('.download-table tr')[1:6]:
            cells = row.find_all('td')
            if len(cells) >= 3:
                version = cells[0].text.strip()
                date = cells[2].text.strip()
                versions.append({'version': version, 'date': date})
        return versions
    except Exception as e:
        print(f"Error scraping ASRock {model}: {e}")
        return []

# Scrape for each manufacturer
for manufacturer, models in config.items():
    bios_data[manufacturer] = {}
    for model in models:
        if manufacturer == 'asus':
            bios_data[manufacturer][model] = scrape_asus(model)
        elif manufacturer == 'msi':
            bios_data[manufacturer][model] = scrape_msi(model)
        elif manufacturer == 'gigabyte':
            bios_data[manufacturer][model] = scrape_gigabyte(model)
        elif manufacturer == 'asrock':
            bios_data[manufacturer][model] = scrape_asrock(model)
        time.sleep(2)  # Avoid rate limiting

# Save data to JSON
with open('bios_data.json', 'w') as f:
    json.dump(bios_data, f, indent=4)

# Generate Markdown for GitHub Pages
md_content = "# BIOS Version Tracker\n\n"
for manufacturer, models in bios_data.items():
    md_content += f"## {manufacturer.upper()}\n\n"
    for model, versions in models.items():
        md_content += f"### {model}\n\n"
        if versions:
            md_content += "| Version | Release Date |\n|---------|--------------|\n"
            for v in versions:
                md_content += f"| {v['version']} | {v['date']} |\n"
        else:
            md_content += "No data found.\n\n"
with open('index.md', 'w') as f:
    f.write(md_content)

print("Scraping complete. Data updated.")
