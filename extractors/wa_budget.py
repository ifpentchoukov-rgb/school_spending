"""Washington adopted-budget extractor — OSPI F-195 Access database.

Companion to extractors/wa.py (F-196 actuals). Per RCW 28A.505.040,
WA school districts adopt FY budgets by Aug 31 (fiscal year is
Sep 1 – Aug 31, NOT Jul-Jun). OSPI publishes the F-195 data set
shortly after — typically October of the new school year.

What this gives us:
  - Per-district General Fund expenditures from the BOARD-ADOPTED
    budget, line-itemized by Program × Activity × Object.
  - Plus separate tables for Capital Projects, Debt Service, and
    Transportation Vehicle revenues (not used for the topline).

Topline definition:
  Sum of Amount in `{YYYY}-{YY+1} BudgetGeneralFundExpenditures` per
  CCDDD. This is parity with WA actuals topline (F-196 General Fund
  total expenditures), aligned with the F-33 'current expenditures'
  frame (Capital Projects + Debt Service are separate WA funds and
  are excluded by table boundary).

Status: `adopted` — F-195 = adopted budget for the new school year.

Crosswalk:
  Master state_leaid format: 'WA-{5-digit-CCDDD}' (e.g. 'WA-17001' Seattle)
  Access DB column:          CCDDD (5-char zero-padded)
  → state_leaid suffix == CCDDD.

Implementation note:
  The .accdb is a Microsoft Access database. We shell out to mdb-export
  (mdbtools, brew install mdbtools) to read the General Fund
  Expenditures table without needing an ODBC stack.
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

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

EXTRACTOR_NAME = "wa_budget"
STATE = "WA"
BUCKET = "wa"
SOURCE_PORTAL_URL = "https://ospi.k12.wa.us/safs-data-files"
PUBLISHER = "Washington Office of Superintendent of Public Instruction"
DOCUMENT_TYPE = "ospi_f195_accdb"
TOPLINE_DEFINITION = (
    "OSPI F-195 Access DB — sum of Amount in '{YYYY-YY} "
    "BudgetGeneralFundExpenditures' table per CCDDD. General Fund "
    "expenditures from the board-adopted budget. Aligned with F-33 "
    "'current expenditures' frame (Capital Projects + Debt Service are "
    "separate WA funds, excluded by table boundary)."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

# OSPI publishes one F-195 .accdb per fiscal year. URL pattern:
#   /sites/default/files/safs/AF195{YY1}{YY2}.accdb
# where YY1YY2 = e.g. "2526" for SY 2025-26 (= our fiscal_year=2026).
# Earlier years sometimes shipped as zipped .accdb — handle both.
KNOWN_FILE_URLS: dict[int, str] = {
    # FY26 = SY 2025-26 (latest as of 2026-05-07; FY27 expected Oct 2026
    # after Aug 31 adoption deadline).
    2026: "https://ospi.k12.wa.us/sites/default/files/safs/AF1952526.accdb",
}

EXPENDITURES_TABLE_TEMPLATE = "{yy1}-{yy2} BudgetGeneralFundExpenditures"


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def _table_name_for_fy(fiscal_year: int) -> str:
    """e.g. fiscal_year=2026 -> '2025-2026 BudgetGeneralFundExpenditures'."""
    yy1 = fiscal_year - 1
    yy2 = fiscal_year
    return EXPENDITURES_TABLE_TEMPLATE.format(yy1=yy1, yy2=yy2)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def _export_table_csv(accdb_bytes: bytes, table: str) -> bytes:
    """Run mdb-export against the .accdb bytes and return UTF-8 CSV bytes.

    Shells out to mdb-export (mdbtools); requires `brew install mdbtools`
    or an apt equivalent on Linux.
    """
    with tempfile.NamedTemporaryFile(suffix=".accdb", delete=False) as tf:
        tf.write(accdb_bytes)
        tmp_path = Path(tf.name)
    try:
        try:
            csv_bytes = subprocess.check_output(
                ["mdb-export", str(tmp_path), table],
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "mdb-export not found. Install mdbtools "
                "(`brew install mdbtools` on macOS)."
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"mdb-export failed for table '{table}': "
                f"{e.stderr.decode('utf-8', errors='replace')}"
            ) from e
    finally:
        tmp_path.unlink(missing_ok=True)
    return csv_bytes


def parse_wa_f195(accdb_bytes: bytes, fiscal_year: int) -> list[dict]:
    """Return [{code, total_op_exp}] from the F-195 Access DB.

    code = CCDDD (state_leaid suffix).
    total_op_exp = sum(Amount) in BudgetGeneralFundExpenditures.
    """
    table = _table_name_for_fy(fiscal_year)
    csv_bytes = _export_table_csv(accdb_bytes, table)
    totals: dict[str, float] = {}
    rdr = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8", errors="replace")))
    for row in rdr:
        ccddd = (row.get("CCDDD") or "").strip()
        if not ccddd:
            continue
        try:
            amt = float(row.get("Amount") or 0)
        except (TypeError, ValueError):
            continue
        totals[ccddd] = totals.get(ccddd, 0.0) + amt
    return [
        {"code": k, "total_op_exp": v}
        for k, v in totals.items()
        if v > 0
    ]


def build_wa_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("WA-"):
            out[sl.removeprefix("WA-")] = r
    return out


def extract(*, fiscal_year: int = 2026, triggered_by: str = "manual") -> dict:
    print(f"WA adopted-budget extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No WA F-195 URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        accdb_bytes = download(url)
        content_hash = sha256_bytes(accdb_bytes)
        print(f"  {len(accdb_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        # The full .accdb is ~120 MB which exceeds Supabase Storage's
        # default payload limit. Instead of storing the bulky source,
        # we extract the single relevant table to CSV and store that —
        # the canonical hash + source_url still pin the original .accdb.
        gf_csv_bytes = _export_table_csv(accdb_bytes, _table_name_for_fy(fiscal_year))
        storage_relpath = f"fy{fiscal_year}/f195_general_fund_expenditures.csv"

        existing_src = (
            client.table("source_documents")
            .select("id")
            .eq("content_hash_sha256", content_hash)
            .execute()
        )
        if not existing_src.data:
            print(
                f"  uploading General Fund Expenditures CSV "
                f"({len(gf_csv_bytes) / 1e6:.2f} MB extract from "
                f"{len(accdb_bytes) / 1e6:.0f} MB .accdb) "
                f"to {BUCKET}/{storage_relpath}..."
            )
            upload_source_document(
                client=client,
                bucket=BUCKET,
                storage_path=storage_relpath,
                content=gf_csv_bytes,
                mime_type="text/csv",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/x-msaccess",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                f"table='{_table_name_for_fy(fiscal_year)}'; "
                "sum(Amount) group by CCDDD; CCDDD == state_leaid suffix"
            ),
            notes=(
                f"FY{fiscal_year} WA F-195 adopted budget (General Fund "
                f"Expenditures). Hash is of canonical .accdb at source_url; "
                f"stored artifact is the General Fund Expenditures CSV "
                f"extract (other F-195 tables omitted to fit storage limits)."
            ),
        )

        crosswalk = build_wa_crosswalk(client)
        print(f"  WA crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_wa_f195(accdb_bytes, fiscal_year)
        print(f"  F-195 districts with FY{fiscal_year} adopted budget: {len(district_data):,}")

        no_match: list[str] = []
        for d in district_data:
            district = crosswalk.get(d["code"])
            if district is None:
                no_match.append(d["code"])
                continue

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="adopted",
                topline_amount=d["total_op_exp"],
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
            f"unmatched CCDDDs (state schools / non-operating not in master): {len(no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2026)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
