# Motherboard BIOS Tracker (GitHub Pages)

This repo scrapes the latest **two** BIOS versions for selected ASUS, MSI, GIGABYTE, and ASRock motherboards, then renders a clean, searchable website (via GitHub Pages).

## Quick Start

1. **Install deps** (Python 3.9+ recommended):

   ```bash
   pip install -r requirements.txt
   ```

2. **Add boards** to `boards.yaml` (paste the official BIOS/support page for each board).

3. **Run the scraper**:

   ```bash
   python -m src.scrape
   ```

   This writes `docs/data.json`. The static site in `docs/` reads that file.

4. **Publish**: push the repo to GitHub and enable **GitHub Pages** with the root set to `/docs`. Your site will be live at `https://<you>.github.io/<repo>/`

## How it Works

- `boards.yaml` — list of boards to track (name, vendor, official BIOS page URL).
- `src/vendors/*.py` — per-vendor scrapers. Currently each uses a **best-effort heuristic** parser designed to work across vendor pages without brittle selectors. If a vendor changes HTML, it should still pull out obvious "Version" + date pairs.
- `src/scrape.py` — loops over boards, scrapes, and writes `docs/data.json` with fields:
  - `board`, `vendor`
  - `latest` and `previous`: `{ "version": "...", "date": "YYYY-MM-DD" | null }`
  - `download_page`: the official BIOS page for convenience
  - Optional `error` with details if scraping failed.

- `docs/index.html` + `docs/app.js` — a static UI with **search** and **sort** by vendor and **latest date**. Clicking **Download** opens the vendor's official BIOS page for that board.

## Tips for Reliable Results

- Paste the most specific BIOS page you can find for the exact model (no generic family page).
- If some models fail to parse, open their page and confirm the version/date text is present in the HTML (not only inside a dynamic blob blocked by CORS).
- You can strengthen a vendor parser by specializing it:
  - E.g., inside `src/vendors/asus.py`, replace `scrape_generic(url)` with tailored BeautifulSoup selectors for that model family.
- Add a friendly delay in `src/scrape.py` to avoid hammering vendor sites (done by default).

## Automate Updates

Use GitHub Actions to run nightly and commit new `docs/data.json`. Create `.github/workflows/scrape.yml` with:

```yaml
name: Scrape BIOS
on:
  schedule:
    - cron: "15 5 * * *"  # daily at 05:15 UTC
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python -m src.scrape
      - name: Commit changes
        run: |
          git config user.name "bot"
          git config user.email "bot@example.com"
          git add docs/data.json
          git commit -m "Update BIOS data [skip ci]" || echo "No changes"
          git push
```

## Known Limitations

- Vendor pages change frequently; the included **heuristic** parser aims to be robust but isn't perfect.
- If date parsing fails, you'll still get versions; dates may be `null`. You can click **BIOS page** to verify.
- Some vendor sites load data dynamically; if requests don't see the content, consider adding a vendor-specific endpoint or selector.

## License

MIT
