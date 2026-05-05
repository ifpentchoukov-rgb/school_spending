"""Seed `districts` from legacy/sd_tracker_step1/processed/master_districts.csv.

Operating-only filter (~11,880 rows). Idempotent via upsert on `leaid`.
Run with `.venv/bin/python -m seeds.seed_districts`.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from seeds._client import get_client

CSV_PATH = (
    Path(__file__).parent.parent
    / "legacy"
    / "sd_tracker_step1"
    / "processed"
    / "master_districts.csv"
)

BATCH = 500


def coerce_int(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def coerce_float(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_tier(value: str) -> int | None:
    n = coerce_int(value)
    return n if n in (1, 2, 3) else None


def coerce_calendar(value: str) -> str | None:
    v = (value or "").strip()
    return v if v in {"July-June", "Sept-Aug"} else None


def iter_rows():
    with CSV_PATH.open() as f:
        for r in csv.DictReader(f):
            if r["is_operating_district"].strip().lower() != "true":
                continue
            yield {
                "leaid": r["leaid"],
                "lea_name": r["lea_name"],
                "state_postal": r["state_postal"],
                "state_leaid": r["state_leaid"] or None,
                "county_name": r["county_name"] or None,
                "enrollment_fy25": coerce_int(r["enrollment_fy25"]),
                "exp_total_fy23": coerce_float(r["exp_total_fy23"]),
                "is_operating_district": True,
                "data_tier": coerce_tier(r["data_tier"]),
                "fy_calendar": coerce_calendar(r["fy_calendar"]),
            }


def main() -> int:
    rows = list(iter_rows())
    print(f"districts: {len(rows)} operating rows from {CSV_PATH.name}")

    client = get_client()
    table = client.table("districts")
    inserted = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        table.upsert(batch, on_conflict="leaid").execute()
        inserted += len(batch)
        print(f"  upserted {inserted}/{len(rows)}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
