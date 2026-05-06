"""Alabama extractor — ALSDE System Level Per-Pupil Expenditures PDF.

Source: https://www.alabamaachieves.org/reports-data/financial-reports/
File: RD_FR_{YYYYMMDD}_System-Level-Per-Pupil-Expenditures-FY{YYYY}_V1.0.pdf
      Published annually around August following AL FY-end (Sept 30).
      Each district gets one page with a funding-source × expenditure
      category matrix and a 'Total' summary row.

What this gives us:
  - Per-LEA total expenditures across instructional, support,
    operations, transportation, food service, and preschool services
    for all ~148 AL operating LEAs (county systems + city systems +
    Alabama School Districts/Specialized Centers).

Topline definition:
  Per-page 'Total' row, last column — sum of all funding-source rows
  across all expenditure categories. Includes Federal + State + Local +
  Local Sch + Other revenue-sourced spending. Aligned with F-33
  'current expenditures' frame; ALSDE excludes capital outlay and debt
  service from this PPE report.

Status: `actual` — post-AFR audited (ALSDE publishes from district
Annual Financial Reports filed under Code of Alabama § 16-13A).

Alabama school FY = Oct 1 - Sept 30 (state fiscal year, per migration
0006). FY2023 = Oct 2022 - Sept 2023. Latest publication as of 2026-05-06
is FY2023 (PDF dated 2024-08-26); FY2024 PDF expected late 2025 to
mid-2026 but not yet posted.

Crosswalk:
  Master state_leaid format: 'AL-{3-digit}' (e.g. 'AL-001' Autauga County)
  PDF system code:           3-digit string at start of district header
                             (e.g. '001 Autauga County PK-12')
  → strip AL- prefix == system code directly.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import urllib.error
import urllib.request

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

EXTRACTOR_NAME = "al"
STATE = "AL"
BUCKET = "al"
SOURCE_PORTAL_URL = "https://www.alabamaachieves.org/reports-data/financial-reports/"
PUBLISHER = "Alabama State Department of Education (LEA Accounting)"
DOCUMENT_TYPE = "alsde_system_level_ppe_pdf"
TOPLINE_DEFINITION = (
    "ALSDE System Level Per-Pupil Expenditures PDF, per-district 'Total' "
    "row last column — sum across funding sources × expenditure "
    "categories (Instructional, Instructional Support, Student Services, "
    "Staff Support, School Admin, Operations & Maintenance, "
    "Transportation, General Admin, Food Service, Preschool, Services). "
    "Aligned with F-33 'current expenditures' frame; excludes capital "
    "outlay and debt service."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

KNOWN_FILE_URLS: dict[int, str] = {
    # AL FY2023 = Oct 2022 - Sept 2023; published Aug 2024.
    2023: (
        "https://www.alabamaachieves.org/wp-content/uploads/2024/08/"
        "RD_FR_20240826_System-Level-Per-Pupil-Expenditures-FY2023_V1.0.pdf"
    ),
}

# District header line: "{3-digit code} {Name with K-12 grade band}"
# E.g. "001 Autauga County PK-12", "101 Albertville City PK-12"
HEADER_RE = re.compile(r"^(\d{3})\s+(.+?)\s+(?:PK|K)-12\s*$", re.MULTILINE)
# Total row: "Total {amounts...} {grand_total}"
TOTAL_RE = re.compile(r"^\s*Total\s+([\d,\s]+?)\s*$", re.MULTILINE)


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_ppe_pdf(pdf_bytes: bytes) -> list[dict]:
    """Return [{code, name, total_op_exp}], one record per district page."""
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    out: list[dict] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        h = HEADER_RE.search(text)
        t = TOTAL_RE.search(text)
        if not h or not t:
            continue
        code = h.group(1)
        name = h.group(2).strip()
        # The Total row's last whitespace-separated token is the grand total
        nums = t.group(1).split()
        if not nums:
            continue
        try:
            grand_total = float(nums[-1].replace(",", ""))
        except ValueError:
            continue
        if grand_total <= 0:
            continue
        out.append({"code": code, "name": name, "total_op_exp": grand_total})
    pdf.close()
    return out


def build_al_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("AL-"):
            out[sl.removeprefix("AL-")] = r
    return out


def extract(*, fiscal_year: int = 2023, triggered_by: str = "manual") -> dict:
    print(f"AL extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No ALSDE PPE URL for fiscal_year={fiscal_year}; "
                "add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/system_level_ppe.pdf"

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
                content=pdf_bytes,
                mime_type="application/pdf",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/pdf",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "One page per district; topline = 'Total' row last column "
                "(grand total across funding sources × expenditure "
                "categories); match 3-digit code in district header == "
                "state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} ALSDE System Level Per-Pupil Expenditures",
        )

        crosswalk = build_al_crosswalk(client)
        print(f"  AL crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_ppe_pdf(pdf_bytes)
        print(f"  ALSDE PDF districts: {len(district_data):,}")

        no_match: list[str] = []
        for d in district_data:
            district = crosswalk.get(d["code"])
            if district is None:
                no_match.append(f"{d['code']} {d['name']}")
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
            f"unmatched ALSDE codes: {len(no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2023)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
