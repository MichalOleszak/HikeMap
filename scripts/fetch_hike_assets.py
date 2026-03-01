#!/usr/bin/env python3
"""Fetch recent hike data from Garmin Connect and emit static JSON for the site."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from garminconnect import Garmin, GarminConnectAuthenticationError  # type: ignore
except ImportError:  # pragma: no cover - handled by requirements
    Garmin = None  # type: ignore
    GarminConnectAuthenticationError = Exception  # type: ignore

DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


@dataclass
class Hike:
    id: str
    name: str
    date: str
    distance_km: float
    elevation_gain_m: float
    max_elevation_m: float
    duration_h: float
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

    activities = client.get_activities(0, limit)
    hikes: List[Hike] = []

    for activity in activities:
        activity_type = (activity.get("activityType") or {}).get("typeKey", "").lower()
        if activity_type not in {"hiking", "trail_running"}:
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

    hikes.sort(key=lambda h: h.date, reverse=True)
    return hikes


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate hike data for the map site")
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of recent activities to inspect",
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
        hikes = fetch_from_garmin(args.limit)
        meta = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source": "garmin",
        }

    if not hikes:
        print("No hikes found. Consider using --limit to pull more activities.")

    write_payload(hikes, meta)


if __name__ == "__main__":
    main()
