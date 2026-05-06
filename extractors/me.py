"""Maine extractor — Maine DOE Resident Expenditures by Budget Category PDF.

Source: https://www.maine.gov/doe/funding/reports/expenditures
File: 'School Finance - FY{YY} Resident Expenditure Totals - {date}.pdf'
      Maine DOE Bureau of Finance publishes annually after FY-end.

What this gives us:
  - Per-SAU expenditures across 11 budget categories: Regular
    Instruction, Special Ed Instruction, Other Instruction, Career &
    Tech Instruction, Student & Staff Support, System Administration,
    School Administration, Transportation, Operations & Maintenance,
    Debt Service, All Other; plus a Total column.

Topline definition:
  Per-row Total minus Debt Service column. Aligned with F-33 'current
  expenditures' frame; excludes debt service principal/interest, but
  retains capital-style spending that ME bundles into Operations &
  Maintenance.

Status: `actual` — post-AFR audited.

Crosswalk:
  Master state_leaid format: 'ME-{numeric}' (variable-length integer)
  PDF ORG ID:                integer prefix on row (e.g. '1761Acadia Academy')
  → state_leaid suffix == ORG_ID directly.
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

EXTRACTOR_NAME = "me"
STATE = "ME"
BUCKET = "me"
SOURCE_PORTAL_URL = "https://www.maine.gov/doe/funding/reports/expenditures"
PUBLISHER = "Maine Department of Education (Bureau of Finance)"
DOCUMENT_TYPE = "me_doe_resident_expenditure_totals_pdf"
TOPLINE_DEFINITION = (
    "Maine DOE 'Resident Expenditures by Budget Category - Total "
    "Amounts' PDF; per-SAU row Total minus Debt Service column. "
    "Aligned with F-33 'current expenditures' frame."
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

KNOWN_FILE_URLS: dict[int, str] = {
    # FY25 = SY 2024-25; published Jan 2026.
    2025: "https://www.maine.gov/doe/sites/maine.gov.doe/files/inline-files/School%20Finance%20-%20FY25%20Resident%20Expenditure%20Totals%20-%201.7.2026.pdf",
}

# Row format: ORG_ID then SAU name (concatenated, no space) then 12 dollar amounts
# The 12 values are: Regular Instr, Special Ed, Other Instr, Career&Tech,
# Student/Staff, System Admin, School Admin, Transportation, Ops&Maint,
# Debt Service, All Other, Total. We need Total - Debt Service.
ROW_RE = re.compile(
    r"^(\d{1,4})([A-Z][A-Za-z'.\s\-/]*?)\s+"
    + r"\s+".join([r"\$([\-\d,\.]+)"] * 12)
    + r"\s*$",
    re.MULTILINE,
)


def _normalize(name: str) -> str:
    n = re.sub(
        r"\s+(School Department|Public Schools|Public School District|"
        r"School District|Schools|Department|District|Academy|CSD|MSAD|RSU)$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    n = re.sub(r"\s+", " ", n).strip().upper()
    return n


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_me(pdf_bytes: bytes) -> list[dict]:
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    out: list[dict] = []
    seen_codes: set[str] = set()
    for page in pdf.pages:
        text = page.extract_text() or ""
        for m in ROW_RE.finditer(text):
            org_id = m.group(1)
            sau_name = m.group(2).strip()
            if sau_name.upper() == "STATE TOTAL":
                continue
            if org_id in seen_codes:
                continue
            # Capture groups: 1=ORG_ID, 2=SAU name, 3..14 = 12 dollar amounts
            # The 10th amount is Debt Service (group 12); the 12th is Total (group 14).
            try:
                debt_service = float(m.group(12).replace(",", ""))
                total = float(m.group(14).replace(",", ""))
            except ValueError:
                continue
            op_total = total - debt_service
            if op_total <= 0:
                continue
            seen_codes.add(org_id)
            out.append({
                "code": org_id,
                "name": sau_name,
                "total_op_exp": op_total,
            })
    pdf.close()
    return out


def build_me_crosswalk(client: Client) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (by_code, by_normalized_name)."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    by_code: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("ME-"):
            by_code[sl.removeprefix("ME-")] = r
        name = r.get("lea_name") or ""
        if name:
            by_name[_normalize(name)] = r
    return by_code, by_name


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"ME extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No ME DOE URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1].split('%')[0]}...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/resident_expenditure_totals.pdf"

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
                "Per-row Total minus Debt Service column from PDF table; "
                "match ORG_ID prefix == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} ME DOE Resident Expenditure Totals",
        )

        by_code, by_name = build_me_crosswalk(client)
        print(f"  ME crosswalk: {len(by_code):,} by code, {len(by_name):,} by name")

        district_data = parse_me(pdf_bytes)
        print(f"  ME PDF SAUs: {len(district_data):,}")

        no_match: list[str] = []
        for d in district_data:
            district = by_code.get(d["code"])
            if district is None:
                # Fall back to name match
                district = by_name.get(_normalize(d["name"]))
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
            f"unmatched ME ORG IDs: {len(no_match)}"
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
