import requests
from bs4 import BeautifulSoup
import json
import os

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

def get_models():
    url = "https://www.gigabyte.com/Motherboard/All-Series"
    resp = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(resp.text, 'lxml')
    models = []
    for link in soup.find_all('a', class_='product-link'):  # Adjust class based on site inspection
        model_name = link.text.strip()
        model_url = "https://www.gigabyte.com" + link['href'] + "/support#support-dl-bios"
        models.append({"name": model_name, "url": model_url})
    return models

def scrape_bios_for_model(url):
    resp = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(resp.text, 'lxml')
    bios_list = []
    for row in soup.find_all('div', class_='div-table-row'):  # Target BIOS table rows
        cells = row.find_all('div', class_='div-table-cell')
        if len(cells) >= 3:
            version = cells[0].text.strip()
            date = cells[1].text.strip()  # Assuming date in second cell
            link = cells[2].find('a')['href'] if cells[2].find('a') else ''
            if version.startswith('F'):  # Filter BIOS versions
                bios_list.append({"version": version, "date": date, "link": link})
    # Sort by date descending (assuming YYYY-MM-DD format)
    bios_list.sort(key=lambda x: x['date'], reverse=True)
    return bios_list

def main():
    data_file = '../data/gigabyte_bios.json'
    if os.path.exists(data_file):
        with open(data_file, 'r') as f:
            existing_data = json.load(f)
    else:
        existing_data = {"models": []}

    models = get_models()
    updated = False
    new_data = {"models": []}
    for model in models[:10]:  # Limit to 10 for testing; remove for full
        bios_versions = scrape_bios_for_model(model['url'])
        # Check if new
        old_model = next((m for m in existing_data['models'] if m['name'] == model['name']), None)
        if not old_model or bios_versions[0] != old_model['bios_versions'][0]:
            updated = True
        new_data['models'].append({"name": model['name'], "bios_versions": bios_versions})

    if updated:
        with open(data_file, 'w') as f:
            json.dump(new_data, f, indent=4)
        print("Gigabyte data updated.")

if __name__ == "__main__":
    main()
