"""Connecticut extractor — OPM Adopted Municipal Budgets (data.ct.gov SODA API).

Source: https://data.ct.gov/d/pcg4-s5rc
        ("Summary Financial Information from Adopted Municipal Budgets,
         2022-Present")
API: https://data.ct.gov/resource/pcg4-s5rc.json (Socrata SoQL)

What this gives us:
  - Per-municipality `Education Expenditures` from the **adopted** budget
    (not actuals) — Connecticut towns adopt their full municipal budget
    including a school-spending line. The OPM Fiscal Health Monitoring
    System (FHMS) publishes these as soon as towns adopt them, with the
    actual `date_budget_adopted` recorded.
  - 170 entities per FY (169 municipalities + Groton City).
  - FY22-FY26 currently published (FY26 = SY 2025-26 = our fiscal_year=2026).

Topline definition:
  `education_expenditures` field — the town's total education spending
  line from the adopted municipal operating budget. For towns with their
  own school district this equals the district's adopted budget; for
  towns in a regional school district this is the town's assessment to
  that regional district.

Status: `adopted` — these are board/town-meeting adopted budgets uploaded
to OPM with a `date_budget_adopted` field.

Crosswalk:
  Master state_leaid format: 'CT-{7-digit}' state-assigned LEA ID
                              (doesn't directly map to town name)
  OPM entity_name:           Town name in UPPER (e.g. 'ANSONIA', 'HARTFORD')
  → Match by normalized lea_name → strip "School District" / "Public
    Schools" suffix, uppercase. Town/city school districts match cleanly
    (~129 of 139 master CT operating LEAs); regional school districts
    and charter LEAs don't have a town-name equivalent and won't match.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

from supabase import Client

from extractors._base import (
    BudgetEventInput,
    Run,
    fetch_all,
    sha256_bytes,
    upload_source_document,
    upsert_budget_event_with_supersession,
    upsert_source_document_row,
)

EXTRACTOR_NAME = "ct"
STATE = "CT"
BUCKET = "ct"
SOURCE_PORTAL_URL = "https://data.ct.gov/d/pcg4-s5rc"
SODA_BASE = "https://data.ct.gov/resource/pcg4-s5rc.json"
PUBLISHER = "Connecticut Office of Policy and Management"
DOCUMENT_TYPE = "ct_opm_adopted_municipal_budget_json"
TOPLINE_DEFINITION = (
    "CT OPM Adopted Municipal Budget (FHMS), 'education_expenditures' "
    "field — town's adopted education spending line. For towns with own "
    "school district this is the district's adopted budget; for towns in "
    "a regional school district this is their assessment to it."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"


def fetch_fy_records(fiscal_year: int) -> tuple[list[dict], bytes]:
    """Pull all rows for fiscal_year from the SODA API. Returns (records,
    raw_bytes_for_provenance)."""
    url = (
        f"{SODA_BASE}?$where=fiscal_period_of_budget={fiscal_year}"
        f"&$limit=500"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    records = json.loads(raw)
    return records, raw


def normalize_master_name(name: str) -> str:
    n = re.sub(
        r"\s+(School District|Public Schools|Schools|Public School District|"
        r"Regional School District|District)$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    n = re.sub(r"\s+", " ", n).upper()
    return n


def build_ct_crosswalk(client: Client) -> dict[str, dict]:
    """{normalized_town_name: district_row}. Town/city school districts only;
    regional districts and charters don't map to a single town name."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        name = r.get("lea_name") or ""
        # Skip regional / cooperative / charter / academy LEAs that don't
        # have a 1-town equivalent
        lower = name.lower()
        if any(x in lower for x in ("regional", "cooperative", "academy", "charter")):
            continue
        key = normalize_master_name(name)
        out.setdefault(key, r)
    return out


def extract(*, fiscal_year: int = 2026, triggered_by: str = "manual") -> dict:
    print(f"CT extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        records, raw = fetch_fy_records(fiscal_year)
        print(f"  fetched {len(records)} OPM municipal records for FY{fiscal_year}")

        content_hash = sha256_bytes(raw)
        storage_relpath = f"fy{fiscal_year}/opm_adopted_municipal_budgets.json"

        existing_src = (
            client.table("source_documents")
            .select("id")
            .eq("content_hash_sha256", content_hash)
            .execute()
        )
        if not existing_src.data:
            print(f"  uploading to {BUCKET}/{storage_relpath}...")
            upload_source_document(
                client=client,
                bucket=BUCKET,
                storage_path=storage_relpath,
                content=raw,
                mime_type="application/json",
            )

        url = f"{SODA_BASE}?$where=fiscal_period_of_budget={fiscal_year}"
        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/json",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "Socrata SoQL: $where=fiscal_period_of_budget=N; "
                "match entity_name == normalize(lea_name); "
                "topline = education_expenditures field"
            ),
            notes=(
                f"FY{fiscal_year} CT adopted municipal budgets via OPM FHMS. "
                "Regional school districts NOT covered (data is per-town)."
            ),
        )

        crosswalk = build_ct_crosswalk(client)
        print(f"  CT crosswalk (town/city districts only): {len(crosswalk):,}")

        no_match: list[str] = []
        for r in records:
            name = (r.get("entity_name") or "").strip().upper()
            if not name:
                continue
            try:
                edu = float(r.get("education_expenditures") or 0)
            except (TypeError, ValueError):
                continue
            if edu <= 0:
                continue
            district = crosswalk.get(name)
            if district is None:
                no_match.append(name)
                continue

            event_date = r.get("date_budget_adopted")
            if event_date and "T" in event_date:
                event_date = event_date.split("T", 1)[0]

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="adopted",
                topline_amount=edu,
                topline_definition=TOPLINE_DEFINITION,
                source_document_id=src_id,
                extraction_run_id=run.run_id,
                event_date=event_date,
            )
            _, changed = upsert_budget_event_with_supersession(
                client=client, event=event
            )
            run.records_extracted += 1
            if changed:
                run.records_changed += 1

        print(
            f"  inserted/changed={run.records_changed}/{run.records_extracted}; "
            f"unmatched OPM entities (regional districts / non-school towns): {len(no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2026,
                   help="OPM fiscal_period_of_budget (FY26 = SY 2025-26 latest as of 2026-05-05)")
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
