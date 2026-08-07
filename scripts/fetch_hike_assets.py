#!/usr/bin/env python3
"""Fetch recent hike data from Garmin Connect and emit static JSON for the site."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )  # type: ignore
except ImportError:  # pragma: no cover - handled by requirements
    Garmin = None  # type: ignore
    GarminConnectAuthenticationError = Exception  # type: ignore
    GarminConnectConnectionError = Exception  # type: ignore
    GarminConnectTooManyRequestsError = Exception  # type: ignore

DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
WORKOUT_STATS_PATH = DATA_DIR / "workout-stats-2026.json"
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
    polyline: Optional[List[List[float]]]
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


def load_overrides() -> List[Dict[str, Any]]:
    if not OVERRIDES_PATH.exists():
        return []
    with OVERRIDES_PATH.open(encoding='utf-8') as fp:
        payload = yaml.safe_load(fp) or []
    overrides: List[Dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        overrides.append({
            'id': str(entry['id']) if entry.get('id') not in {None, ''} else None,
            'name': entry.get('name'),
            'date': entry.get('date'),
            'distance_km': parse_float(entry.get('distance_km')),
            'elevation_gain_m': parse_float(entry.get('elevation_gain_m')),
            'max_elevation_m': parse_float(entry.get('max_elevation_m')),
            'duration_h': parse_float(entry.get('duration_h')),
        })
    return overrides


def apply_overrides(hikes: List[Hike], overrides: List[Dict[str, Any]]) -> int:
    if not overrides:
        return 0

    hikes_by_id = {hike.id: hike for hike in hikes if hike.id}
    applied = 0

    for override in overrides:
        target = None
        override_id = override.get('id')
        if override_id and override_id in hikes_by_id:
            target = hikes_by_id[override_id]
        else:
            name = override.get('name')
            if not name:
                continue
            date_hint = override.get('date')
            for hike in hikes:
                if hike.name == name and (not date_hint or hike.date == date_hint):
                    target = hike
                    break
        if not target:
            continue

        updated = False
        for field in ('distance_km', 'elevation_gain_m', 'max_elevation_m', 'duration_h'):
            value = override.get(field)
            if value is not None:
                setattr(target, field, value)
                updated = True
        if updated:
            applied += 1

    return applied


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


def build_workout_stats(activities: List[Dict[str, Any]], year: int) -> Dict[str, Any]:
    """Build aggregate counts for every Garmin activity in *year*.

    This intentionally does not expose individual non-hiking activities. The
    aggregate feeds the private Obsidian goal tracker without requiring it to
    perform a second Garmin login from a separate GitHub Action.
    """
    monthly = [0] * 12
    latest_date: Optional[str] = None

    for activity in activities:
        raw_start = activity.get("startTimeLocal") or activity.get("startTimeGMT")
        if not isinstance(raw_start, str) or len(raw_start) < 10:
            continue
        try:
            activity_date = datetime.fromisoformat(raw_start[:10]).date()
        except ValueError:
            continue
        if activity_date.year != year:
            continue
        monthly[activity_date.month - 1] += 1
        date_string = activity_date.isoformat()
        if latest_date is None or date_string > latest_date:
            latest_date = date_string

    return {
        "year": year,
        "total": sum(monthly),
        "monthly": monthly,
        "latest_activity": latest_date,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "definition": "Every Garmin activity counts as a workout.",
    }


def write_payload(
    hikes: List[Hike],
    meta: Dict[str, Any],
    workout_stats: Optional[Dict[str, Any]] = None,
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    hikes_path = DATA_DIR / "hikes.json"
    meta_path = DATA_DIR / "meta.json"

    with hikes_path.open("w", encoding="utf-8") as fp:
        json.dump([asdict(h) for h in hikes], fp, indent=2)
        fp.write("\n")

    with meta_path.open("w", encoding="utf-8") as fp:
        json.dump(meta, fp, indent=2)
        fp.write("\n")

    if workout_stats is not None:
        with WORKOUT_STATS_PATH.open("w", encoding="utf-8") as fp:
            json.dump(workout_stats, fp, indent=2)
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


def login_with_retry(client: "Garmin", attempts: int = 3, initial_delay: int = 60) -> None:
    delay = initial_delay
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            client.login()
            return
        except GarminConnectAuthenticationError:
            raise
        except GarminConnectTooManyRequestsError as err:  # pragma: no cover - network
            last_error = err
        except GarminConnectConnectionError as err:  # pragma: no cover - network
            if "429" not in str(err):
                raise
            last_error = err
        else:
            last_error = None

        if attempt == attempts:
            break

        wait_time = delay
        print(
            f"Garmin rate limit (429) on attempt {attempt}/{attempts}; retrying in {wait_time}s...",
            file=sys.stderr,
        )
        time.sleep(wait_time)
        delay *= 2

    if last_error is not None:
        raise last_error


def fetch_from_garmin(limit: int) -> tuple[List[Hike], List[Dict[str, Any]]]:
    ensure_garmin_available()
    username = os.environ.get("GARMIN_USERNAME")
    password = os.environ.get("GARMIN_PASSWORD")
    if not username or not password:
        raise RuntimeError("GARMIN_USERNAME and GARMIN_PASSWORD must be set in the environment")

    client = Garmin(username, password)
    try:
        login_with_retry(client)
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
            raw_polyline = (
                details.get("geoPolylineDTO", {}).get("polyline")
                if isinstance(details, dict)
                else None
            )
            if raw_polyline:
                # Keep only lat/lon — the full Garmin point objects carry 13
                # fields (speed, cumulative ascent, timer flags, etc.) that are
                # not needed for map rendering and bloat the JSON enormously.
                polyline = [
                    [round(pt["lat"], 5), round(pt["lon"], 5)]
                    for pt in raw_polyline
                    if pt.get("lat") is not None and pt.get("lon") is not None
                ] or None
        except Exception:  # pragma: no cover - best effort
            polyline = None
        hikes.append(Hike.from_activity(activity, polyline))

    hikes.sort(key=lambda h: h.date or "", reverse=True)
    return hikes, activities


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate hike data for the map site")
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
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
        workout_stats = None
        meta = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source": "sample",
        }
    else:
        overrides = load_overrides()
        try:
            hikes, activities = fetch_from_garmin(args.limit)
        except GarminConnectTooManyRequestsError as err:  # pragma: no cover - network
            print(
                f"Garmin rate limit hit ({err}); skipping refresh to avoid failures.",
                file=sys.stderr,
            )
            return
        workout_stats = build_workout_stats(activities, 2026)
        applied_overrides = apply_overrides(hikes, overrides)
        manual_hikes = load_manual_hikes()
        if manual_hikes:
            hikes.extend(manual_hikes)
        meta = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source": "garmin+manual" if manual_hikes else "garmin",
            "manual_count": len(manual_hikes),
            "override_count": applied_overrides,
        }

    if not hikes:
        print("No hikes found. Consider using --limit to pull more activities.")

    write_payload(hikes, meta, workout_stats)


if __name__ == "__main__":
    main()
