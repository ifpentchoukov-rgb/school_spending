"""North Dakota extractor — NDDPI School Finance Facts PDF Section H.

Source: https://www.nd.gov/dpi/data/financial-transparency
File: 2025FinFacts.pdf (data through SY 2023-24 = FY24).
Published February of the year after FY-end.

What this gives us:
  - Per-district ADM and Average Cost Per Pupil for ~143 ND school
    districts. NDDPI defines avg cost = (regular instruction + special
    ed + CTE + federal programs + administration + plant O&M) / ADM —
    aligned with F-33 'current expenditures' frame.

Topline definition:
  Section H 'Rank Order ... by Average Cost Per Pupil':
  ADM × Average Cost = total operating expenditure per district.
  Excludes capital projects, debt service, extra-curricular,
  transportation, and 'all other'.

Status: `actual` — post-AFR audited.

Crosswalk:
  Master state_leaid format: 'ND-{5-digit}' = {2-digit county}{3-digit district}
  PDF: county and district as separate columns
  → state_leaid suffix == f'{county}{district}'
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

EXTRACTOR_NAME = "nd"
STATE = "ND"
BUCKET = "nd"
SOURCE_PORTAL_URL = "https://www.nd.gov/dpi/data/financial-transparency"
PUBLISHER = "North Dakota Department of Public Instruction (School Finance Office)"
DOCUMENT_TYPE = "nddpi_finfacts_pdf"
TOPLINE_DEFINITION = (
    "NDDPI School Finance Facts PDF Section H 'Rank Order ... by "
    "Average Cost Per Pupil': ADM × Average Cost. NDDPI's avg cost "
    "definition includes regular instruction + special ed + CTE + "
    "federal programs + administration + plant O&M (excludes capital, "
    "debt, extracurricular, transportation, all-other). Aligned with "
    "F-33 'current expenditures' frame."
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

KNOWN_FILE_URLS: dict[int, str] = {
    # 2025 FinFacts has FY24 (SY 2023-24) data.
    2024: "https://www.nd.gov/dpi/sites/www/files/documents/SFO/2025FinFacts.pdf",
}

# Match one district entry within a row.
# Format: rank county district name+# ADM AvgCost
# Example: "1 36 002 Edmore 2 17 68,691"
DIST_RE = re.compile(
    r"(\d+)\s+(\d{2})\s+(\d{3})\s+([A-Za-z][A-Za-z'.\s\-]*?\s+\d+)\s+([\d,]+)\s+([\d,]+)"
)


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_nd(pdf_bytes: bytes) -> list[dict]:
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    out: list[dict] = []
    seen: set[str] = set()
    in_section_h = False
    for page in pdf.pages:
        text = page.extract_text() or ""
        # Section H markers
        if "RANK ORDER" in text.upper() and "AVERAGE COST PER PUPIL" in text.upper():
            in_section_h = True
        if not in_section_h:
            continue
        if "Section " in text and "G - " in text:
            # Section G ended; we're past Section H
            break
        for line in text.splitlines():
            for m in DIST_RE.finditer(line):
                county, district = m.group(2), m.group(3)
                code = f"{county}{district}"
                if code in seen:
                    continue
                try:
                    adm = float(m.group(5).replace(",", ""))
                    avg_cost = float(m.group(6).replace(",", ""))
                except ValueError:
                    continue
                if adm <= 0 or avg_cost <= 0:
                    continue
                seen.add(code)
                out.append({
                    "code": code,
                    "total_op_exp": adm * avg_cost,
                })
    pdf.close()
    return out


def build_nd_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("ND-"):
            out[sl.removeprefix("ND-")] = r
    return out


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"ND extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No NDDPI FinFacts URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/finfacts.pdf"

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
                "Section H 'Rank Order...by Avg Cost Per Pupil'; "
                "topline = ADM × Avg Cost; match {county}{district} == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} NDDPI School Finance Facts PDF",
        )

        crosswalk = build_nd_crosswalk(client)
        print(f"  ND crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_nd(pdf_bytes)
        print(f"  ND PDF districts: {len(district_data):,}")

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
            f"unmatched ND codes: {len(no_match)}"
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
