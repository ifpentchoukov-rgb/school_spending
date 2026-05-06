"""DC extractor — OSSE DC School Report Card Finance Data XLSX.

Source: https://osse.dc.gov/page/dc-school-report-card-resource-library
File: DC School Report Card School Finance Data ({YEAR}).xlsx
      OSSE refreshes this each spring with the prior FY's data.

What this gives us:
  - Per-LEA expenditure breakdown across State/Local and Federal
    funding sources, with both school-level and centralized totals.
    73 LEAs in the file (DCPS + ~67 charter LEAs + specialty).

Topline definition:
  Sheet 'Finance Data': Aggregate State/Local Expenditures (col 8) +
  Total School Level Expenditures Federal (col 10) + Total School
  Share of Centralized Expenditures Federal (col 11). Aligned with
  F-33 'current expenditures' frame.

Status: `actual` — post-AFR audited (LEA Financial Reporting App).

Crosswalk:
  Master state_leaid format: 'DC-{3-digit}' (e.g. 'DC-001' DCPS)
  XLSX 'LEA Code':           integer (e.g. 1, 108, 178)
  → state_leaid suffix == zfill(LEA Code, 3).
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

EXTRACTOR_NAME = "dc"
STATE = "DC"
BUCKET = "dc"
SOURCE_PORTAL_URL = "https://osse.dc.gov/page/dc-school-report-card-resource-library"
PUBLISHER = "DC Office of the State Superintendent of Education (OSSE)"
DOCUMENT_TYPE = "dc_osse_school_finance_data_xlsx"
TOPLINE_DEFINITION = (
    "OSSE DC School Report Card Finance Data XLSX, sheet 'Finance "
    "Data': Aggregate State/Local Expenditures + Total School Level "
    "Expenditures Federal + Total School Share of Centralized "
    "Expenditures Federal per LEA. Aligned with F-33 'current "
    "expenditures' frame."
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

KNOWN_FILE_URLS: dict[int, str] = {
    # SY 2023-24 = FY24, published 2025.
    2024: "https://osse.dc.gov/sites/default/files/dc/sites/osse/page_content/attachments/DC%20School%20Report%20Card%20School%20Finance%20Data%20%282024%29.xlsx",
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_dc(xlsx_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb["Finance Data"]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # header
    out: list[dict] = []
    for r in rows:
        if not r or r[1] is None:
            continue
        try:
            lea_code = int(r[1])
        except (TypeError, ValueError):
            continue
        try:
            sl = float(r[8]) if r[8] is not None else 0.0
            fed_school = float(r[10]) if r[10] is not None else 0.0
            fed_cent = float(r[11]) if r[11] is not None else 0.0
        except (TypeError, ValueError):
            continue
        total = sl + fed_school + fed_cent
        if total <= 0:
            continue
        out.append({"code": f"{lea_code:03d}", "total_op_exp": total})
    return out


def build_dc_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("DC-"):
            out[sl.removeprefix("DC-")] = r
    return out


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"DC extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No DC OSSE URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading School Finance Data ({fiscal_year}).xlsx...")
        xlsx_bytes = download(url)
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/school_finance_data.xlsx"

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
                "Sheet 'Finance Data'; col 8 + col 10 + col 11 (S/L + "
                "Fed school + Fed centralized) per row; match "
                "zfill(LEA Code, 3) == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} OSSE DC School Report Card Finance Data",
        )

        crosswalk = build_dc_crosswalk(client)
        print(f"  DC crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_dc(xlsx_bytes)
        print(f"  DC LEAs in file: {len(district_data):,}")

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
            f"unmatched DC codes (charters not in master): {len(no_match)}"
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
