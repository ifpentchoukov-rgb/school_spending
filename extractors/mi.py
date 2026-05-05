"""Michigan extractor — MDE Bulletin 1011 (Analysis of MI Public Schools
Revenue and Expenditures) bulk Excel.

Source: https://www.michigan.gov/mde/services/financial-management/state-aid/
        publications/bulletin-1011-analysis-of-michigan-public-schools-
        revenue-and-expenditures
File pattern: https://mdoe.state.mi.us/SAMSPublic/Reports/others/
              {NN}_Bulletin1011Export.xlsx
e.g. 25_Bulletin1011Export.xlsx covers SY 2024-25 = our fiscal_year=2025.

What this gives us:
  - Per-district revenue + expenditure detail across 5 fund categories
    (General Fund, Special Revenue, Capital Projects, etc.) for completed
    Michigan FYs. MDE publishes one Excel annually after the AFR (Form
    SE-4096) reconciliation cycle completes.
  - 821 LEAs covered as of FY25.

Topline definition:
  Sum of `TOTCUROPEX` (Total Current Operating Expenditure) across all 5
  funds per district. This is MDE's all-funds operating spend, aligned
  with F-33 'current expenditures' and the actuals topline used for
  TX/CA/FL/IL/GA/OH.

Status: `actual` — these are post-AFR audited numbers.

Note: CEPI's Financial Information Database (FID) requires milogin and
isn't programmatically accessible. Bulletin 1011 is the public-facing
bulk extract of the same underlying data.

Crosswalk:
  Master state_leaid format: 'MI-{5-digit-DCode}' (e.g. 'MI-82015' Detroit)
  Bulletin DCode:            5-digit zero-padded code
  → strip 'MI-'.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from io import BytesIO

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

EXTRACTOR_NAME = "mi"
STATE = "MI"
BUCKET = "mi"
SOURCE_PORTAL_URL = (
    "https://www.michigan.gov/mde/services/financial-management/state-aid/"
    "publications/bulletin-1011-analysis-of-michigan-public-schools-"
    "revenue-and-expenditures"
)
PUBLISHER = "Michigan Department of Education"
DOCUMENT_TYPE = "mde_bulletin_1011_xlsx"
TOPLINE_DEFINITION = (
    "MDE Bulletin 1011 Bulletin1011Export sheet, sum of TOTCUROPEX (Total "
    "Current Operating Expenditure) across all 5 funds per district — "
    "all-funds audited operating spend"
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

# TOTCUROPEX column index in the Bulletin1011Export sheet (row 2 header).
TOTCUROPEX_COL_IDX = 59
DCODE_COL_IDX = 0
NAME_COL_IDX = 1


def file_url(fiscal_year: int) -> str:
    nn = fiscal_year % 100
    return (
        f"https://mdoe.state.mi.us/SAMSPublic/Reports/others/"
        f"{nn:02d}_Bulletin1011Export.xlsx"
    )


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_bulletin_1011(xlsx_bytes: bytes) -> list[dict]:
    """Aggregate TOTCUROPEX per district across all funds. Returns
    [{dcode, name, total_op_exp}, ...]."""
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    # Row 0 is blank, row 1 is header, data starts at row 2.
    header = rows[1] if len(rows) > 1 else None
    if not header or header[TOTCUROPEX_COL_IDX] != "TOTCUROPEX":
        raise RuntimeError(
            f"Header mismatch: expected TOTCUROPEX at col {TOTCUROPEX_COL_IDX}, "
            f"got '{header[TOTCUROPEX_COL_IDX] if header else None}'"
        )
    totals: dict[str, float] = defaultdict(float)
    names: dict[str, str] = {}
    for r in rows[2:]:
        if not r or not r[DCODE_COL_IDX]:
            continue
        try:
            v = float(r[TOTCUROPEX_COL_IDX] or 0)
        except (TypeError, ValueError):
            continue
        dcode = str(r[DCODE_COL_IDX])
        totals[dcode] += v
        names.setdefault(dcode, r[NAME_COL_IDX])
    return [
        {"dcode": dcode, "name": names.get(dcode), "total_op_exp": total}
        for dcode, total in totals.items()
        if total > 0
    ]


def build_mi_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("MI-"):
            out[sl.removeprefix("MI-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"MI extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        print(f"  downloading {url.rsplit('/',1)[-1]}...")
        try:
            xlsx_bytes = download(url)
        except urllib.error.HTTPError as e:
            print(f"  FAILED: {e}")
            raise
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.1f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/bulletin_1011.xlsx"

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
                "Sheet 'Bulletin1011Export'; match DCode == state_leaid suffix; "
                "topline = sum(TOTCUROPEX) across all 5 funds per district"
            ),
            notes=f"FY{fiscal_year} Bulletin 1011 audited revenue/expenditure data",
        )

        crosswalk = build_mi_crosswalk(client)
        print(f"  MI crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_totals = parse_bulletin_1011(xlsx_bytes)
        print(f"  Bulletin 1011 districts: {len(district_totals):,}")

        no_match: list[str] = []
        for d in district_totals:
            district = crosswalk.get(d["dcode"])
            if district is None:
                no_match.append(d["dcode"])
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
            f"unmatched DCodes: {len(no_match)}"
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
                   help="Bulletin 1011 FY (latest as of 2026-05-05: 2025)")
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
