"""Seed FY25 `actual` budget_events from legacy/sd_tracker_step2.

Steps per state (TX/CA/FL):
  1. Upsert one synthetic source_documents row keyed by `notes='legacy:step2:{STATE}'`.
  2. Insert budget_events rows pointing at that source_document_id.

Idempotent: deletes any existing FY25 actual rows linked to the legacy synthetic
source_documents before re-inserting. (Legacy data has no extraction_run_id, so
deletion is bounded by the source_document_id whitelist.)

Run with `.venv/bin/python -m seeds.seed_legacy_actuals`.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

from seeds._client import get_client

CSV_PATH = (
    Path(__file__).parent.parent
    / "legacy"
    / "sd_tracker_step2"
    / "processed"
    / "state_extractions.csv"
)

BATCH = 500


def coerce_float(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    by_state: dict[str, list[dict]] = defaultdict(list)
    state_meta: dict[str, dict[str, str]] = {}
    skipped_null_topline = 0

    with CSV_PATH.open() as f:
        for r in csv.DictReader(f):
            state = r["state_postal"]
            if state not in state_meta:
                publisher = r["notes"].split(";")[0].strip()
                topline_def = r["notes"].split("definition=")[-1].strip("' ")
                state_meta[state] = {
                    "source_url": r["source"],
                    "publisher": publisher,
                    "topline_definition": topline_def,
                    "fetched_at": r["source_date"],
                }
            topline = coerce_float(r["topline_amount"])
            if topline is None:
                skipped_null_topline += 1
                continue
            by_state[state].append(
                {
                    "leaid": r["leaid"],
                    "fiscal_year": int(r["fiscal_year"]),
                    "status": r["status"],
                    "topline_amount": topline,
                    "yoy_change_pct": coerce_float(r["yoy_change_pct"]),
                    "yoy_change_dollars": coerce_float(r["yoy_change_dollars"]),
                    "event_date": r["source_date"] or None,
                }
            )

    print(f"states: {sorted(by_state.keys())}")
    total = sum(len(v) for v in by_state.values())
    print(f"total legacy rows: {total} (skipped {skipped_null_topline} with null topline_amount)")

    client = get_client()

    # Step 1: ensure one synthetic source_documents row per state (check-then-insert).
    state_to_src_id: dict[str, str] = {}
    for state, meta in sorted(state_meta.items()):
        marker = f"legacy:step2:{state}"
        existing = (
            client.table("source_documents")
            .select("id")
            .eq("notes", marker)
            .execute()
        )
        if existing.data:
            state_to_src_id[state] = existing.data[0]["id"]
            continue
        inserted = (
            client.table("source_documents")
            .insert(
                {
                    "source_url": meta["source_url"],
                    "publisher": meta["publisher"],
                    "document_type": "legacy_seed_extraction",
                    "notes": marker,
                    "fetched_at": meta["fetched_at"] + "T00:00:00+00:00",
                }
            )
            .execute()
        )
        state_to_src_id[state] = inserted.data[0]["id"]
    print(f"source_documents resolved: {state_to_src_id}")

    # Step 2: clear any prior FY25 actual rows tied to these legacy sources, then insert fresh.
    src_ids = list(state_to_src_id.values())
    deleted = (
        client.table("budget_events")
        .delete()
        .in_("source_document_id", src_ids)
        .execute()
    )
    print(f"cleared {len(deleted.data or [])} prior legacy budget_events")

    inserted = 0
    for state, rows in sorted(by_state.items()):
        src_id = state_to_src_id[state]
        topline_def = state_meta[state]["topline_definition"]
        payload = [
            {
                **row,
                "topline_definition": topline_def,
                "source_document_id": src_id,
            }
            for row in rows
        ]
        for i in range(0, len(payload), BATCH):
            batch = payload[i : i + BATCH]
            client.table("budget_events").insert(batch).execute()
            inserted += len(batch)
            print(f"  {state}: inserted {min(i + BATCH, len(payload))}/{len(payload)}")

    print(f"done: {inserted} budget_events inserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
