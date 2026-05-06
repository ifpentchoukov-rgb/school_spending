"""Montana extractor — OPI School Expenditures (OPIEXP) per-LE detail.

Source: https://opi.mt.gov/Leadership/Finance-Grants/School-Finance/OPI-Financial-Data-Files
File: OPIEXP{YY}.xlsx — one sheet per pivot view; sheet
'ExpByLineItemByLE' has detail rows by County × LE × Fund × Program ×
Function × Object.

What this gives us:
  - Per-LE expenditure detail across ~418 Montana LE codes (much
    larger than master's 64 K-12-equivalent districts; the rest are
    small elementary-only or HS-only LEs not in master).

Topline definition:
  Sheet 'ExpByLineItemByLE': sum of SumOfAmount per LE where
  FunctionCode starts with '1', '2', or '3' (Instruction, Support
  Services, Non-Instructional). Excludes Function 4XXX (Facilities
  Acquisition / Capital) and 5XXX (Debt Service / Other Outlays).
  Aligned with F-33 'current expenditures' frame.

Status: `actual` — post-AFR audited.

Crosswalk:
  Master state_leaid format: 'MT-{4-digit}' (only K-12 equivalents)
  XLSX LE col:               4-digit string (e.g. '0003')
  → state_leaid suffix == LE directly.

Note: MT has many elementary-only and HS-only LEs that share
boundaries with a master K-12 district; these don't have a 1:1 match
and won't be captured here. Master coverage is the K-12 set only.
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

EXTRACTOR_NAME = "mt"
STATE = "MT"
BUCKET = "mt"
SOURCE_PORTAL_URL = "https://opi.mt.gov/Leadership/Finance-Grants/School-Finance/OPI-Financial-Data-Files"
PUBLISHER = "Montana Office of Public Instruction"
DOCUMENT_TYPE = "mt_opi_expenditures_xlsx"
TOPLINE_DEFINITION = (
    "OPI School Expenditures (OPIEXP) workbook, sheet "
    "'ExpByLineItemByLE': sum of SumOfAmount per LE where Function "
    "code starts with 1, 2, or 3 (Instruction + Support Services + "
    "Non-Instructional). Excludes Function 4XXX (Capital) and 5XXX "
    "(Debt). Aligned with F-33 'current expenditures' frame."
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

KNOWN_FILE_URLS: dict[int, str] = {
    2025: "https://opi.mt.gov/Portals/182/Page%20Files/School%20Finance/OPI%20Financial%20Data%20Files/School%20Budget%20and%20Expenditure%20Data/School%20Expenditures/School%20Expenditures/OPIEXP25.xlsx?ver=2026-02-18-062820-677",
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_mt(xlsx_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb["ExpByLineItemByLE"]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # row 0: total
    next(rows)  # row 1: header
    totals: dict[str, float] = {}
    for r in rows:
        if not r or r[2] is None:
            continue
        le = str(r[2]).strip()
        if not le:
            continue
        func_code = str(r[9]) if r[9] is not None else ""
        if not func_code or func_code[0] not in ("1", "2", "3"):
            continue
        amt = r[13]
        if amt is None:
            continue
        try:
            v = float(amt)
        except (TypeError, ValueError):
            continue
        totals[le] = totals.get(le, 0.0) + v
    return [
        {"code": code, "total_op_exp": v}
        for code, v in totals.items()
        if v > 0
    ]


def build_mt_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("MT-"):
            out[sl.removeprefix("MT-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"MT extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No OPI URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading OPIEXP{fiscal_year - 2000}.xlsx...")
        xlsx_bytes = download(url)
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.1f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/expenditures.xlsx"

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
                "Sheet 'ExpByLineItemByLE'; sum SumOfAmount per LE "
                "where FunctionCode[0] in (1,2,3); match LE == "
                "state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} OPI School Expenditures (OPIEXP)",
        )

        crosswalk = build_mt_crosswalk(client)
        print(f"  MT crosswalk: {len(crosswalk):,} state→NCES mappings (K-12 only)")

        district_data = parse_mt(xlsx_bytes)
        print(f"  MT LEs in file: {len(district_data):,}")

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
            f"unmatched MT LEs (elementary-only/HS-only not in master): {len(no_match)}"
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
