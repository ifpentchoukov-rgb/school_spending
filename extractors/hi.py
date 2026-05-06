"""Hawaii extractor — HIDOE Annual Financial and Single Audit (AFSA).

Hawaii is the only state with a single statewide school district. The
HI Department of Education publishes an Annual Financial and Single
Audit (AFSA) PDF each fall covering the prior FY. The 'Statement of
Revenues, Expenditures, and Changes in Fund Balances – Governmental
Funds' page (typically p17) has clean per-program expenditure totals.

Source: https://hawaiipublicschools.org/data-reports/annual-financial-and-single-audit/
File: AFSA{YYYY}.pdf — fiscal_year = FY-end calendar year.

Topline definition:
  Statement of Revenues, Expenditures, and Changes in Fund Balances –
  Governmental Funds: 'School-related' Total + 'State and complex area
  administration' Total. Excludes 'Capital outlay' and 'Public
  libraries' (libraries are bundled into HIDOE but separate from F-33
  K-12 frame). Aligned with F-33 'current expenditures' frame.

Status: `actual` — independent CPA audit.

Crosswalk:
  Master state_leaid format: 'HI-001' (single statewide district)
  PDF: no LEA code — the entire AFSA is for HIDOE.
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

EXTRACTOR_NAME = "hi"
STATE = "HI"
BUCKET = "hi"
SOURCE_PORTAL_URL = "https://hawaiipublicschools.org/data-reports/annual-financial-and-single-audit/"
PUBLISHER = "Hawaii State Department of Education"
DOCUMENT_TYPE = "hidoe_afsa_pdf"
TOPLINE_DEFINITION = (
    "HIDOE Annual Financial and Single Audit (AFSA) PDF, Statement of "
    "Revenues, Expenditures, and Changes in Fund Balances – "
    "Governmental Funds: 'School-related' Total + 'State and complex "
    "area administration' Total. Excludes Capital outlay and Public "
    "libraries. Aligned with F-33 'current expenditures' frame."
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

KNOWN_FILE_URLS: dict[int, str] = {
    # AFSA{YYYY}.pdf — published fall of FY-end year.
    2025: "https://hawaiipublicschools.org/wp-content/uploads/AFSA2025.pdf",
    2024: "https://hawaiipublicschools.org/wp-content/uploads/AFSA2024.pdf",
}

# Patterns to match the per-program 'Total' line from the Governmental
# Funds Statement. Each program row has 5 columns (General + Federal +
# Capital Projects + Other + Total); a column may be '-' (dash) when
# zero. The last column is the row total across all funds.
_FIELD = r"(?:\$?\s*[\d,]+(?:\.\d+)?|-)"
_LAST_FIELD = r"\$?\s*([\d,]+(?:\.\d+)?)"
SCHOOL_RELATED_RE = re.compile(
    r"School-related\s+" + (_FIELD + r"\s+") * 4 + _LAST_FIELD
)
ADMIN_RE = re.compile(
    r"State and complex area administration\s+" + (_FIELD + r"\s+") * 4 + _LAST_FIELD
)


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_afsa(pdf_bytes: bytes) -> float:
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    school_total: float | None = None
    admin_total: float | None = None
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "Statement of Revenues, Expenditures" not in text:
            continue
        if "Governmental Funds" not in text:
            continue
        m1 = SCHOOL_RELATED_RE.search(text)
        m2 = ADMIN_RE.search(text)
        if m1 and m2:
            try:
                school_total = float(m1.group(1).replace(",", ""))
                admin_total = float(m2.group(1).replace(",", ""))
            except ValueError:
                continue
            break
    pdf.close()
    if school_total is None or admin_total is None:
        raise RuntimeError("Could not locate School-related and admin totals in AFSA PDF")
    return school_total + admin_total


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


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"HI extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No AFSA URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/afsa.pdf"

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
                "Statement of Revenues, Expenditures, and Changes in Fund "
                "Balances – Governmental Funds; School-related Total col + "
                "State and complex area administration Total col"
            ),
            notes=f"FY{fiscal_year} HIDOE AFSA",
        )

        district = build_hi_crosswalk(client)
        print(f"  HI single statewide district: {district['lea_name']}")

        total_op_exp = parse_afsa(pdf_bytes)
        print(f"  HI FY{fiscal_year} operating expenditure: ${total_op_exp:,.0f}")

        event = BudgetEventInput(
            leaid=district["leaid"],
            fiscal_year=fiscal_year,
            status="actual",
            topline_amount=total_op_exp,
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
    p.add_argument("--fiscal-year", type=int, default=2025)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
