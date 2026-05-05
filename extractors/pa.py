"""Pennsylvania extractor — PDE General Fund Budget (GFB) bulk Excel.

Source: https://www.pa.gov/agencies/education/programs-and-services/schools/
        grants-and-funding/school-finances/financial-data/general-fund-budget-gfb-data
File pattern: https://www.pa.gov/content/dam/copapwp-pagov/en/education/
              documents/schools/grants-and-funding/school-finances/finances/
              gfbdata/{YYYY-YY}gfbdata.xlsx
e.g. 2025-26gfbdata.xlsx covers SY 2025-26 = our fiscal_year=2026.

What this gives us:
  - Adopted General Fund Budget (operating budget) per PA school district per
    fiscal year. PDE publishes one Excel per fiscal year covering all
    ~500 districts plus IUs (Intermediate Units, separate sheets).
  - Available years: 2016-17 through 2025-26 as of 2026-05-05.

Topline definition:
  `FB_Cert` sheet, column `TotalExpAmount` — the certified total
  expenditure budget per district. PDE derives this from the detailed
  expenditure breakdown in the `Exp` sheet (function-object grid). Aligned
  with adopted-budget definition used by FL Summary Budget and CA SACS BS1
  for cross-state comparability.

Status: `adopted` — these are board-adopted budgets filed with PDE per
24 P.S. § 6-687. They're NOT actuals; PA AFR is a separate cycle and
covered by a sibling extractor TBD.

Crosswalk:
  Master state_leaid format: 'PA-{9-digit-AUN}' (e.g. 'PA-101260303')
  GFB AUN column:            9-digit AUN (e.g. 101260303)
  → strip 'PA-'.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
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

EXTRACTOR_NAME = "pa"
STATE = "PA"
BUCKET = "pa"
SOURCE_PORTAL_URL = (
    "https://www.pa.gov/agencies/education/programs-and-services/schools/"
    "grants-and-funding/school-finances/financial-data/general-fund-budget-gfb-data"
)
PUBLISHER = "Pennsylvania Department of Education"
DOCUMENT_TYPE = "pde_gfb_xlsx"
TOPLINE_DEFINITION = (
    "PDE General Fund Budget, FB_Cert sheet, TotalExpAmount column "
    "(certified total adopted operating expenditure budget per district)"
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"


def _fy_full(fiscal_year: int) -> str:
    """2026 → '2025-26'."""
    return f"{fiscal_year - 1:04d}-{fiscal_year % 100:02d}"


def file_url(fiscal_year: int) -> str:
    return (
        "https://www.pa.gov/content/dam/copapwp-pagov/en/education/documents/"
        "schools/grants-and-funding/school-finances/finances/gfbdata/"
        f"{_fy_full(fiscal_year)}gfbdata.xlsx"
    )


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_fb_cert(xlsx_bytes: bytes) -> list[dict]:
    """Read FB_Cert sheet, return rows for InstCat='01' (school districts)."""
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    if "FB_Cert" not in wb.sheetnames:
        raise RuntimeError(f"FB_Cert sheet not found; sheets={wb.sheetnames}")
    ws = wb["FB_Cert"]
    out: list[dict] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        if not row or len(row) < 6:
            continue
        cat, aun, name, county = row[0], row[1], row[2], row[3]
        if cat != "01" or not aun:
            continue
        try:
            total_exp = float(row[5]) if row[5] is not None else None
        except (TypeError, ValueError):
            total_exp = None
        if total_exp is None or total_exp <= 0:
            continue
        out.append({
            "aun": str(aun),
            "name": name,
            "county": county,
            "total_exp": total_exp,
        })
    return out


def build_pa_crosswalk(client: Client) -> dict[str, dict]:
    """9-digit AUN → district row."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("PA-"):
            out[sl.removeprefix("PA-")] = r
    return out


def extract(*, fiscal_year: int = 2026, triggered_by: str = "manual") -> dict:
    print(f"PA extract: fiscal_year={fiscal_year}")

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

        storage_relpath = f"fy{fiscal_year}/gfb_data.xlsx"

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
                "Sheet 'FB_Cert'; filter InstCat='01'; "
                "match AUN == state_leaid suffix; topline = TotalExpAmount"
            ),
            notes=(
                f"FY{fiscal_year} adopted GFB; one bulk file covers ~500 PA "
                "school districts. IU (Intermediate Unit) data on separate "
                "sheets; not extracted here."
            ),
        )

        crosswalk = build_pa_crosswalk(client)
        print(f"  PA crosswalk: {len(crosswalk):,} state→NCES mappings")

        gfb_rows = parse_fb_cert(xlsx_bytes)
        print(f"  GFB FB_Cert districts: {len(gfb_rows):,}")

        no_match: list[str] = []
        for row in gfb_rows:
            district = crosswalk.get(row["aun"])
            if district is None:
                no_match.append(row["aun"])
                continue

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="adopted",
                topline_amount=row["total_exp"],
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
            f"unmatched AUNs: {len(no_match)}"
        )
        if no_match[:5]:
            print(f"  sample unmatched: {no_match[:5]}")

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2026,
                   help="GFB file FY (latest as of 2026-05-05: 2026 = SY 2025-26)")
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
