# BIOS Tracker

A GitHub-Action-powered Python tracker that checks motherboard BIOS pages (ASUS, MSI, Gigabyte, ASRock) and notifies you when a **new BIOS version** is released for your specific boards.

- Runs daily (or on a schedule you set) in GitHub Actions.
- Stores last-seen versions in `state/db.json` (committed to the repo by the Action so history is preserved).
- Sends notifications to **Discord/Slack (incoming webhook)** when a new version is detected.
- Extensible vendor parsers — add your own or supply CSS selectors in `config.yml` if needed.

> ⚠️ Vendor websites change often. This works out-of-the-box for many common layouts, but you may need to tweak CSS selectors in `config.yml` per board page. The code has fallbacks that try to parse versions/dates heuristically.

## Quick Start

1. **Create a new GitHub repo** and upload this folder.
2. **Set repository secrets** (Settings → Secrets and variables → Actions → New repository secret):
   - `WEBHOOK_URL` (optional but recommended): Discord/Slack incoming webhook URL
   - `GIT_AUTHOR_NAME` (optional): Name for commits from the Action (default: `bios-tracker-bot`)
   - `GIT_AUTHOR_EMAIL` (optional): Email for commits (default: `bot@example.com`)
3. (Optional) Edit schedule in [`.github/workflows/schedule.yml`](.github/workflows/schedule.yml).
4. Edit `config.yml` to list your exact boards (examples included).
5. Push. The Action will run on schedule and on each push. When a new BIOS is found, it posts to the webhook and updates `state/db.json`.

## Configuration (`config.yml`)

```yaml
boards:
  - name: "ROG STRIX B550-F (Wi-Fi)"
    vendor: "asus"
    url: "https://www.asus.com/supportonly/rog-strix-b550-f-gaming-wi-fi/helpdesk_bios/"
    selectors: {}

  - name: "MSI MAG B550 TOMAHAWK"
    vendor: "msi"
    url: "https://www.msi.com/Motherboard/MAG-B550-TOMAHAWK/support"
    selectors: {}

  - name: "Gigabyte X570 AORUS ELITE"
    vendor: "gigabyte"
    url: "https://www.gigabyte.com/Motherboard/X570-AORUS-ELITE-rev-10/support#support-dl-bios"
    selectors: {}

  - name: "ASRock B650M Pro RS"
    vendor: "asrock"
    url: "https://www.asrock.com/mb/AMD/B650M%20Pro%20RS/index.asp#BIOS"
    selectors: {}
```

## Notifications

- **Discord/Slack**: Set `WEBHOOK_URL` secret — the script posts JSON payloads to it when a new version is found.
- **GitHub commits**: The Action commits changes to `state/db.json` to keep a history of discovered versions.

## Local Run

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python src/main.py --config config.yml --verbose
```

## Add more boards/vendors

- Add entries in `config.yml`.
- If a vendor page changes, try adding CSS selectors in the config first.
- To add a new vendor parser, create a new file in `src/vendors/` that exposes `parse(url, html, selectors=None)`
  returning `{"version": "...", "date": "YYYY-MM-DD", "title": "...", "url": url}`.

---

MIT License.
