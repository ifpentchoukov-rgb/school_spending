"""Oklahoma extractor — OSDE OCAS Expenditure Summary (With Exclusions).

Source: https://sdeweb01.sde.ok.gov/ocas_reporting/statereports.aspx
File: ExpenditureSummaryWithExclusions{YYYY}.xlsx (state-totals view).
      The "With Exclusions" file removes non-operating expenditures
      (capital outlay, debt service, fund-to-fund transfers).
      File year = end of school year (e.g. 2025 = SY 2024-25).

What this gives us:
  - Per-district current-operating expenditure detail down to the
    Object Code level (137k+ rows). Group by County + District code
    and sum the Expended column to get a per-district topline.

Topline definition:
  OCAS Expenditure Summary (With Exclusions) — sum of `Expended`
  per CountyCode+DistrictCode. The "With Exclusions" file already
  excludes capital outlay (function 4XXX), debt service (function
  5XXX), and inter-fund transfers from the Sheet1 detail. Aligned
  with F-33 'current expenditures' frame.

Status: `actual` — post-OCAS audited.

Crosswalk:
  Master state_leaid format: 'OK-{2-digit}-{4-char}' (e.g. 'OK-55-I001'
                              Oklahoma City)
  OCAS CountyCode + DistrictCode: '{2-digit}-{4-char}' concatenation
  → strip OK- prefix == CountyCode-DistrictCode directly.
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.error
import urllib.request

import openpyxl
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

EXTRACTOR_NAME = "ok"
STATE = "OK"
BUCKET = "ok"
SOURCE_PORTAL_URL = "https://sdeweb01.sde.ok.gov/ocas_reporting/statereports.aspx"
PUBLISHER = "Oklahoma State Department of Education (OCAS)"
DOCUMENT_TYPE = "ok_ocas_expenditure_summary_xlsx"
TOPLINE_DEFINITION = (
    "OSDE OCAS Expenditure Summary (With Exclusions), Sheet1 — sum of "
    "Expended per CountyCode+DistrictCode. 'With Exclusions' removes "
    "capital outlay (function 4XXX), debt service (function 5XXX), and "
    "inter-fund transfers. Aligned with F-33 'current expenditures' frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"


def file_url(fiscal_year: int) -> str:
    # OCAS files use end-of-SY year; FY25 = SY 2024-25 = fiscal_year=2025.
    return (
        f"https://sdeweb01.sde.ok.gov/ocas_reporting/docs/"
        f"ExpenditureSummaryWithExclusions{fiscal_year}.xlsx"
    )


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_ocas(xlsx_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb["Sheet1"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    expected = ("Year", "CountyCode", "DistrictCode", "districtName")
    if header[:4] != expected:
        raise RuntimeError(f"Unexpected OCAS header: {header[:4]}")
    totals: dict[str, float] = {}
    for r in rows:
        if not r or r[1] is None or r[2] is None:
            continue
        cc = str(r[1]).strip()
        dc = str(r[2]).strip()
        amt = r[10]  # Expended column
        if amt is None:
            continue
        try:
            v = float(amt)
        except (TypeError, ValueError):
            continue
        key = f"{cc}-{dc}"
        totals[key] = totals.get(key, 0.0) + v
    return [
        {"code": k, "total_op_exp": v}
        for k, v in totals.items()
        if v > 0
    ]


def build_ok_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("OK-"):
            out[sl.removeprefix("OK-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"OK extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        xlsx_bytes = download(url)
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.1f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/ocas_expenditure_with_exclusions.xlsx"

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
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "Sheet1; group by CountyCode + DistrictCode; sum Expended; "
                "match '{CountyCode}-{DistrictCode}' == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} OSDE OCAS Expenditure Summary (With Exclusions)",
        )

        crosswalk = build_ok_crosswalk(client)
        print(f"  OK crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_ocas(xlsx_bytes)
        print(f"  OCAS districts with FY{fiscal_year} expenditures: {len(district_data):,}")

        no_match: list[str] = []
        for d in district_data:
            district = crosswalk.get(d["code"])
            if district is None:
                no_match.append(d["code"])
                continue

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="actual",
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
            f"unmatched OCAS codes (charters/dependent/Common districts): {len(no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
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
