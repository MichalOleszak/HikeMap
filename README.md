# HikeMap

Static site + automation pipeline for publishing Michal's hiking stats on GitHub Pages.

## Local development

```bash
npm install
npm run dev
```

The app expects hike data under `public/data/hikes.json`. During development you can populate it with sample content:

```bash
python3 scripts/fetch_hike_assets.py --use-sample
```

## Updating data from Garmin

The `scripts/fetch_hike_assets.py` script logs in to Garmin Connect using the `GARMIN_USERNAME` and `GARMIN_PASSWORD` environment variables. Run it locally like so:

```bash
export GARMIN_USERNAME="you@example.com"
export GARMIN_PASSWORD="super-secret"
python3 scripts/fetch_hike_assets.py --limit 80
```

The script writes refreshed JSON to `public/data/` and updates `meta.json` with a timestamp. Any changes can then be committed and pushed.

## GitHub Actions

Two workflows keep everything up-to-date:

- `fetch-data.yml` — runs nightly (and on manual dispatch) to refresh Garmin data, commit, and push.
- `deploy.yml` — builds the Vite app and publishes `dist/` to `gh-pages` whenever `main` changes.

Ensure the repository has the following Actions secrets configured:

- `GARMIN_USERNAME`
- `GARMIN_PASSWORD`
- `GITHUB_TOKEN` (provided automatically)

Once `deploy.yml` runs successfully, GitHub Pages will serve the site from the `gh-pages` branch. EOF