"""Texas extractor — TEA PEIMS Summarized Financial Data.

Source: https://tea.texas.gov/finance-and-grants/state-funding/
        state-funding-reports-and-data/peims-financial-data-downloads
File: 2009-2025 Summarized Financial Data Excel (~19 MB, refreshed yearly
each spring after audit close)

What this gives us:
  - FY2009 through latest published year of audited ACTUAL operating expenditures
    for every TX LEA, all in one bulk Excel.
  - One source_documents row covers the whole file. Per-district provenance is
    recoverable by filtering on DISTRICT NUMBER (== state_leaid suffix).

Topline definition:
  ALL FUNDS-TOTAL OPERATING EXPENDITURES BY OBJ
  (combines instruction, support services, admin, plant, transportation,
   etc. across all funds — most comparable to F-33 'current expenditures').

Status: `actual` — these are post-audit numbers, not budgets.

Inserts: one budget_event per TX district per requested fiscal_year.
Supersedes any prior non-superseded event for the same (leaid, FY, status),
including the synthetic legacy:step2:TX rows seeded in Phase 1.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from io import BytesIO

import pandas as pd
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

EXTRACTOR_NAME = "tx"
STATE = "TX"
BUCKET = "tx"

SOURCE_PORTAL_URL = (
    "https://tea.texas.gov/finance-and-grants/state-funding/"
    "state-funding-reports-and-data/peims-financial-data-downloads"
)
FILE_URL = (
    "https://tea.texas.gov/reports-and-data/financial-reports/"
    "school-finance-reports-and-data/2009-2025-summarized-financial-data-04-08-2026.xlsx"
)
PUBLISHER = "Texas Education Agency"
DOCUMENT_TYPE = "peims_summarized_financial_data_xlsx"
SHEET_NAME = "DATAMART"
TOPLINE_COL = "ALL FUNDS-TOTAL OPERATING EXPENDITURES BY OBJ"
TOPLINE_DEFINITION = (
    "TEA PEIMS Summarized Financial Data, "
    "ALL FUNDS-TOTAL OPERATING EXPENDITURES BY OBJ"
)


def download_bulk_excel() -> bytes:
    req = urllib.request.Request(
        FILE_URL, headers={"User-Agent": "school-budget-tracker/0.1"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def build_tx_crosswalk(client: Client) -> dict[str, dict]:
    """state_leaid suffix (TX district number, zero-padded) → district row."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if not sl.startswith("TX-"):
            continue
        # Normalize district number: strip leading zeros for matching, then
        # zero-pad inside the function. PEIMS DISTRICT NUMBER is typically 6
        # digits, sometimes with a leading "'" zero-padding artifact.
        out[sl.removeprefix("TX-").lstrip("0")] = r
    return out


def parse_peims(xlsx_bytes: bytes, fiscal_year: int) -> pd.DataFrame:
    """Return df with columns: tx_dist_num, fiscal_year, topline, prior_topline."""
    df = pd.read_excel(
        BytesIO(xlsx_bytes),
        sheet_name=SHEET_NAME,
        usecols=["DISTRICT NUMBER", "YEAR", TOPLINE_COL],
    )
    df["DISTRICT NUMBER"] = (
        df["DISTRICT NUMBER"].astype(str).str.lstrip("'").str.strip()
    )
    df = df.rename(
        columns={
            "DISTRICT NUMBER": "tx_dist_num",
            "YEAR": "fiscal_year",
            TOPLINE_COL: "topline",
        }
    )
    df["topline"] = pd.to_numeric(df["topline"], errors="coerce")
    df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["tx_dist_num", "fiscal_year", "topline"])
    df = df.sort_values(["tx_dist_num", "fiscal_year"])
    df["prior_topline"] = df.groupby("tx_dist_num")["topline"].shift(1)
    return df[df["fiscal_year"] == fiscal_year].copy()


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"TX extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        print("  downloading PEIMS Excel...")
        xlsx_bytes = download_bulk_excel()
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.1f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/peims_summarized_financial_data.xlsx"

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
                content=xlsx_bytes,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=FILE_URL,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                f"Sheet='{SHEET_NAME}', filter DISTRICT NUMBER == state_leaid "
                f"suffix; topline column '{TOPLINE_COL}'; YEAR == fiscal_year"
            ),
            notes=f"Bulk file covering FY09–FY{fiscal_year}; one row per (district, year)",
        )

        crosswalk = build_tx_crosswalk(client)
        print(f"  TX crosswalk: {len(crosswalk):,} state→NCES mappings")

        df = parse_peims(xlsx_bytes, fiscal_year=fiscal_year)
        print(f"  PEIMS rows for FY{fiscal_year}: {len(df):,}")

        no_match: list[str] = []
        for _, row in df.iterrows():
            key = str(row["tx_dist_num"]).lstrip("0")
            district = crosswalk.get(key)
            if district is None:
                no_match.append(key)
                continue

            topline = float(row["topline"])
            prior = (
                None if pd.isna(row["prior_topline"])
                else float(row["prior_topline"])
            )
            yoy_dollars = (topline - prior) if prior else None
            yoy_pct = (yoy_dollars / prior * 100) if prior else None

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="actual",
                topline_amount=topline,
                topline_definition=TOPLINE_DEFINITION,
                source_document_id=src_id,
                extraction_run_id=run.run_id,
                yoy_change_pct=yoy_pct,
                yoy_change_dollars=yoy_dollars,
                prior_year_baseline=prior,
            )
            _, changed = upsert_budget_event_with_supersession(
                client=client, event=event
            )
            run.records_extracted += 1
            if changed:
                run.records_changed += 1

        print(
            f"  inserted/changed={run.records_changed}/{run.records_extracted}; "
            f"unmatched TX district numbers: {len(no_match)}"
        )
        if no_match[:5]:
            print(f"  sample unmatched: {no_match[:10]}")

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match": no_match,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2025)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
