# Motherboard BIOS Tracker (ASUS / MSI / GIGABYTE / ASRock)

Fetch the latest **two** BIOS versions for selected motherboards and publish a static page via GitHub Pages.

- Output in `/docs/index.html`
- Driven by `config.yml` (models per vendor). Supports **explicit support URLs** per model.
- Runs on push and nightly via GitHub Actions
- Shows **current** and **previous** BIOS versions

## Quick Start
1. Upload files to a new GitHub repository.
2. In **Settings → Pages**, set **Source**: `Deploy from a branch` → Branch: `main` → Folder: `/docs`.
3. Edit `config.yml` and commit. The Action will rebuild the site.

If Pages 404s initially, wait for the first workflow run and confirm the Pages settings above.
