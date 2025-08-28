import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# Load motherboard list from JSON
with open('motherboards.json', 'r') as f:
    motherboards = json.load(f)

data = []

# Set up headless Selenium
options = Options()
options.headless = True
options.add_argument("--window-size=1920,1200")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

for mb in motherboards:
    brand = mb['brand'].lower()
    model = mb['model']
    url = mb['support_url']
    
    driver.get(url)
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    version = None
    date = None
    link = None
    
    if brand == 'asus':
        # ASUS: Typically a list of divs; assume class 'download-list-item' or similar. Adjust if needed.
        # Find first entry (latest), parse version/date from text patterns.
        items = soup.find_all('div', class_='download-list-item')  # Adjust class based on inspection
        if items:
            latest = items[0]
            version_text = latest.find('h4') or latest.find('span', class_='version')  # Adjust
            version = version_text.text.strip() if version_text else 'Unknown'
            date_text = latest.find('p', class_='date') or latest.find(text=lambda t: '/' in t and len(t.split('/')) == 3)
            date_str = date_text.text.strip() if date_text else 'Unknown'
            try:
                date = datetime.strptime(date_str, '%Y/%m/%d')
            except:
                date = None
            link_elem = latest.find('a', href=True)
            link = link_elem['href'] if link_elem else 'No link'

    elif brand == 'msi':
        # MSI: Often a tabbed section or table loaded via JS. Assume table with class 'table-download' or similar.
        # Click tab if needed (e.g., driver.find_element_by_id('bios-tab').click()), but assuming direct URL loads it.
        table = soup.find('table', class_='table')  # Adjust class
        if table:
            rows = table.find_all('tr')
            if rows:
                latest = rows[1]  # Skip header
                tds = latest.find_all('td')
                version = tds[0].text.strip() if len(tds) > 0 else 'Unknown'
                date_str = tds[2].text.strip() if len(tds) > 2 else 'Unknown'  # Assume column order: version, size, date, etc.
                try:
                    date = datetime.strptime(date_str, '%Y-%m-%d')  # MSI often uses YYYY-MM-DD
                except:
                    date = None
                link = tds[-1].find('a')['href'] if tds[-1].find('a') else 'No link'

    elif brand == 'gigabyte':
        # Gigabyte: Table structure as per example.
        table = soup.find('table', class_='download-table')
        if table:
            tbody = table.find('tbody')
            rows = tbody.find_all('tr', class_='download-entry')
            if rows:
                latest = rows[0]
                version = latest.find('td', class_='version').text.strip()
                date_str = latest.find('td', class_='date').text.strip()
                try:
                    date = datetime.strptime(date_str, '%b %d, %Y')
                except:
                    date = None
                link = latest.find('td', class_='download').find('a')['href']

    elif brand == 'asrock':
        # ASRock: Typically a table with th/td for version, date, size, desc, download.
        table = soup.find('table', id='bios_table')  # Adjust ID/class based on inspection
        if table:
            rows = table.find_all('tr')
            if rows:
                latest = rows[1]  # Skip header
                tds = latest.find_all('td')
                version = tds[0].text.strip() if len(tds) > 0 else 'Unknown'
                date_str = tds[1].text.strip() if len(tds) > 1 else 'Unknown'  # Assume columns: version, date, size, desc, download
                try:
                    date = datetime.strptime(date_str, '%Y/%m/%d')  # Common format
                except:
                    date = None
                link = tds[-1].find('a')['href'] if tds[-1].find('a') else 'No link'
    
    data.append({
        'brand': brand.capitalize(),
        'model': model,
        'version': version or 'Not found',
        'date': date.strftime('%Y-%m-%d') if date else 'Unknown',
        'link': link or 'No link'
    })

driver.quit()

# Generate HTML with DataTables for search/sort/highlight
html = """
<!DOCTYPE html>
<html>
<head>
    <title>Motherboard BIOS Tracker</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.10.25/css/jquery.dataTables.css">
    <style>
        tr.highlight td { background-color: yellow; }
    </style>
</head>
<body>
    <table id="biosTable" class="display">
        <thead>
            <tr>
                <th>Brand</th>
                <th>Model</th>
                <th>Version</th>
                <th>Date</th>
                <th>Link</th>
            </tr>
        </thead>
        <tbody>
"""

for entry in data:
    html += f"""
            <tr>
                <td>{entry['brand']}</td>
                <td>{entry['model']}</td>
                <td>{entry['version']}</td>
                <td>{entry['date']}</td>
                <td><a href="{entry['link']}">Download</a></td>
            </tr>
    """

html += """
        </tbody>
    </table>

    <script src="https://code.jquery.com/jquery-3.5.1.js"></script>
    <script src="https://cdn.datatables.net/1.10.25/js/jquery.dataTables.min.js"></script>
    <script>
        $(document).ready(function() {
            $('#biosTable').DataTable({
                "rowCallback": function(row, data) {
                    var dateStr = data[3];
                    if (dateStr !== 'Unknown') {
                        var date = new Date(dateStr);
                        var now = new Date();
                        var sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                        if (date > sevenDaysAgo) {
                            $(row).addClass('highlight');
                        }
                    }
                }
            });
        });
    </script>
</body>
</html>
"""

with open('index.html', 'w') as f:
    f.write(html)

print("Scraping complete. Open index.html in your browser.")
