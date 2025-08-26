# BIOS Tracker — Option B (Pages from /docs on main)

This repo publishes **docs/index.html** from the `main` branch to GitHub Pages.

## Setup
1. Create a repo and upload this folder.
2. In GitHub: **Settings → Pages**
   - Source: **Deploy from a branch**
   - Branch: **main**
   - Folder: **/docs**
3. Edit `config.yml` with your boards + support URLs.
4. Push. The Action will generate `docs/index.html` and commit it to `main` automatically.

If you only see a README on your Pages site, double-check that `docs/index.html` exists on `main` (the workflow prints a directory listing to the logs).
