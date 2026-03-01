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

## Manual hikes

Pre-Garmin adventures live in `data/manual_hikes.yaml`. Each entry can include:

```yaml
- name: "Galdhøpiggen"
  location: "Norway"
  date: 2018-08-12        # optional
  distance_km: 12.3       # optional
  elevation_gain_m: 1368  # optional
  max_elevation_m: 2469   # optional
  lat: 61.6360            # required for map marker
  lng: 8.3151             # required for map marker
```

Leave any unknown metric as `null` and it will render as `—` in the UI (and be skipped in the "Top" boxes). The fetch script automatically merges these manual entries with the Garmin data set.

## Metric overrides

For Garmin-recorded hikes where the watch died early or a metric is off, add an entry to `data/overrides.yaml`:

```yaml
- id: "1234567890"      # Garmin activityId (optional if you use name/date)
  name: "Mulhacén"      # fallback match when id is unknown
  date: 2023-10-05        # optional extra guard
  distance_km: 25.5       # omit or set to null to skip
  elevation_gain_m: null
  max_elevation_m: null
  duration_h: null
```

Overrides are matched by `id` when possible; otherwise the script falls back to `name` (and `date` if provided) to find the hike to patch. Any metric provided (distance, elevation gain, max elevation, or duration) replaces the Garmin value before the site is built. These overrides also run inside the nightly GitHub Action.

## Updating data from Garmin

The `scripts/fetch_hike_assets.py` script logs in to Garmin Connect using the `GARMIN_USERNAME` and `GARMIN_PASSWORD` environment variables. Run it locally like so:

```bash
export GARMIN_USERNAME="you@example.com"
export GARMIN_PASSWORD="super-secret"
python3 scripts/fetch_hike_assets.py --limit 10000
```

The script writes refreshed JSON to `public/data/` and updates `meta.json` with a timestamp (plus counts for manual hikes and overrides, if any). Any changes can then be committed and pushed.

## GitHub Actions

`fetch-data.yml` handles the entire pipeline:

1. Refresh data from Garmin (up to 10k recent activities).
2. Apply metric overrides from `data/overrides.yaml`.
3. Append manual hikes from `data/manual_hikes.yaml`.
4. Commit changes (if any).
5. Build the Vite site and deploy to GitHub Pages.

Ensure the repository has the following Actions secrets configured:

- `GARMIN_USERNAME`
- `GARMIN_PASSWORD`
- `GITHUB_TOKEN` (provided automatically)

Once the workflow runs successfully, GitHub Pages serves the site from the `github-pages` environment. EOF