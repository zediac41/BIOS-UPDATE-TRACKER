# BIOS Tracker

This repo tracks the latest two BIOS versions for selected motherboards (ASUS, MSI, Gigabyte, ASRock).  
The site is automatically updated daily and published via GitHub Pages.

## Setup
1. Edit `config.yml` with your boards and vendor URLs.
2. Push to GitHub and enable GitHub Pages on the `gh-pages` branch.
3. The workflow will scrape BIOS pages daily and update `index.html`.

Visit your site at:  
`https://<username>.github.io/bios-tracker-pages-v2/`
