"""South Carolina extractor — SCDE In$ite per-district expenditure PDFs.

Source: https://ed.sc.gov/finance/financial-data/in-ite/
Files: two bundled PDFs per FY containing one page per district —
  - fiscal-year-{YYYY}-abbeville-greenwood-52  (A → G districts)
  - fiscal-year-{YYYY}-hampton-limestone        (H → Z districts + charters)

The "fiscal-year-{YYYY}-state-totals" URL is just the statewide page
and is not used.

What this gives us:
  - Per-district `Current Expenditures` for all 75 SC operating LEAs
    (74 traditional school districts + Charter District + Erskine
    Charter District + Limestone Charter District). Statewide total
    $11.7B for FY24.

Topline definition:
  Per-district 'Function' total in In$ite — equal to Total
  Expenditures minus Capital & Out-of-District Obligations.
  Excludes capital outlay, debt service, and out-of-district
  payments (school-choice tuition transfers). Aligned with F-33
  'current expenditures' frame.

Status: `actual` — post-AFR audited (SCDE In$ite is published
annually after district audits close).

Crosswalk:
  Master state_leaid format: 'SC-{4-digit}' (e.g. 'SC-0160' Abbeville)
  PDF Location Code:         4-digit string (e.g. '0160')
  → strip SC- prefix == Location Code directly.
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

EXTRACTOR_NAME = "sc"
STATE = "SC"
BUCKET = "sc"
SOURCE_PORTAL_URL = "https://ed.sc.gov/finance/financial-data/in-ite/"
PUBLISHER = "South Carolina Department of Education (Office of Finance)"
DOCUMENT_TYPE = "scde_insite_pdf"
TOPLINE_DEFINITION = (
    "SCDE In$ite per-district report: 'Function' total = Total "
    "Expenditures minus Capital & Out-of-District Obligations. "
    "Aligned with F-33 'current expenditures' frame; excludes "
    "capital outlay, debt service, and out-of-district payments."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

KNOWN_FILE_URLS: dict[int, list[tuple[str, str]]] = {
    # FY2024 — published 2025-2026.
    2024: [
        (
            "abbeville_greenwood_52",
            "https://ed.sc.gov/finance/financial-data/in-ite/fiscal-year-2024-abbeville-greenwood-52/",
        ),
        (
            "hampton_limestone",
            "https://ed.sc.gov/finance/financial-data/in-ite/fiscal-year-2024-hampton-limestone/",
        ),
    ],
}

LOCATION_CODE_RE = re.compile(r"Location Code:\s*(\d{4})")
# Per-district topline line ends with "$ <total> $ <per-pupil> 100.00%".
# In the rendered text this appears as
# "Function Sub-Function Detail Function $ <total> $ <per-pupil> 100.00%"
# (the header columns get concatenated onto the totals row by pdfplumber).
# Anchor on the trailing "$ X $ Y 100.00%" pattern so we don't depend on
# the leading column headers, and clean spurious mid-number spaces first.
FUNCTION_LINE_RE = re.compile(
    r"\$\s*([\d,]+)\s+\$\s*[\d,]+\s+100\.00\s*%"
)
_SPACE_FIX = re.compile(r"(?<![,\d])(\d) (?=[\d,])")


def _clean(text: str) -> str:
    return _SPACE_FIX.sub(r"\1", text)


def file_urls(fiscal_year: int) -> list[tuple[str, str]] | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_insite_pdf(pdf_bytes: bytes) -> list[dict]:
    """Return [{code, total_op_exp}] from one SCDE In$ite PDF; one page per district."""
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    out: list[dict] = []
    for page in pdf.pages:
        text = _clean(page.extract_text() or "")
        loc = LOCATION_CODE_RE.search(text)
        fn = FUNCTION_LINE_RE.search(text)
        if not loc or not fn:
            continue
        code = loc.group(1)
        # Skip the state-totals page if present
        if code == "0000":
            continue
        try:
            amt = float(fn.group(1).replace(",", ""))
        except ValueError:
            continue
        if amt <= 0:
            continue
        out.append({"code": code, "total_op_exp": amt})
    pdf.close()
    return out


def build_sc_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("SC-"):
            out[sl.removeprefix("SC-")] = r
    return out


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"SC extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        urls = file_urls(fiscal_year)
        if not urls:
            raise RuntimeError(
                f"No SCDE In$ite URLs for fiscal_year={fiscal_year}; "
                "add to KNOWN_FILE_URLS."
            )

        crosswalk = build_sc_crosswalk(client)
        print(f"  SC crosswalk: {len(crosswalk):,} state→NCES mappings")

        all_no_match: list[str] = []
        for slug, url in urls:
            print(f"  downloading {slug}...")
            pdf_bytes = download(url)
            content_hash = sha256_bytes(pdf_bytes)
            print(
                f"    {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}..."
            )

            storage_relpath = f"fy{fiscal_year}/{slug}.pdf"

            existing_src = (
                client.table("source_documents")
                .select("id")
                .eq("content_hash_sha256", content_hash)
                .execute()
            )
            if not existing_src.data:
                print(f"    uploading to {BUCKET}/{storage_relpath}...")
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
                    "One page per district; topline = 'Function' line = "
                    "Total Expenditures - Capital & Out-of-District "
                    "Obligations; match Location Code (4-digit) == "
                    "state_leaid suffix"
                ),
                notes=f"FY{fiscal_year} SCDE In$ite PDF bundle ({slug})",
            )

            district_data = parse_insite_pdf(pdf_bytes)
            print(f"    parsed {len(district_data)} districts from this bundle")

            for d in district_data:
                district = crosswalk.get(d["code"])
                if district is None:
                    all_no_match.append(d["code"])
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
            f"unmatched In$ite codes: {len(all_no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(all_no_match),
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
