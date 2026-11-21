# Motherboard BIOS Tracker (ASUS / MSI / GIGABYTE / ASRock)

Fetch the latest **two** BIOS versions for selected motherboards and publish a static page via GitHub Pages.

Click a board tile to open its M.2 / PCIe lane-sharing details. The pilot covers
ROG STRIX X870E-E GAMING WIFI, MAG X870 TOMAHAWK WIFI, and X870 AORUS ELITE WIFI7 ICE
(PCB rev. 1.0/1.1). Other boards explicitly show research pending.

## Lane-sharing research

`lane_sharing.yml` stores reviewed hardware facts independently of daily BIOS
results. Each record identifies the exact model/revision, CPU assumptions, slots,
conditional conflicts, and official sources. Only add verified facts for that
exact model. A missing record means unknown, not that there is no lane sharing.
Review records when a model/revision or relevant vendor documentation changes.
The daily workflow reads this file locally and makes no research requests.

For a new board, research the exact model/revision first and add its verified
`lane_sharing.yml` record together with its `config.yml` entry. Asking the coding
agent to add a board includes this one-time research step; see `AGENTS.md`.
The `Check new board research` pull-request workflow flags newly added boards
without verified records. It only validates saved research and does not publish
the site. The build summary also lists any outstanding initial research.

Direct changes on main do not go through a pull-request check. Use the board
addition process above to ensure research is completed before its first scrape.

Rebuild the page from the existing `docs/data.json` without scraping:

```sh
python bios_tracker.py --render-only
```

Run the focused checks after installing `requirements.txt`:

```sh
python -m unittest discover -s tests
python -m playwright install chromium
python tests/check_lane_ui.py
```

- Output in `/docs/index.html`
- Driven by `config.yml` (models per vendor). Supports **explicit support URLs** per model.
- Runs on push and nightly via GitHub Actions
- Shows **current** and **previous** BIOS versions

## Quick Start
1. Upload files to a new GitHub repository.
2. In **Settings → Pages**, set **Source**: `Deploy from a branch` → Branch: `main` → Folder: `/docs`.
3. Edit `config.yml` and commit. The Action will rebuild the site.

If Pages 404s initially, wait for the first workflow run and confirm the Pages settings above.
