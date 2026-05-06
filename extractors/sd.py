"""South Dakota extractor — SD DOE All Expenditures workbook.

Source: https://doe.sd.gov/ofm/schfinance.aspx
File: 25-AllExpend.xlsx — SD DOE Office of Finance and Management
publishes annually after AFR submissions close.

What this gives us:
  - Per-district FY{YYYY} expenditures across General Fund (10),
    Capital Outlay (21), and Special Education (22) funds. Sheet has
    one row per district with Expenditures, Fund Balance, and Fund
    Balance % columns for each fund.

Topline definition:
  General Fund/Impact Aid Combined Expenditures (col 5) + Special
  Education (22) Expenditures (col 11). Excludes Capital Outlay (21)
  per F-33 'current expenditures' frame.

Status: `actual` — post-AFR audited.

Crosswalk:
  Master state_leaid format: 'SD-{5-digit}' (e.g. 'SD-06001' Aberdeen)
  XLSX District Number:      integer (e.g. 6001 = 06-001)
  → state_leaid suffix == zfill(district_number, 5).
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

EXTRACTOR_NAME = "sd"
STATE = "SD"
BUCKET = "sd"
SOURCE_PORTAL_URL = "https://doe.sd.gov/ofm/schfinance.aspx"
PUBLISHER = "South Dakota Department of Education (Office of Finance and Management)"
DOCUMENT_TYPE = "sd_doe_all_expend_xlsx"
TOPLINE_DEFINITION = (
    "SD DOE All Expenditures workbook, sheet 'Exp&FB' — General "
    "Fund/Impact Aid Combined Expenditures + Special Education (22) "
    "Expenditures per district. Excludes Capital Outlay (21). Aligned "
    "with F-33 'current expenditures' frame."
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

KNOWN_FILE_URLS: dict[int, str] = {
    # FY25 published Jan 2026.
    2025: "https://doe.sd.gov/ofm/documents/25-AllExpend.xlsx",
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_sd(xlsx_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb["Exp&FB"]
    out: list[dict] = []
    # Data starts at row 7 (0-indexed 6), which is "Aberdeen 06-1"
    for r in ws.iter_rows(min_row=7, values_only=True):
        if not r or r[0] is None or r[1] is None:
            continue
        try:
            district_num = int(r[1])
        except (TypeError, ValueError):
            continue
        # Skip aggregate rows
        if district_num <= 0:
            continue
        try:
            gen_imp = float(r[5]) if r[5] is not None else 0.0
            sped = float(r[11]) if r[11] is not None else 0.0
        except (TypeError, ValueError):
            continue
        total = gen_imp + sped
        if total <= 0:
            continue
        out.append({
            "code": f"{district_num:05d}",
            "total_op_exp": total,
        })
    return out


def build_sd_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("SD-"):
            out[sl.removeprefix("SD-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"SD extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No SD DOE URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        xlsx_bytes = download(url)
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/all_expend.xlsx"

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
                "Sheet 'Exp&FB'; col 5 (General Fund/Impact Aid Combined "
                "Expenditures) + col 11 (Special Ed Expenditures); match "
                "zfill(district_number, 5) == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} SD DOE All Expenditures workbook",
        )

        crosswalk = build_sd_crosswalk(client)
        print(f"  SD crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_sd(xlsx_bytes)
        print(f"  SD DOE districts: {len(district_data):,}")

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
            f"unmatched SD codes: {len(no_match)}"
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
