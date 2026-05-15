"""Arkansas extractor — DESE Annual Statistical Report PDF.

Source: https://dese.ade.arkansas.gov/Offices/fiscal-and-administrative-services/school-funding/funding-data
File: Annual_Statistics_Report_w.GL_{N}_{YYYY}_FAS.pdf — published
      annually by ADE Division of Elementary and Secondary Education,
      Fiscal Services. One page per district + ESC; ~400 pages.

What this gives us:
  - Per-district expenditures, ADM, mills, salaries, etc. for all
    AR operating LEAs (school districts + charter LEAs). The ASR is
    the authoritative state-published per-district report.

Topline definition:
  Each district page line 79 "Total Current Expenditures", Actual
  column (= FY just closed). This excludes line 77 Capital Expenditures
  and line 78 Debt Service per the ASR's own definition. Aligned with
  F-33 'current expenditures' frame.

Status: `actual` — post-AFR audited.

Crosswalk:
  Master state_leaid format: 'AR-{7-digit}' (e.g. 'AR-0101000' DeWitt)
  PDF LEA code:              7-digit string (e.g. '1201000')
  → strip AR- prefix == PDF LEA code directly.
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
    ComponentInput,
    Run,
    fetch_all,
    sha256_bytes,
    upload_source_document,
    upsert_budget_event_with_supersession,
    upsert_components,
    upsert_source_document_row,
)

EXTRACTOR_NAME = "ar"
STATE = "AR"
BUCKET = "ar"
SOURCE_PORTAL_URL = "https://dese.ade.arkansas.gov/Offices/fiscal-and-administrative-services/school-funding/funding-data"
PUBLISHER = "Arkansas Department of Education (Division of Elementary and Secondary Education, Fiscal Services)"
DOCUMENT_TYPE = "ar_dese_asr_pdf"
TOPLINE_DEFINITION = (
    "ADE/DESE Annual Statistical Report PDF, per-district page line 79 "
    "'Total Current Expenditures' — Actual column. ASR-defined as Total "
    "Expenditures minus Capital Expenditures and Debt Service. Aligned "
    "with F-33 'current expenditures' frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

# Per-page LEA header: "... LEA: NNNNNNN"
LEA_RE = re.compile(r"LEA:\s*(\d{7})")
# Line 79 with two integer values (actual + budget). Allow spaces or
# embedded spaces in the rendered numbers.
LINE_79_RE = re.compile(
    r"^\s*79\s+Total Current Expenditures\s+([\d,]+)\s+", re.MULTILINE
)
# Phase 7.5 — Line 77 Capital Expenditures + Line 78 Debt Service.
# ASR renders these as "Less: Capital Expenditures (NNN,NNN) -NNN,NNN"
# meaning they're subtracted from Total Expenditures to derive Total
# Current Expenditures (line 79). Values in parentheses are positive
# dollar amounts. Line 77 sometimes has line 76 text bleed through
# ("Special Education: 77 ..."), so match anywhere on the line.
LINE_77_RE = re.compile(
    r"\b77\s+Less:\s*Capital Expenditures\s+\(?([\d,]+)\)?", re.MULTILINE
)
LINE_78_RE = re.compile(
    r"\b78\s+Less:\s*Debt Service\s+\(?([\d,]+)\)?", re.MULTILINE
)

KNOWN_FILE_URLS: dict[int, str] = {
    # FY24 = SY 2023-24 ASR; published Dec 2024.
    2024: "https://dese.ade.arkansas.gov/Files/Annual_Statistics_Report_w.GL_1_2024_FAS.pdf",
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_asr(pdf_bytes: bytes) -> list[dict]:
    pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    out: list[dict] = []
    seen_codes: set[str] = set()
    for page in pdf.pages:
        text = page.extract_text() or ""
        m_lea = LEA_RE.search(text)
        m_79 = LINE_79_RE.search(text)
        if not m_lea or not m_79:
            continue
        code = m_lea.group(1)
        if code in seen_codes:
            continue  # ASR sometimes prints continuations; skip duplicates
        try:
            amt = float(m_79.group(1).replace(",", ""))
        except ValueError:
            continue
        if amt <= 0:
            continue
        seen_codes.add(code)
        # Phase 7.5 — capital + debt from lines 77, 78 (Actual column)
        components: dict[str, float] = {}
        m_77 = LINE_77_RE.search(text)
        if m_77:
            try:
                components["capital_outlay"] = float(m_77.group(1).replace(",", ""))
            except ValueError:
                pass
        m_78 = LINE_78_RE.search(text)
        if m_78:
            try:
                components["debt_service"] = float(m_78.group(1).replace(",", ""))
            except ValueError:
                pass
        out.append({
            "code": code,
            "total_op_exp": amt,
            "components": components,
        })
    pdf.close()
    return out


def build_ar_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("AR-"):
            out[sl.removeprefix("AR-")] = r
    return out


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"AR extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No DESE ASR URL for fiscal_year={fiscal_year}; "
                "add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/asr.pdf"

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
                "One page per LEA; topline = line 79 'Total Current "
                "Expenditures' Actual column; match 7-digit LEA code "
                "from header == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} ADE/DESE Annual Statistical Report (PDF)",
        )

        crosswalk = build_ar_crosswalk(client)
        print(f"  AR crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_asr(pdf_bytes)
        print(f"  ASR districts parsed: {len(district_data):,}")

        no_match: list[str] = []
        n_components_inserted = 0
        n_components_updated = 0
        n_components_unchanged = 0
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
            event_id, changed = upsert_budget_event_with_supersession(
                client=client, event=event
            )
            run.records_extracted += 1
            if changed:
                run.records_changed += 1

            # Phase 7.5 — capital + debt from lines 77, 78.
            components: list[ComponentInput] = []
            for category, amount in d.get("components", {}).items():
                if amount <= 0:
                    continue
                line_num = "77" if category == "capital_outlay" else "78"
                desc = "Capital Expenditures" if category == "capital_outlay" else "Debt Service"
                components.append(
                    ComponentInput(
                        category=category,
                        amount=float(amount),
                        definition=(
                            f"ADE/DESE ASR PDF: Line {line_num} '{desc}', "
                            f"Actual column — per-district page"
                        ),
                        line_or_cell_reference=(
                            f"PDF page for LEA {d['code']}, line {line_num}"
                        ),
                    )
                )
            if components:
                ins, upd, unch = upsert_components(
                    client=client,
                    budget_event_id=event_id,
                    components=components,
                )
                n_components_inserted += ins
                n_components_updated += upd
                n_components_unchanged += unch

        print(
            f"  inserted/changed={run.records_changed}/{run.records_extracted}; "
            f"unmatched ASR LEA codes (charters/ESCs): {len(no_match)}"
        )
        print(
            f"  components: inserted={n_components_inserted} "
            f"updated={n_components_updated} unchanged={n_components_unchanged}"
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
