"""Florida AFR extractor — FLDOE Annual Financial Reports (audited actuals).

Source: https://www.fldoe.org/finance/fl-edu-finance-program-fefp/
        school-dis-annual-financial-reports-af.stml

URL pattern: https://www.fldoe.org/file/7507/{shortcode}afr{County}.pdf
            (e.g. 2425afrDade.pdf for FY24-25 Miami-Dade)

What this gives us:
  - General Fund TOTAL EXPENDITURES per FL county district per fiscal year
    (audited actuals, typically published in January of the following year).

Topline definition:
  Statement of Revenues, Expenditures and Changes in Fund Balance —
  General Fund 100, "TOTAL EXPENDITURES 0000" first amount column. This is
  the same definition the legacy step-2 extractor used and matches F-33
  'current expenditures'.

Status: `actual` (audited).

Companion to extractors/fl.py (which handles the Summary BUDGET portal —
adopted budgets, status='adopted'). This module handles ACTUALS — different
document, different status. Keeping them as sibling files keeps each
extractor's intent clear and the cron runner can call them independently.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from io import BytesIO

import pdfplumber
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
from extractors.fl import COUNTY_TO_LEA_NAME, FL_COUNTIES

EXTRACTOR_NAME = "fl_afr"
STATE = "FL"
BUCKET = "fl"
SOURCE_PORTAL_URL = (
    "https://www.fldoe.org/finance/fl-edu-finance-program-fefp/"
    "school-dis-annual-financial-reports-af.stml"
)
FILE_URL_TEMPLATE = "https://www.fldoe.org/file/7507/{shortcode}afr{county}.pdf"
PUBLISHER = "Florida Department of Education"
DOCUMENT_TYPE = "annual_financial_report_pdf"
TOPLINE_DEFINITION = (
    "FLDOE Annual Financial Report Statement of Revenues, Expenditures and "
    "Changes in Fund Balance — General Fund 100, TOTAL EXPENDITURES 0000 "
    "(first amount column)"
)

# `TOTAL EXPENDITURES 0000 X,XXX,XXX,XXX.XX ...` — first dollar amount
TOTAL_EXP_RE = re.compile(
    r"^TOTAL\s+EXPENDITURES\s+0000\s+([\d,]+\.\d{2})", re.MULTILINE
)


def fy_short(fiscal_year: int) -> str:
    """2025 → '2425'."""
    start = fiscal_year - 1
    return f"{start % 100:02d}{fiscal_year % 100:02d}"


def build_county_to_district(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    by_upper = {row["lea_name"].upper(): row for row in rows}
    out: dict[str, dict] = {}
    for county in FL_COUNTIES:
        keyword = COUNTY_TO_LEA_NAME.get(county, county.upper())
        match = next(
            (row for name, row in by_upper.items() if keyword in name),
            None,
        )
        if match is not None:
            out[county] = match
    return out


def download_pdf(county: str, shortcode: str) -> bytes | None:
    candidates = [
        FILE_URL_TEMPLATE.format(county=county, shortcode=shortcode),
        FILE_URL_TEMPLATE.format(county=county.lower(), shortcode=shortcode),
    ]
    for url in candidates:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "school-budget-tracker/0.1"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    data = resp.read()
                    if len(data) > 1024:
                        return data
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    return None


def parse_general_fund_total_expenditures(pdf_bytes: bytes) -> tuple[float | None, int | None]:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages[:30]):
            text = page.extract_text() or ""
            upper = text.upper()
            if "GENERAL FUND" not in upper or "TOTAL EXPENDITURES" not in upper:
                continue
            m = TOTAL_EXP_RE.search(text)
            if m:
                return float(m.group(1).replace(",", "")), i + 1
    return None, None


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    shortcode = fy_short(fiscal_year)
    print(f"FL AFR extract: fiscal_year={fiscal_year} (shortcode {shortcode})")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        crosswalk = build_county_to_district(client)
        print(f"  matched {len(crosswalk)}/{len(FL_COUNTIES)} counties to districts")

        downloaded = 0
        not_published: list[str] = []
        parse_failed: list[str] = []
        no_match: list[str] = []

        for county in FL_COUNTIES:
            if county not in crosswalk:
                no_match.append(county)
                continue

            pdf_bytes = download_pdf(county, shortcode)
            if pdf_bytes is None:
                not_published.append(county)
                continue
            downloaded += 1

            topline, page_num = parse_general_fund_total_expenditures(pdf_bytes)
            if topline is None:
                parse_failed.append(county)
                continue

            content_hash = sha256_bytes(pdf_bytes)
            storage_relpath = f"fy{fiscal_year}/afr/{county}{shortcode}afr.pdf"
            file_url = FILE_URL_TEMPLATE.format(county=county, shortcode=shortcode)

            existing_src = (
                client.table("source_documents")
                .select("id")
                .eq("content_hash_sha256", content_hash)
                .execute()
            )
            if not existing_src.data:
                upload_source_document(
                    client=client,
                    bucket=BUCKET,
                    storage_path=storage_relpath,
                    content=pdf_bytes,
                    mime_type="application/pdf",
                )

            src_id = upsert_source_document_row(
                client=client,
                content_hash=content_hash,
                source_url=file_url,
                storage_path=f"{BUCKET}/{storage_relpath}",
                mime_type="application/pdf",
                publisher=PUBLISHER,
                document_type=DOCUMENT_TYPE,
                page_number=page_num,
                line_or_cell_reference=(
                    "Statement of Revenues, Expenditures and Changes in Fund "
                    "Balance — General Fund 100, TOTAL EXPENDITURES 0000 row"
                ),
                notes=f"FY{fiscal_year} audited actuals AFR PDF",
            )

            row = crosswalk[county]
            event = BudgetEventInput(
                leaid=row["leaid"],
                fiscal_year=fiscal_year,
                status="actual",
                topline_amount=topline,
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
            f"  downloaded={downloaded}  inserted/changed={run.records_changed}  "
            f"no-match={len(no_match)}  not-published={len(not_published)}  "
            f"parse-failed={len(parse_failed)}"
        )
        if not_published:
            print(f"  not on FLDOE: {not_published}")
        if parse_failed:
            print(f"  parse failed: {parse_failed}")
        if no_match:
            print(f"  no district match: {no_match}")

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "not_published": not_published,
        "parse_failed": parse_failed,
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
