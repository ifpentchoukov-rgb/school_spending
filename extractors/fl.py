"""Florida extractor — FLDOE District Summary Budget portal.

Source: https://www.fldoe.org/finance/fl-edu-finance-program-fefp/
        school-dis-summary-budget.stml

URL pattern: https://www.fldoe.org/file/7507/{County}TotalBUD{YYYY}.pdf
            (one PDF per FL county district per fiscal year)

What this gives us:
  - Adopted operating budgets for the 67 FL county districts
  - Historical: FY09-10 through latest published year
  - As of 2026-05-04: latest is FY 2025-26 (filename code '2526'); FY 2026-27
    ('2627') will appear after the Sept 30 statutory submission deadline.

Topline definition:
  Section II. GENERAL FUND 100, "TOTAL APPROPRIATIONS" — first column
  (the "Total" column, which sums Salaries / Benefits / Services / Materials
  / Capital / Other across all functions). This is the operating spend
  budgeted for the General Fund and is comparable to the AFR's General Fund
  TOTAL EXPENDITURES that the legacy fl.py extracted.

Status:
  These are submissions of the BOARD-ADOPTED budget to FLDOE — `status='adopted'`.
  Proposed/tentative versions are NOT on FLDOE; they live in district board-
  meeting agendas. Per-district board-portal scraping is queued as Phase 6 work.

What this does NOT give us:
  - Lab schools (FAU, FSU, etc.), Florida Virtual School, charter LEAs that
    file separately (e.g. IDEA Public Schools). These don't appear on the
    FLDOE Summary Budget portal.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pdfplumber
from supabase import Client

from extractors._base import (
    BudgetEventInput,
    Run,
    get_prior_year_baseline,
    sha256_bytes,
    upload_source_document,
    upsert_budget_event_with_supersession,
    upsert_source_document_row,
)

EXTRACTOR_NAME = "fl"
STATE = "FL"
BUCKET = "fl"
SOURCE_PORTAL_URL = (
    "https://www.fldoe.org/finance/fl-edu-finance-program-fefp/"
    "school-dis-summary-budget.stml"
)
FILE_URL_TEMPLATE = "https://www.fldoe.org/file/7507/{county}TotalBUD{shortcode}.pdf"
TOPLINE_DEFINITION = (
    "FLDOE District Summary Budget Section II. GENERAL FUND 100, "
    "TOTAL APPROPRIATIONS (Total column)"
)
PUBLISHER = "Florida Department of Education"
DOCUMENT_TYPE = "summary_budget_pdf"

# County labels as they appear in FLDOE filenames. Source: legacy/sd_tracker_step2/scripts/extractors/fl.py
FL_COUNTIES: list[str] = [
    "Alachua", "Baker", "Bay", "Bradford", "Brevard", "Broward",
    "Calhoun", "Charlotte", "Citrus", "Clay", "Collier", "Columbia",
    "Dade", "Desoto", "Dixie", "Duval", "Escambia", "Flagler",
    "Franklin", "Gadsden", "Gilchrist", "Glades", "Gulf", "Hamilton",
    "Hardee", "Hendry", "Hernando", "Highlands", "Hillsborough",
    "Holmes", "IndianRiver", "Jackson", "Jefferson", "Lafayette",
    "Lake", "Lee", "Leon", "Levy", "Liberty", "Madison", "Manatee",
    "Marion", "Martin", "Monroe", "Nassau", "Okaloosa", "Okeechobee",
    "Orange", "Osceola", "PalmBeach", "Pasco", "Pinellas", "Polk",
    "Putnam", "StJohns", "StLucie", "SantaRosa", "Sarasota", "Seminole",
    "Sumter", "Suwannee", "Taylor", "Union", "Volusia", "Wakulla",
    "Walton", "Washington",
]

# Map FLDOE county filename → CCD lea_name keyword for crosswalk.
COUNTY_TO_LEA_NAME: dict[str, str] = {
    "Dade": "MIAMI-DADE",
    "PalmBeach": "PALM BEACH",
    "IndianRiver": "INDIAN RIVER",
    "StJohns": "ST. JOHNS",
    "StLucie": "ST. LUCIE",
    "SantaRosa": "SANTA ROSA",
    "Desoto": "DESOTO",
}

TOTAL_APPROPRIATIONS_RE = re.compile(
    r"^TOTAL\s+APPROPRIATIONS\s+([\d,]+\.\d{2})", re.MULTILINE
)


def fy_short(fiscal_year: int) -> str:
    """2026 → '2526'. (FY26 = school year 2025-26.)"""
    start = fiscal_year - 1
    return f"{start % 100:02d}{fiscal_year % 100:02d}"


def build_county_to_district(client: Client) -> dict[str, dict]:
    """Map county filename → {leaid, lea_name, state_leaid} via the districts table."""
    fl = (
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
        .execute()
    ).data
    by_upper = {row["lea_name"].upper(): row for row in fl}

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
    """Try lowercase and original .pdf/.PDF variants; return content or None."""
    candidates = [
        FILE_URL_TEMPLATE.format(county=county, shortcode=shortcode),
        FILE_URL_TEMPLATE.format(county=county, shortcode=shortcode).replace(
            ".pdf", ".PDF"
        ),
    ]
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "school-budget-tracker/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    data = resp.read()
                    if len(data) > 1024:
                        return data
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    return None


def parse_general_fund_total_appropriations(pdf_bytes: bytes) -> tuple[float | None, int | None]:
    """Return (topline_amount, page_number) — page number is 1-indexed."""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages[:30]):
            text = page.extract_text() or ""
            upper = text.upper()
            if "GENERAL FUND" not in upper or "TOTAL APPROPRIATIONS" not in upper:
                continue
            m = TOTAL_APPROPRIATIONS_RE.search(text)
            if m:
                return float(m.group(1).replace(",", "")), i + 1
    return None, None


def extract(*, fiscal_year: int = 2026, triggered_by: str = "manual") -> dict:
    shortcode = fy_short(fiscal_year)
    print(f"FL extract: fiscal_year={fiscal_year} (shortcode {shortcode})")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        crosswalk = build_county_to_district(client)
        print(f"  matched {len(crosswalk)}/{len(FL_COUNTIES)} counties to districts")

        downloaded = 0
        parse_failed: list[str] = []
        not_published: list[str] = []
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

            topline, page_num = parse_general_fund_total_appropriations(pdf_bytes)
            if topline is None:
                parse_failed.append(county)
                continue

            content_hash = sha256_bytes(pdf_bytes)
            storage_relpath = f"fy{fiscal_year}/{county}TotalBUD{shortcode}.pdf"
            file_url = FILE_URL_TEMPLATE.format(county=county, shortcode=shortcode)

            existing_src = (
                client.table("source_documents")
                .select("id, storage_path")
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
                line_or_cell_reference="Section II. GENERAL FUND 100, TOTAL APPROPRIATIONS row, first amount column",
                notes=f"FY{fiscal_year} adopted budget submitted to FLDOE",
            )

            row = crosswalk[county]
            prior_actual = get_prior_year_baseline(client, row["leaid"], fiscal_year)
            yoy_pct = None
            yoy_dollars = None
            if prior_actual:
                yoy_dollars = topline - prior_actual
                yoy_pct = yoy_dollars / prior_actual * 100

            event = BudgetEventInput(
                leaid=row["leaid"],
                fiscal_year=fiscal_year,
                status="adopted",
                topline_amount=topline,
                topline_definition=TOPLINE_DEFINITION,
                source_document_id=src_id,
                extraction_run_id=run.run_id,
                yoy_change_pct=yoy_pct,
                yoy_change_dollars=yoy_dollars,
                prior_year_baseline=prior_actual,
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
    p.add_argument("--fiscal-year", type=int, default=2026)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
