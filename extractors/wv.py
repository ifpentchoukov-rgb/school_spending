"""West Virginia adopted state-aid extractor — WVDE PSSP BOE Reconciliation.

Per W.V. Code §18-9A-12, the State Board of Education each year publishes
'Public School Support Program' (PSSP) computations that fix each
county's Basic State Aid Allowance — the legally-adopted state
appropriation flowing to each of WV's 55 county school systems.
WVDE posts the per-county tables as PDFs in the late-fall after the
Legislature finalizes the school aid formula.

Source URL pattern (FY26 example):
  https://wvde.us/media/7959/boe-sa-recon-comps-26pdf

Network note:
  wvde.us is a Drupal site behind Imperva-style WAF that returns
  Access Denied to Python-stdlib HTTP clients. We use `curl_cffi` with
  `impersonate='chrome120'` to mimic a real Chrome TLS handshake — that
  passes the WAF cleanly. `verify=False` because curl-impersonate
  doesn't pick up macOS's cert bundle automatically.

Topline definition (state-aid frame, NOT full F-33):
  'Basic State Aid Allowance for County Boards (WVC 18-9A-12)' — the
  state's adopted appropriation per county, calculated under the
  School Aid Formula (Steps 1-7). This is the LEGALLY-BINDING state
  contribution and is the most authoritative public-data point for
  WV per-county school finance. It does NOT include local share
  (county property tax) or federal funds, so it is NOT comparable
  to F-33 'current expenditures' (which sums all funds). For WV,
  the local share + federal portions are filed in WVEIS behind a
  login and are not bulk-published.

Status: `adopted` — the State Aid Allowance is set by SBOE under §18-9A-12.

Crosswalk:
  Master state_leaid format: 'WV-{2-digit county num}00000'
                              (NCES format; e.g. 'WV-3900000' Kanawha)
  PDF column:                 county name (e.g. 'Kanawha')
  Match strategy:             '{Name} County Schools' lookup against
                              master lea_name.
"""

from __future__ import annotations

import argparse
import io
import re
import sys

import pdfplumber
from curl_cffi import requests as curl_req
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

EXTRACTOR_NAME = "wv"
STATE = "WV"
BUCKET = "wv"
SOURCE_PORTAL_URL = "https://wvde.us/finance/school-finance/school-finance-data/"
PUBLISHER = "West Virginia Department of Education (Office of School Finance)"
DOCUMENT_TYPE = "wvde_pssp_boe_recon_pdf"
TOPLINE_DEFINITION = (
    "WVDE PSSP BOE State Aid Reconciliation PDF — 'Basic State Aid "
    "Allowance for County Boards (WVC 18-9A-12)' per county. State-aid "
    "frame ONLY (not full F-33 'current expenditures'): excludes local "
    "share (property tax) and federal funds, both of which are filed in "
    "WVEIS behind a login and not bulk-published. Use as state-aid "
    "appropriation reference, not as total operating spending."
)
USER_AGENT = (
    "school-budget-tracker/0.1 "
    "(https://github.com/ifpentchoukov-rgb/school_spending)"
)

# Annual WVDE publication URLs — pinned per FY.
KNOWN_FILE_URLS: dict[int, str] = {
    # FY26 final
    2026: "https://wvde.us/media/7959/boe-sa-recon-comps-26pdf",
    # FY27 preliminary (released Dec 15, 2025)
    2027: "https://wvde.us/media/8835/boe-sa-recon-prel-comps-27pdf",
}

# pdfplumber occasionally inserts a stray space inside dollar amounts
# from narrow columns: e.g. '3 4,545' should be '34,545'. We only fix
# the specific pattern where a single digit is immediately followed by
# whitespace + digits-with-comma — not generic digit-space-digit (which
# would merge legitimately separated columns).
_STRAY_DIGIT_FIX = re.compile(r"(?<![\d,])(\d)\s(\d{1,2},\d{3})")


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    # Let curl-cffi use chrome120's native User-Agent — passing a custom
    # UA can break some WAFs.
    r = curl_req.get(
        url,
        impersonate="chrome120",
        timeout=120,
        verify=False,
    )
    r.raise_for_status()
    return r.content


def parse_wv_pssp(pdf_bytes: bytes) -> list[dict]:
    """Return [{county, basic_state_aid}] from the WV PSSP BOE
    Reconciliation PDF.
    """
    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as p:
        for page in p.pages:
            text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts)

    # Fix only the narrow-column digit-split artifact (e.g. "3 4,545"
    # -> "34,545"). Don't merge generic digit-space-digit because that
    # would collapse legitimate column separators.
    fixed = _STRAY_DIGIT_FIX.sub(r"\1\2", text)

    out: list[dict] = []
    # Match lines like:
    #   Berkeley 124,441,151 3,332,462 121,108,689
    # or with trailing $ on first row:
    #   Barbour $ 11,362,889 $ 332,685 $ 11,030,204
    # or with empty/zero column 1 (e.g. Marshall, Tyler, Wetzel):
    #   Marshall - 182,702 (182,702)
    line_re = re.compile(
        r"^\s*"
        r"([A-Z][A-Za-z. ]+?)"            # county name
        r"\s+\$?\s*"
        r"([\d,()-]+|-)"                   # column 1: Basic State Aid
        r"\s+\$?\s*"
        r"([\d,()-]+|-)"                   # column 2: Charter Adjustment
        r"\s+\$?\s*"
        r"([\d,()-]+|-)"                   # column 3: Adjusted Basic State Aid
        r"\s*$",
        re.M,
    )

    for m in line_re.finditer(fixed):
        county = m.group(1).strip().rstrip(".")
        amt_str = m.group(1 + 1)
        # Handle '-' = 0 (county had no state aid before charter pull),
        # parens = negative, commas allowed.
        amt = _to_num(amt_str)
        # Skip 'State' total row.
        if county.lower() == "state" or county.lower() == "totals":
            continue
        if county in {"Note"}:
            continue
        # Reject obvious non-county lines (e.g. headers).
        if amt == 0 and "_" in county:
            continue
        # Must be a known county shape: one or two words, capitalized.
        if not re.match(r"^[A-Z][A-Za-z. ]+$", county):
            continue
        if amt < 0:
            # Negative basic state aid means charter payments exceed —
            # they net out as 0 from the state to BOE; adjusted column
            # captures the deficit. For our topline purposes we keep
            # the original Basic State Aid Allowance (column 1, which
            # would be 0 in those cases).
            amt = 0
        out.append({
            "county": county,
            "basic_state_aid": amt,
        })
    return out


def _to_num(s: str) -> float:
    s = s.replace(",", "").replace("$", "").strip()
    if s in {"-", "", "—"}:
        return 0.0
    if s.startswith("(") and s.endswith(")"):
        try:
            return -float(s[1:-1])
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def build_wv_crosswalk(client: Client) -> dict[str, dict]:
    """Return {county_name_lower: district_row}. Master lea_name is
    '{County} County Schools' for WV's 55 county systems."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        name = (r.get("lea_name") or "").strip()
        # 'Barbour County Schools' -> 'barbour'
        m = re.match(r"^(.+?)\s+County\s+Schools$", name, re.I)
        if m:
            out[m.group(1).strip().lower()] = r
    return out


def extract(*, fiscal_year: int = 2026, triggered_by: str = "manual") -> dict:
    print(f"WV state-aid extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No WV PSSP BOE Reconciliation URL for fiscal_year="
                f"{fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]} (curl-cffi chrome120)...")
        pdf_bytes = download(url)
        content_hash = sha256_bytes(pdf_bytes)
        print(f"  {len(pdf_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/pssp_boe_sa_recon.pdf"
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
                "Page 1 'Basic State Aid Allowance for County Boards' "
                "column; per-county; match '{County} County Schools' "
                "against master lea_name"
            ),
            notes=(
                f"FY{fiscal_year} WV PSSP BOE State Aid Reconciliation. "
                f"Fetched via curl-cffi chrome120 to bypass wvde.us "
                f"Drupal/Imperva firewall. State-aid frame only — does "
                f"NOT include local share or federal funds (those live "
                f"in WVEIS behind a login)."
            ),
        )

        crosswalk = build_wv_crosswalk(client)
        print(f"  WV crosswalk: {len(crosswalk):,} county→NCES mappings")

        records = parse_wv_pssp(pdf_bytes)
        print(f"  PSSP per-county rows parsed: {len(records):,}")

        no_match: list[str] = []
        for d in records:
            district = crosswalk.get(d["county"].lower())
            if district is None:
                no_match.append(d["county"])
                continue

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="adopted",
                topline_amount=d["basic_state_aid"],
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
            f"unmatched counties: {len(no_match)}"
        )
        if no_match:
            print(f"  unmatched: {no_match}")

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
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
