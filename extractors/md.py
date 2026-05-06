"""Maryland extractor — MSDE Selected Financial Data Part 2.

Source: https://marylandpublicschools.org/about/Pages/DBS/SFD/index.aspx
File: Selected-Financial-Data-{YYYY-YY}-Part2-A.pdf (Local Accountability
Branch, MSDE; published annually around June following FY-end).

What this gives us:
  - Per-LEA `Total Current Expense Fund` for all 24 MD LEAs (23 counties
    + Baltimore City) from Table 1 'Expenditures for All Purposes'.
    Statewide $17.47B for FY24.

Topline definition:
  Table 1 col 'Total Current Expense Fund' — per-LEA operating fund
  expenditures (instruction + administration + special education +
  student services + transportation + plant O&M + maintenance +
  fixed charges + community services). Excludes capital outlay,
  school construction fund, food service fund, debt service principal,
  and inter-fund transfers. Aligned with F-33 'current expenditures'
  frame.

Status: `actual` — post-AFR audited (MSDE Local Accountability Branch
publishes from Annual Financial Reports submitted by LEAs).

Crosswalk:
  Master state_leaid format: 'MD-{2-digit}' (state-assigned LEA ID)
  PDF agency name:           county short name (e.g. 'Baltimore' = Baltimore
                              County, 'Baltimore City' = Baltimore City)
  → Name match against normalize(master.lea_name) — strip
    "County Public Schools" / "City Public Schools" suffix.
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

EXTRACTOR_NAME = "md"
STATE = "MD"
BUCKET = "md"
SOURCE_PORTAL_URL = "https://marylandpublicschools.org/about/Pages/DBS/SFD/index.aspx"
PUBLISHER = "Maryland State Department of Education (Local Accountability Branch)"
DOCUMENT_TYPE = "msde_sfd_part2_pdf"
TOPLINE_DEFINITION = (
    "MSDE Selected Financial Data Part 2, Table 1 'Expenditures for "
    "All Purposes' col 'Total Current Expense Fund' — per-LEA "
    "operating fund expenditures (excludes capital outlay, food "
    "service, school construction, debt service principal, inter-fund "
    "transfers). Aligned with F-33 'current expenditures' frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

KNOWN_FILE_URLS: dict[int, str] = {
    # FY24 = SY 2023-2024; published June 2025.
    2024: (
        "https://www.marylandpublicschools.org/about/Documents/DBS/SFD/"
        "2023-2024/Selected-Financial-Data-2023-2024-Part2-A.pdf"
    ),
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


# Strip pdfplumber's spurious mid-number spaces. PDF rendering occasionally
# inserts a space after a leading single digit ("2 ,771,827" → "2,771,827",
# "1 1,388,566" → "11,388,566"). Only collapse when the digit starts a
# number (negative-lookbehind for digit/comma) so we don't merge legitimate
# inter-number spaces like "168,681,677 158,798,562".
_SPACE_FIX = re.compile(r"(?<![,\d])(\d) (?=[\d,])")


def _clean_numbers(line: str) -> str:
    return _SPACE_FIX.sub(r"\1", line)


def _normalize_name(name: str) -> str:
    """Strip 'Public Schools' suffix only — keep County/City to disambiguate
    Baltimore City vs Baltimore County."""
    n = re.sub(r"\s*Public\s+Schools\s*$", "", name, flags=re.IGNORECASE).strip()
    n = re.sub(r"\s+", " ", n).upper()
    return n


def _pdf_name_to_key(pdf_name: str) -> str:
    """PDF agency names are bare (e.g., 'Baltimore City', 'Baltimore',
    'Allegany'). Append 'County' if not already 'City'."""
    n = pdf_name.strip()
    if n.upper().endswith("CITY"):
        return n.upper()
    return f"{n} COUNTY".upper()


def parse_table1(pdf_bytes: bytes) -> list[dict]:
    """Read Table 1 from page 8 of SFD Part 2; return [{name, total_op_exp}]."""
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    out: list[dict] = []
    found_header = False
    for page in pdf.pages[:12]:
        text = page.extract_text() or ""
        if "Expenditures for All Purposes" not in text or "Current Expense" not in text:
            continue
        if "(continued)" in text:
            continue  # page 9 is the continuation
        found_header = True
        for raw_line in text.splitlines():
            line = _clean_numbers(raw_line.strip())
            if not line:
                continue
            # Match: NAME WS NUM1 NUM2 NUM3 ... where NUMs are dollar amounts
            # Skip the "Total State" row and any non-LEA rows.
            m = re.match(
                r"^([A-Z][A-Za-z'.\s]+?)\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)\s",
                line,
            )
            if not m:
                continue
            name = m.group(1).strip()
            if name.lower().startswith("total"):
                continue
            if name.lower().startswith("agency") or name.lower().startswith(
                "education"
            ):
                continue
            if "fund" in name.lower():
                continue
            try:
                # group 2 = Local Exp All Funds; group 3 = Total Current Expense Fund (topline)
                topline = float(m.group(3).replace(",", ""))
            except ValueError:
                continue
            if topline <= 0:
                continue
            out.append({"name": name, "total_op_exp": topline})
        if found_header and out:
            break
    pdf.close()
    return out


def build_md_crosswalk(client: Client) -> dict[str, dict]:
    """Map normalized lea_name → district row.

    Special-case Baltimore City vs Baltimore County: master names are
    "Baltimore City Public Schools" → key 'BALTIMORE CITY' and
    "Baltimore County Public Schools" → key 'BALTIMORE'.
    """
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        name = r.get("lea_name") or ""
        key = _normalize_name(name)
        out[key] = r
    return out


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"MD extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No MSDE SFD URL for fiscal_year={fiscal_year}; "
                "add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/sfd_part2.pdf"

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
                "Table 1 'Expenditures for All Purposes' page 8; "
                "topline = col 'Total Current Expense Fund'; "
                "match LEA name == normalize(master.lea_name)"
            ),
            notes=f"FY{fiscal_year} MSDE Selected Financial Data Part 2 (PDF)",
        )

        crosswalk = build_md_crosswalk(client)
        print(f"  MD crosswalk: {len(crosswalk):,} normalized name → master mappings")

        district_data = parse_table1(pdf_bytes)
        print(f"  parsed {len(district_data)} LEA rows from Table 1")

        no_match: list[str] = []
        for d in district_data:
            key = _pdf_name_to_key(d["name"])
            district = crosswalk.get(key)
            if district is None:
                no_match.append(d["name"])
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
            f"unmatched LEA names: {no_match}"
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
