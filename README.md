# BIOS Tracker (Pages Fix)

This version writes the site to `./public/index.html` and the workflow deploys **only** that folder to the `gh-pages` branch.

## Steps
1. Push this repo to GitHub on `main` (or `master`).
2. Go to **Settings → Pages** and set **Source = Deploy from a branch** and **Branch = `gh-pages`**.
3. Edit `config.yml` with your boards and URLs.
4. Check **Actions** logs — look for the `Listing public dir:` step to confirm `index.html` was produced.
5. Your site should be at `https://<username>.github.io/<repo-name>/`.

If nothing appears:
- Confirm the workflow ran successfully and `public/index.html` exists in logs.
- Ensure Pages is pointed at the `gh-pages` branch.
- Verify there’s no organization policy blocking Pages.
