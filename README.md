# BIOS Tracker — Option B (Hardened)

Publishes **docs/index.html** from `main` to GitHub Pages. The generator is fail-safe:
- If `config.yml` is missing or empty, it still writes `docs/index.html` with a note.
- Per-board exceptions are caught; the page still renders.
- The workflow prints directory listings so you can verify the file exists.

## Setup
1. Create a new repo and upload this folder.
2. In GitHub: **Settings → Pages**
   - Source: **Deploy from a branch**
   - Branch: **main**
   - Folder: **/docs**
3. Edit `config.yml` with your boards + support URLs.
4. Run the workflow (Actions tab) or push a commit.

If your Pages site only shows a README, ensure:
- `docs/index.html` exists on `main` (see the workflow log: “Listing docs dir”).
- Pages is pointing to **main /docs**.
