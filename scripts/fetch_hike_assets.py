#!/usr/bin/env python3
"""Fetch recent hike data from Garmin Connect and emit static JSON for the site."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    from garminconnect import Garmin, GarminConnectAuthenticationError  # type: ignore
except ImportError:  # pragma: no cover - handled by requirements
    Garmin = None  # type: ignore
    GarminConnectAuthenticationError = Exception  # type: ignore

DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"
MANUAL_HIKES_PATH = Path(__file__).resolve().parents[1] / "data" / "manual_hikes.yaml"


OVERRIDES_PATH = Path(__file__).resolve().parents[1] / "data" / "overrides.yaml"


def slugify(value: str) -> str:
    if not value:
        return "manual-hike"
    normalized = unicodedata.normalize('NFKD', value)
    ascii_value = normalized.encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_value.lower()).strip('-')
    return slug or 'manual-hike'


def parse_float(value: Any, digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits)


@dataclass
class Hike:
    id: str
    name: str
    date: Optional[str]
    distance_km: Optional[float]
    elevation_gain_m: Optional[float]
    max_elevation_m: Optional[float]
    duration_h: Optional[float]
    location: Dict[str, Optional[float]]
    polyline: Optional[str]
    cover_photo: Optional[str]

    @staticmethod
    def from_activity(activity: Dict[str, Any], polyline: Optional[str]) -> "Hike":
        start = activity.get("startTimeLocal") or activity.get("startTimeGMT")
        date = start.split("T")[0] if start else "1970-01-01"
        duration_s = activity.get("duration", 0) or 0
        return Hike(
            id=str(activity.get("activityId")),
            name=activity.get("activityName") or "Unnamed Hike",
            date=date,
            distance_km=round((activity.get("distance", 0) or 0) / 1000, 2),
            elevation_gain_m=round(activity.get("elevationGain", 0) or 0, 1),
            max_elevation_m=round(activity.get("maxElevation", 0) or 0, 1),
            duration_h=round(duration_s / 3600, 2),
            location={
                "lat": activity.get("startLatitude"),
                "lng": activity.get("startLongitude"),
            },
            polyline=polyline,
            cover_photo=None,
        )


def load_overrides() -> Dict[str, Dict[str, Any]]:
    if not OVERRIDES_PATH.exists():
        return {}
    with OVERRIDES_PATH.open(encoding='utf-8') as fp:
        payload = yaml.safe_load(fp) or []
    overrides: Dict[str, Dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        hike_id = entry.get('id')
        if not hike_id:
            continue
        overrides[str(hike_id)] = {
            'distance_km': parse_float(entry.get('distance_km')),
            'elevation_gain_m': parse_float(entry.get('elevation_gain_m')),
            'max_elevation_m': parse_float(entry.get('max_elevation_m')),
            'duration_h': parse_float(entry.get('duration_h')),
        }
    return overrides


def load_manual_hikes() -> List[Hike]:
    if not MANUAL_HIKES_PATH.exists():
        return []

    with MANUAL_HIKES_PATH.open(encoding='utf-8') as fp:
        payload = yaml.safe_load(fp) or []

    hikes: List[Hike] = []
    seen_ids: set[str] = set()

    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            continue
        name = entry.get('name') or f'Manual hike {index + 1}'
        base_id = entry.get('id') or f"manual-{slugify(name)}"
        candidate = base_id
        suffix = 1
        while candidate in seen_ids:
            candidate = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(candidate)

        hikes.append(
            Hike(
                id=candidate,
                name=name,
                date=entry.get('date') or None,
                distance_km=parse_float(entry.get('distance_km')),
                elevation_gain_m=parse_float(entry.get('elevation_gain_m'), 1),
                max_elevation_m=parse_float(entry.get('max_elevation_m'), 1),
                duration_h=parse_float(entry.get('duration_h')),
                location={
                    'lat': parse_float(entry.get('lat'), 6),
                    'lng': parse_float(entry.get('lng'), 6),
                },
                polyline=None,
                cover_photo=None,
            )
        )

    return hikes


def write_payload(hikes: List[Hike], meta: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    hikes_path = DATA_DIR / "hikes.json"
    meta_path = DATA_DIR / "meta.json"

    with hikes_path.open("w", encoding="utf-8") as fp:
        json.dump([asdict(h) for h in hikes], fp, indent=2)
        fp.write("\n")

    with meta_path.open("w", encoding="utf-8") as fp:
        json.dump(meta, fp, indent=2)
        fp.write("\n")

    print(f"Wrote {len(hikes)} hikes to {hikes_path.relative_to(Path.cwd())}")


def load_sample() -> List[Hike]:
    sample_path = SAMPLE_DIR / "hikes.sample.json"
    with sample_path.open(encoding="utf-8") as fp:
        payload = json.load(fp)
    return [Hike(**item) for item in payload]


def ensure_garmin_available() -> None:
    if Garmin is None:
        print("garminconnect is not installed. Run `pip install -r requirements.txt`.", file=sys.stderr)
        sys.exit(1)


def fetch_from_garmin(limit: int) -> List[Hike]:
    ensure_garmin_available()
    username = os.environ.get("GARMIN_USERNAME")
    password = os.environ.get("GARMIN_PASSWORD")
    if not username or not password:
        raise RuntimeError("GARMIN_USERNAME and GARMIN_PASSWORD must be set in the environment")

    client = Garmin(username, password)
    try:
        client.login()
    except GarminConnectAuthenticationError as err:  # pragma: no cover - network
        raise SystemExit(f"Failed to authenticate with Garmin: {err}")

    activities: List[Dict[str, Any]] = []
    fetched = 0
    max_batch = 1000
    while fetched < limit:
        batch_size = min(max_batch, limit - fetched)
        if batch_size <= 0:
            break
        batch = client.get_activities(fetched, batch_size)
        if not batch:
            break
        activities.extend(batch)
        fetched += len(batch)
        if len(batch) < batch_size:
            break

    hikes: List[Hike] = []
    for activity in activities:
        activity_type = (activity.get("activityType") or {}).get("typeKey", "").lower()
        if activity_type not in {"hiking", "trail_running", "mountaineering"}:
            continue
        activity_id = activity.get("activityId")
        polyline = None
        try:
            details = client.get_activity_details(activity_id)
            polyline = (
                details.get("geoPolylineDTO", {}).get("polyline")
                if isinstance(details, dict)
                else None
            )
        except Exception:  # pragma: no cover - best effort
            polyline = None
        hikes.append(Hike.from_activity(activity, polyline))

    hikes.sort(key=lambda h: h.date or "", reverse=True)
    return hikes


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate hike data for the map site")
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Approximate number of recent activities to inspect (batched at 1000 per API call)",
    )
    parser.add_argument(
        "--use-sample",
        action="store_true",
        help="Populate data directory with bundled sample data",
    )
    args = parser.parse_args()

    if args.use_sample:
        hikes = load_sample()
        meta = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source": "sample",
        }
    else:
        overrides = load_overrides()
        hikes = fetch_from_garmin(args.limit)
        if overrides:
            for hike in hikes:
                patch = overrides.get(hike.id)
                if not patch:
                    continue
                if patch.get('distance_km') is not None:
                    hike.distance_km = patch['distance_km']
                if patch.get('elevation_gain_m') is not None:
                    hike.elevation_gain_m = patch['elevation_gain_m']
                if patch.get('max_elevation_m') is not None:
                    hike.max_elevation_m = patch['max_elevation_m']
                if patch.get('duration_h') is not None:
                    hike.duration_h = patch['duration_h']
        manual_hikes = load_manual_hikes()
        if manual_hikes:
            hikes.extend(manual_hikes)
        meta = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source": "garmin+manual" if manual_hikes else "garmin",
            "manual_count": len(manual_hikes),
            "override_count": len(overrides),
        }

    if not hikes:
        print("No hikes found. Consider using --limit to pull more activities.")

    write_payload(hikes, meta)


if __name__ == "__main__":
    main()
