"""Massachusetts extractor — DESE Profiles Per Pupil Expenditures (statereport).

Source: https://profiles.doe.mass.edu/statereport/ppx.aspx
Page is ASP.NET WebForms; default GET returns the latest available FY's
all-district per-pupil expenditure table embedded as HTML.

What this gives us:
  - Per-district `Total Expenditures` for every MA LEA. This is the
    "All Funds" total — in-district + out-of-district + school-choice +
    educational-collaborative payments — drawn from districts' submitted
    End-of-Year Financial Report (EOYR). Aligned with F-33 'current
    expenditures' frame; matches the Department's Per-Pupil Expenditure
    publication.

Topline definition:
  PPX page column 'Total Expenditures' — total per-district current
  expenditures across all funds (post-audit). EOYR-derived.

Status: `actual` — post-EOYR audited.

Crosswalk:
  Master state_leaid format: 'MA-{4-digit}' (e.g. 'MA-0001' Abington)
  DESE district_code:        8-digit (e.g. '00010000')
  → first 4 digits of district_code == state_leaid suffix.

Latest FY: FY24 (SY 2023-24). FY25 publishes after Dec 2025 EOYR
audit cycle; FY27 calendar maps to FY24 for now.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request

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

EXTRACTOR_NAME = "ma"
STATE = "MA"
BUCKET = "ma"
SOURCE_PORTAL_URL = "https://profiles.doe.mass.edu/statereport/ppx.aspx"
PUBLISHER = "Massachusetts Department of Elementary and Secondary Education"
DOCUMENT_TYPE = "ma_dese_ppx_statereport_html"
TOPLINE_DEFINITION = (
    "DESE Profiles Statewide Per Pupil Expenditures (PPX), 'Total "
    "Expenditures' column — per-district current expenditures across "
    "all funds (in-district + out-of-district + school-choice + "
    "educational-collaborative). EOYR-derived; aligned with F-33 "
    "'current expenditures' frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"


def page_url() -> str:
    return SOURCE_PORTAL_URL


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse_ppx_table(html: bytes) -> tuple[int, list[dict]]:
    """Return (fiscal_year, [{code, name, total_exp}, ...]) from the PPX
    HTML page. Default GET returns latest available FY."""
    text = html.decode("utf-8", errors="replace")

    # Detect FY from the selected option in the FY dropdown.
    fy_match = re.search(
        r'<option\s+selected="selected"\s+value="(\d{4})">\d{4}</option>',
        text,
    )
    if not fy_match:
        raise RuntimeError("Could not detect selected FY on PPX page")
    fy = int(fy_match.group(1))

    # Locate the per-pupil-expenditure table by id.
    tbl_match = re.search(
        r"<table[^>]*id='tblPerPupilExpenditure'[^>]*>(.*?)</table>",
        text,
        re.DOTALL,
    )
    if not tbl_match:
        raise RuntimeError("tblPerPupilExpenditure not found in HTML")
    tbl = tbl_match.group(1)

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.DOTALL)
    out: list[dict] = []
    for r in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.DOTALL)
        if len(cells) < 6:
            continue
        # Strip tags and whitespace
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        # Skip header
        if clean[0] == "District Name":
            continue
        name = clean[0]
        code8 = clean[1]
        total_exp_str = clean[5]
        # Total Expenditures is "$25,489,056.09" — strip $ and commas
        amt_clean = total_exp_str.replace("$", "").replace(",", "").strip()
        try:
            total_exp = float(amt_clean)
        except ValueError:
            continue
        if total_exp <= 0:
            continue
        if not (len(code8) == 8 and code8.isdigit()):
            continue
        out.append(
            {"code": code8[:4], "name": name, "total_exp": total_exp}
        )
    return fy, out


def build_ma_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("MA-"):
            out[sl.removeprefix("MA-")] = r
    return out


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"MA extract: requested fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = page_url()
        print(f"  downloading {url}...")
        html_bytes = download(url)
        content_hash = sha256_bytes(html_bytes)
        print(f"  {len(html_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        page_fy, district_data = parse_ppx_table(html_bytes)
        print(f"  page reports FY{page_fy}; districts parsed: {len(district_data):,}")
        if page_fy != fiscal_year:
            print(
                f"  WARN: requested FY{fiscal_year} but page returned FY{page_fy}; "
                f"using page FY (DESE PPX page only serves latest balanced FY via plain GET)"
            )
            fiscal_year = page_fy

        storage_relpath = f"fy{fiscal_year}/dese_ppx_statereport.html"

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
                content=html_bytes,
                mime_type="text/html",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="text/html",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "table id='tblPerPupilExpenditure' rows; "
                "match district_code[:4] == state_leaid suffix; "
                "topline = column 'Total Expenditures'"
            ),
            notes=f"FY{fiscal_year} DESE PPX statewide HTML (EOYR-derived)",
        )

        crosswalk = build_ma_crosswalk(client)
        print(f"  MA crosswalk: {len(crosswalk):,} state→NCES mappings")

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
                topline_amount=d["total_exp"],
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
            f"unmatched DESE codes: {len(no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2024,
                   help="DESE PPX page only returns latest balanced FY via "
                        "plain GET; this is informational and will be "
                        "overridden by the page-detected FY")
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
