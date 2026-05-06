"""Hawaii adopted-budget extractor — Department of Budget & Finance BIB.

Hawaii sets a biennial budget by Act of the State Legislature. The
operating budget for FY 2027 was originally enacted in Act 250, SLH
2025 (signed May 2025) covering the FY 2026-27 biennium. The Governor
submits a supplemental budget request each December for the second
year of the biennium; the 2026 Legislature then amends Act 250 to
finalize the FY 27 enacted figure.

This extractor pulls the Act 250/2025 enacted baseline from the
Budget-in-Brief (BIB) PDF — that's the legislatively-enacted FY 27
operating budget for HIDOE as of the most recent prior session. When
the 2026 Legislature passes its supplemental amendment (typically
end of May), update the URL/parse to reflect the new enacted figure.

Source: https://budget.hawaii.gov/budget/executive-supplemental-budget-fiscal-budget-2027/
File: Budget-in-Brief-FY-{YY}-BIB.{suffix}.pdf, page with the
'Department of Education / Operating Budget' table.

Topline definition:
  BIB 'Department of Education Operating Budget' table, 'Total
  Requirements' row, 'Act {NNN}/{YEAR} FY {YYYY}' column — sum across
  General + Special + Federal + Other Federal + Private Contributions
  + Trust + Interdepartmental Transfers + Revolving funds. This is
  the enacted FY operating appropriation for the entire HIDOE
  department (includes K-12 schools, Public Library System, Executive
  Office on Early Learning, School Facilities Authority, Public
  Charter School Commission, but NOT capital improvement projects).

Status: `adopted` — legislatively-enacted appropriation.

Note: NOT directly comparable to the AFSA actuals extractor
(`extractors/hi.py`) because:
  - BIB scope = full DOE department; AFSA scope = K-12 schools + admin
  - AFSA includes state-paid 'non-imposed' employee wages/fringe
    benefits (~$1.07B/year in FY25) NOT charged to the DOE appropriation
  - AFSA reports actual draw-downs of federal grants, BIB enacted only
    the planned federal grants known at enactment time

Crosswalk:
  Single statewide LEA: master 'HI-001' Hawaii Department of Education.
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

EXTRACTOR_NAME = "hi_budget"
STATE = "HI"
BUCKET = "hi"
SOURCE_PORTAL_URL = "https://budget.hawaii.gov/budget/"
PUBLISHER = "Hawaii Department of Budget and Finance"
DOCUMENT_TYPE = "hi_dbf_bib_pdf"
TOPLINE_DEFINITION = (
    "Hawaii DBF Budget-in-Brief, 'Department of Education Operating "
    "Budget' table, 'Total Requirements' row, 'Act {NNN}/{YEAR} FY "
    "{NNNN}' column — legislatively-enacted FY operating appropriation "
    "across all funding sources (general + special + federal + revolving "
    "+ trust + interdepartmental). Covers full HIDOE department incl "
    "Public Library System, EOEL, SFA, PCSC. Excludes Capital "
    "Improvement Projects."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

KNOWN_FILE_URLS: dict[int, str] = {
    # FY 2027 — BIB-27 published Dec 2025 by Gov Green; lists Act 250/2025
    # enacted baseline (column 2 of the DOE operating budget table).
    2027: "https://budget.hawaii.gov/wp-content/uploads/2025/12/Budget-in-Brief-FY-27-BIB.xApH_.pdf",
}

# Total Requirements row in DOE Operating Budget table:
#   "Total Requirements $ {ActFY26} {ActFY27} {AdjFY26} {AdjFY27} {TotalFY26} {TotalFY27}"
# All values are dollar amounts (or '-' for zero); the FY27 *enacted baseline*
# is column 2 (Act FY27).
TOTAL_REQ_RE = re.compile(
    r"Total Requirements\s*\$\s*"
    r"([\d,]+)\s+([\d,]+)\s+(\([\d,]+\)|[\d,]+|-)\s+(\([\d,]+\)|[\d,]+|-)\s+"
    r"([\d,]+)\s+([\d,]+)"
)


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_bib(pdf_bytes: bytes) -> tuple[float, int]:
    """Find the DOE Operating Budget table and return
    (act_fy27_baseline, page_number_1indexed)."""
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if "Department of Education" not in text:
            continue
        if "Operating Budget" not in text:
            continue
        m = TOTAL_REQ_RE.search(text)
        if not m:
            continue
        # group 2 is "Act {NNN}/{YEAR} FY 2027" baseline
        try:
            baseline_fy27 = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        if baseline_fy27 <= 0:
            continue
        pdf.close()
        return baseline_fy27, i + 1
    pdf.close()
    raise RuntimeError("Could not locate DOE Operating Budget Total Requirements row")


def build_hi_crosswalk(client: Client) -> dict:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    if len(rows) != 1:
        raise RuntimeError(f"Expected 1 HI master district; got {len(rows)}")
    return rows[0]


def extract(*, fiscal_year: int = 2027, triggered_by: str = "manual") -> dict:
    print(f"HI budget extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No HI BIB URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/budget_in_brief.pdf"

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

        topline, page_num = parse_bib(pdf_bytes)
        print(
            f"  HI FY{fiscal_year} adopted operating budget: ${topline:,.0f} "
            f"(BIB p{page_num}, Act 250/2025 baseline)"
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
                f"BIB p{page_num} 'Department of Education Operating "
                f"Budget' table, Total Requirements row, Act 250/2025 "
                f"FY 2027 column (legislatively-enacted baseline)"
            ),
            notes=(
                f"HI biennial budget; FY{fiscal_year} enacted in Act 250 "
                f"SLH 2025 (May 2025). Governor's supplemental amendments "
                f"pending 2026 Legislature."
            ),
        )

        district = build_hi_crosswalk(client)
        print(f"  Single statewide LEA: {district['lea_name']}")

        event = BudgetEventInput(
            leaid=district["leaid"],
            fiscal_year=fiscal_year,
            status="adopted",
            topline_amount=topline,
            topline_definition=TOPLINE_DEFINITION,
            source_document_id=src_id,
            extraction_run_id=run.run_id,
        )
        _, changed = upsert_budget_event_with_supersession(
            client=client, event=event
        )
        run.records_extracted = 1
        run.records_changed = 1 if changed else 0

        print(f"  inserted/changed={run.records_changed}/1")

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": 0,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2027)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
