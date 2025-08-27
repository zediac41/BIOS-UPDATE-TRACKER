from flask import Flask, render_template, request
import sqlite3
import json
import requests
from datetime import datetime
import os

app = Flask(__name__)

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('bios_updates.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS bios_updates
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  motherboard TEXT,
                  vendor TEXT,
                  version TEXT,
                  release_date TEXT,
                  download_link TEXT)''')
    conn.commit()
    conn.close()

# Fetch data from GitHub repository
def fetch_bios_data():
    # Replace with your GitHub repository details
    GITHUB_REPO = "your_username/your_bios_repo"
    GITHUB_FILE = "bios_data.json"
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Store token in environment variable
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        content = response.json()
        bios_data = json.loads(base64.b64decode(content['content']).decode('utf-8'))
        return bios_data
    except Exception as e:
        print(f"Error fetching data from GitHub: {e}")
        return []

# Populate database with BIOS data
def populate_db():
    bios_data = fetch_bios_data()
    conn = sqlite3.connect('bios_updates.db')
    c = conn.cursor()
    
    # Clear existing data
    c.execute("DELETE FROM bios_updates")
    
    # Insert new data
    for entry in bios_data:
        motherboard = entry.get('motherboard')
        vendor = entry.get('vendor')
        for version_info in entry.get('versions', [])[:2]:  # Get last two versions
            c.execute('''INSERT INTO bios_updates (motherboard, vendor, version, release_date, download_link)
                        VALUES (?, ?, ?, ?, ?)''',
                     (motherboard, vendor, version_info.get('version'),
                      version_info.get('release_date'), version_info.get('download_link')))
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = sqlite3.connect('bios_updates.db')
    c = conn.cursor()
    
    # Get search and sort parameters
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort', 'release_date')
    sort_order = request.args.get('order', 'desc')
    
    # Build SQL query
    query = "SELECT * FROM bios_updates WHERE motherboard LIKE ? OR vendor LIKE ?"
    params = (f'%{search_query}%', f'%{search_query}%')
    
    if sort_by in ['motherboard', 'vendor', 'release_date']:
        query += f" ORDER BY {sort_by} {sort_order.upper()}"
    
    c.execute(query, params)
    bios_updates = c.fetchall()
    conn.close()
    
    # Group updates by motherboard
    grouped_updates = {}
    for update in bios_updates:
        motherboard = update[1]
        if motherboard not in grouped_updates:
            grouped_updates[motherboard] = {
                'vendor': update[2],
                'versions': []
            }
        grouped_updates[motherboard]['versions'].append({
            'version': update[3],
            'release_date': update[4],
            'download_link': update[5]
        })
    
    return render_template('index.html', updates=grouped_updates)

if __name__ == '__main__':
    init_db()
    populate_db()
    app.run(debug=True)