"""Louisiana extractor — LDOE Annual Financial and Statistical Report (AFSR) Item 9.

Source: https://doe.louisiana.gov/data-and-reports/financial-data
File: {YYYY-YY}-annual-financial-and-statistical-report.zip — published
      annually by LDOE Office of School System Financial Services. The
      ZIP contains 16+ Excel files; we use 'AFSR item9 EXP {YYYY}.XLSX'.

What this gives us:
  - Per-district expenditure detail by category (Instruction, Support,
    Non-Instructional, Capital, Debt) for traditional parishes plus
    a handful of state-run districts. The Item 9 sheet has both
    `Total_Expenditure` and `Current_Expenditure` columns; the latter
    already excludes Facility Acquisition (E41) and Debt Service (E51)
    from the F-33 'current expenditures' frame.

Topline definition:
  Item 9 sheet, row where Category=E52 ('TOTAL EXPENDITURES') and
  Subcategory=TOT — `Current_Expenditure` column. This is the
  state-published F-33-aligned operating spending figure (excludes
  capital outlay and debt service).

Status: `actual` — post-AFR audited (LDOE publishes after fall AFR
collection cycle).

Crosswalk:
  Master state_leaid format: 'LA-{3-digit-or-alpha}' (e.g. 'LA-001'
                              Acadia Parish, 'LA-101' Special School
                              District; charters use 'LA-329'..'LA-WBE')
  AFSR Sponsorcd:            3-digit string (e.g. '001'); aggregate
                              entries like '2-BESE', '4-Type 2', 'LA'
                              are skipped.
  → strip LA- prefix == Sponsorcd directly.

Note: AFSR Item 9 covers the 69 traditional parishes + a few state-run
LEAs. Charter LEAs that file under a 'Type 2 charter' aggregate are
not covered by this extractor — captured as a sibling-extractor follow-up.
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.error
import urllib.request
import zipfile

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

EXTRACTOR_NAME = "la"
STATE = "LA"
BUCKET = "la"
SOURCE_PORTAL_URL = "https://doe.louisiana.gov/data-and-reports/financial-data"
PUBLISHER = "Louisiana Department of Education (Office of School System Financial Services)"
DOCUMENT_TYPE = "ldoe_afsr_item9_exp_zip"
TOPLINE_DEFINITION = (
    "LDOE AFSR Item 9 (Expenditures), row where Category=E52 ('TOTAL "
    "EXPENDITURES') and Subcategory=TOT — Current_Expenditure column. "
    "Excludes Facility Acquisition (E41) and Debt Service (E51); "
    "aligned with F-33 'current expenditures' frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

KNOWN_FILE_URLS: dict[int, str] = {
    # FY24 = SY 2023-24, published 2025.
    2024: (
        "https://doe.louisiana.gov/docs/default-source/financial-data/"
        "2023-2024-annual-financial-and-statistical-report.zip"
        "?sfvrsn=11f42af4_3"
    ),
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_afsr_item9(zip_bytes: bytes) -> list[dict]:
    """Return [{code, total_op_exp}] from AFSR Item 9 EXP per parish."""
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    target = next(
        (n for n in zf.namelist() if "item9" in n.lower() and "exp" in n.lower()
         and n.lower().endswith(".xlsx")),
        None,
    )
    if not target:
        raise RuntimeError(
            f"AFSR Item 9 EXP file not found in zip; namelist={zf.namelist()[:5]}"
        )
    xlsx_bytes = zf.read(target)
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb["item9"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    expected = (
        "Sponsorcd", "Sponsorname", "Subcategory", "Category", "Expenditure",
        "Total_Expenditure",
    )
    if header[:6] != expected:
        raise RuntimeError(f"Unexpected AFSR Item 9 header: {header[:6]}")
    out: list[dict] = []
    for r in rows:
        if not r or r[0] is None:
            continue
        # Only accept the grand-total row (Category=E52, Subcategory=TOT).
        if r[3] != "E52" or r[2] != "TOT":
            continue
        # Topline = Current_Expenditure (col 7); excludes capital + debt.
        amt = r[7]
        if amt is None:
            continue
        try:
            v = float(amt)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        code = str(r[0]).strip()
        # Skip aggregate entries like 'LA' (state total), '2-BESE',
        # '3-Labs', '4-Type 2', '5-RSD', '6-OJJ', etc.
        if not code or "-" in code or code.upper() == "LA":
            continue
        out.append({"code": code, "total_op_exp": v})
    return out


def build_la_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("LA-"):
            out[sl.removeprefix("LA-")] = r
    return out


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"LA extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No LDOE AFSR URL for fiscal_year={fiscal_year}; "
                "add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1].split('?')[0]}...")
        zip_bytes = download(url)
        content_hash = sha256_bytes(zip_bytes)
        print(f"  {len(zip_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/afsr.zip"

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
                content=zip_bytes,
                mime_type="application/zip",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/zip",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "ZIP contains 16+ Excel files; use 'AFSR item9 EXP {FY}.XLSX'; "
                "row where Category=E52 and Subcategory=TOT; topline = "
                "Current_Expenditure column; match Sponsorcd == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} LDOE Annual Financial and Statistical Report (AFSR)",
        )

        crosswalk = build_la_crosswalk(client)
        print(f"  LA crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_afsr_item9(zip_bytes)
        print(f"  AFSR Item 9 parishes/state-LEAs: {len(district_data):,}")

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
            f"unmatched AFSR codes: {len(no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2024)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
