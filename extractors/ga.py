"""Georgia extractor — GOSA Revenues and Expenditures bulk CSV.

Source: https://gosa.georgia.gov/dashboards-data-report-card/downloadable-data
File pattern: https://download.gosa.ga.gov/{YEAR}/REVENUES_AND_EXPENDITURES{YYYY-YY}_{TIMESTAMP}.csv
e.g. .../2025/REVENUES_AND_EXPENDITURES2024-25_2026-02-19_00_32_04.csv
covers SY 2024-25 = our fiscal_year=2025.

What this gives us:
  - Audited per-district expenditure breakdown (11 functional categories)
    for completed fiscal years across all 203 GOSA-tracked GA LEAs.
  - GADOE collects the underlying data; GOSA (Governor's Office of Student
    Achievement) republishes as a clean tabular CSV. Released annually
    around Dec/Feb of the year after.

Topline definition:
  Sum of REV_EXP_VALUE across all 11 'K-12 Expenditures' descriptions per
  district at DETAIL_LVL_DESC='District' — Debt Services, General Admin,
  Instruction, Instructional Support, Maintenance & Operations, Media,
  Pupil Services, Renovation & Capital Projects, School Administration,
  School Food Services, Transportation. Matches the F-33 'total
  expenditures' frame: includes capital outlay (Renovation) plus debt
  service. (For the operating-only comparator we'd subtract Renovation
  and Debt Services, but the legacy/comparable definition is the full
  total — same as TX/CA/FL extractors.)

Status: `actual` — these are post-audit numbers from GADOE's DE0046
collection.

Note: GOSA tabulates ~203 LEAs (county districts + city districts +
charter LEAs). Master has ~192 GA operating LEAs. Charter LEAs that are
their own LEA in NCES may or may not match by 3-digit code.

Crosswalk:
  Master state_leaid format: 'GA-{3-digit-district-code}'
  GOSA SCHOOL_DSTRCT_CD:     3-digit district code
  → strip 'GA-'.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict

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

EXTRACTOR_NAME = "ga"
STATE = "GA"
BUCKET = "ga"
SOURCE_PORTAL_URL = "https://gosa.georgia.gov/dashboards-data-report-card/downloadable-data"
PUBLISHER = "Governor's Office of Student Achievement (GOSA)"
DOCUMENT_TYPE = "gosa_revenues_expenditures_csv"
TOPLINE_DEFINITION = (
    "GOSA Revenues_and_Expenditures CSV, sum of REV_EXP_VALUE across all "
    "11 'K-12 Expenditures' descriptions at DETAIL_LVL_DESC='District' "
    "(Debt Services, General Administration, Instruction, Instructional "
    "Support, Maintenance & Operations, Media, Pupil Services, Renovation "
    "& Capital Projects, School Administration, School Food Services, "
    "Transportation)"
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

# GOSA filenames have a timestamp suffix that's not predictable. Most-recent
# years observed (as of 2026-05-05):
#   FY25 (SY 2024-25): /2025/REVENUES_AND_EXPENDITURES2024-25_2026-02-19_00_32_04.csv
#   FY24 (SY 2023-24): /2024/REVENUES_AND_EXPENDITURES2023-24_2025-01-14_16_46_12.csv
# We hard-code the timestamps for now; when running for a new FY we'd need to
# scrape the index page or extend this map.
KNOWN_FILE_URLS: dict[int, str] = {
    2025: "https://download.gosa.ga.gov/2025/REVENUES_AND_EXPENDITURES2024-25_2026-02-19_00_32_04.csv",
    2024: "https://download.gosa.ga.gov/2024/REVENUES_AND_EXPENDITURES2023-24_2025-01-14_16_46_12.csv",
    2023: "https://download.gosa.ga.gov/2023/REVENUES_AND_EXPENDITURES2022-23_2023-12-19_21_24_10.csv",
}

INDEX_URL = "https://gosa.georgia.gov/dashboards-data-report-card/downloadable-data"


def discover_url(fiscal_year: int) -> str | None:
    """Try the hard-coded mapping first; fall back to scraping the index."""
    if fiscal_year in KNOWN_FILE_URLS:
        return KNOWN_FILE_URLS[fiscal_year]
    # Fallback: scrape the GOSA downloads page for a matching link.
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError:
        return None
    sy = f"{(fiscal_year - 1) % 100:02d}-{fiscal_year % 100:02d}"
    pattern = re.compile(
        r'href="(https://download\.gosa\.ga\.gov/\d+/REVENUES_AND_EXPENDITURES'
        + re.escape(sy) + r'_[^"]+\.csv)"'
    )
    m = pattern.search(html)
    return m.group(1) if m else None


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_district_toplines(csv_bytes: bytes) -> dict[str, dict]:
    """{district_code: {name, total_exp}} aggregating all 11 expenditure rows."""
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    by_district: dict[str, dict] = defaultdict(
        lambda: {"name": None, "total_exp": 0.0, "row_count": 0}
    )
    for r in reader:
        if r.get("DETAIL_LVL_DESC") != "District":
            continue
        if "Expenditures" not in (r.get("REVENUES/EXPENDITURES") or ""):
            continue
        code = r.get("SCHOOL_DSTRCT_CD") or ""
        if not code or code == "ALL":
            continue
        try:
            value = float(r.get("REV_EXP_VALUE") or 0)
        except (TypeError, ValueError):
            continue
        d = by_district[code]
        d["name"] = r.get("SCHOOL_DSTRCT_NM")
        d["total_exp"] += value
        d["row_count"] += 1
    # Drop any district with fewer than the expected 11 expenditure categories
    # (would indicate partial data). Keep but warn upstream.
    return dict(by_district)


def build_ga_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("GA-"):
            out[sl.removeprefix("GA-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"GA extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = discover_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No GOSA Revenues_and_Expenditures file URL found for "
                f"fiscal_year={fiscal_year}; either add to KNOWN_FILE_URLS or "
                "the SY label hasn't been published yet."
            )
        print(f"  downloading {url.rsplit('/',1)[-1]}...")
        csv_bytes = download(url)
        content_hash = sha256_bytes(csv_bytes)
        print(f"  {len(csv_bytes) / 1e3:.1f} KB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/revenues_expenditures.csv"

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
                content=csv_bytes,
                mime_type="text/csv",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="text/csv",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "Filter DETAIL_LVL_DESC='District' AND "
                "REVENUES/EXPENDITURES CONTAINS 'Expenditures'; "
                "match SCHOOL_DSTRCT_CD == state_leaid suffix; "
                "topline = sum(REV_EXP_VALUE) across 11 expenditure descriptions"
            ),
            notes=(
                f"FY{fiscal_year} (SY {fiscal_year-1}-{fiscal_year % 100}) audited "
                "per-district expenditure breakdown from GOSA"
            ),
        )

        crosswalk = build_ga_crosswalk(client)
        print(f"  GA crosswalk: {len(crosswalk):,} state→NCES mappings")

        toplines = parse_district_toplines(csv_bytes)
        print(f"  GOSA districts in CSV: {len(toplines):,}")

        no_match: list[str] = []
        partial_data: list[str] = []
        for code, d in sorted(toplines.items()):
            district = crosswalk.get(code)
            if district is None:
                no_match.append(f"{code} ({d['name']})")
                continue
            if d["row_count"] < 11:
                partial_data.append(f"{code}:{d['row_count']}")

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="actual",
                topline_amount=d["total_exp"],
                topline_definition=TOPLINE_DEFINITION,
                source_document_id=src_id,
                extraction_run_id=run.run_id,
            )
            _, changed = upsert_budget_event_with_supersession(
                client=client, event=event
            )
            run.records_extracted += 1
            if changed:
                run.records_changed += 1

        print(
            f"  inserted/changed={run.records_changed}/{run.records_extracted}; "
            f"unmatched GOSA codes: {len(no_match)}; "
            f"districts with partial categories: {len(partial_data)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2025,
                   help="GOSA file FY (latest as of 2026-05-05: 2025 = SY 2024-25)")
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
