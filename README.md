# Motherboard BIOS Tracker (ASUS / MSI / GIGABYTE / ASRock)

This repo fetches the latest **two** BIOS versions for your selected motherboards
(ASUS, MSI, GIGABYTE, ASRock) and publishes an auto-updating page via GitHub Pages.

- Static output in `/docs/index.html`
- Driven by `config.yml` (list your boards per vendor)
- Runs on push and nightly via GitHub Actions
- Shows **current** and **previous** BIOS versions only

## Quick Start
1. Upload these files to a new GitHub repository.
2. In **Settings → Pages**, set **Source** to `Deploy from a branch`, Branch to `main`, Folder to `/docs`.
3. Edit `config.yml` with your boards and commit.
4. The site will regenerate on push and nightly.

> If Pages shows a 404 at first, wait for the first workflow run and ensure `main` + `/docs` is selected.

## Local Run
```bash
python -m pip install -r requirements.txt
python bios_tracker.py
# Output written to /docs
```

If a vendor page layout changes, you can tweak the parser in `vendors/*.py`.
