"""New Jersey adopted-budget extractor — NJDOE User-Friendly Budget (UFB) CSV.

Companion to extractors/nj.py (TGES actuals). Per N.J. Stat. § 18A:22-1
et seq., NJ districts adopt FY budgets by mid-May (after exec county
superintendent review). Adopted budget data is published as a
public 'User-Friendly Budget' set of CSVs at
https://www.nj.gov/education/budget/ufb/{YYYY-YY}/.

What this gives us:
  - Per-district line-item appropriations from the adopted FY budget
    in approp{YY}.csv. Line numbers map to NJ Chart of Accounts:
      72260 = Total General Current Expense (operating instruction +
              support, NO capital outlay, NO debt service)
      88760 = Total Special Revenue Funds (federal/state categorical
              grants — operating)

Topline definition:
  Sum of approp{YY}.csv amount_3 (= adopted budget year) for line
  numbers 72260 + 88760 per (county_id, district_id). Aligned with
  F-33 'current expenditures' frame; excludes Capital Outlay (line
  76400), Debt Service (line 89980), and inter-fund transfers.

Status: `adopted` — post-board-adoption per § 18A:22-32.

Crosswalk:
  Master state_leaid format: 'NJ-{2-digit-County}{4-digit-District}'
                              (e.g. 'NJ-010110' Atlantic City)
  CSV cols:                  county_id (2-digit) + district_id (4-digit)
  → state_leaid suffix == f'{county_id}{district_id}'
"""

from __future__ import annotations

import argparse
import csv
import io
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

EXTRACTOR_NAME = "nj_budget"
STATE = "NJ"
BUCKET = "nj"
SOURCE_PORTAL_URL = "https://www.nj.gov/education/budget/ufb/"
PUBLISHER = "New Jersey Department of Education (Office of School Finance)"
DOCUMENT_TYPE = "njdoe_ufb_approp_csv"
TOPLINE_DEFINITION = (
    "NJDOE User-Friendly Budget approp{YY}.csv — sum of amount_3 "
    "(adopted budget year) for line 72260 'Total General Current "
    "Expense' + line 88760 'Total Special Revenue Funds' per "
    "(county_id, district_id). Excludes Capital Outlay (76400), "
    "Debt Service (89980). Aligned with F-33 'current expenditures' "
    "frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

# UFB URL pattern: /education/budget/ufb/{YY1YY2}/download/approp{YY2}.csv
# where YY1YY2 = e.g. "2526" for SY 2025-26 (= our fiscal_year=2026)
KNOWN_FILE_URLS: dict[int, str] = {
    # FY26 = SY 2025-26 (latest published as of 2026-05-06).
    # FY27 (SY 2026-27) UFBs will appear here after districts adopt
    # by May 15, 2026 — re-add when posted.
    2026: "https://www.nj.gov/education/budget/ufb/2526/download/approp26.csv",
}

# Line numbers in NJ Chart of Accounts that compose the F-33 operating frame
TOPLINE_LINE_NUMBERS = {72260, 88760}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_nj_ufb(csv_bytes: bytes) -> list[dict]:
    """Return [{code, total_op_exp}] from UFB approp CSV.

    code = f'{county_id}{district_id}' (state_leaid suffix).
    total_op_exp = sum(amount_3) where line_no in TOPLINE_LINE_NUMBERS.
    """
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    rdr = csv.DictReader(io.StringIO(text))
    totals: dict[str, float] = {}
    for row in rdr:
        try:
            line_no = int(row["line_no"])
        except (ValueError, KeyError, TypeError):
            continue
        if line_no not in TOPLINE_LINE_NUMBERS:
            continue
        county_id = (row.get("county_id") or "").strip()
        district_id = (row.get("district_id") or "").strip()
        if not county_id or not district_id:
            continue
        try:
            amt = float(row.get("amount_3") or 0)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        key = f"{county_id}{district_id}"
        totals[key] = totals.get(key, 0.0) + amt
    return [
        {"code": k, "total_op_exp": v}
        for k, v in totals.items()
        if v > 0
    ]


def build_nj_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("NJ-"):
            out[sl.removeprefix("NJ-")] = r
    return out


def extract(*, fiscal_year: int = 2026, triggered_by: str = "manual") -> dict:
    print(f"NJ adopted-budget extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            from extractors._exceptions import SourceNotYetPublished
            raise SourceNotYetPublished(
                f"No NJ UFB URL for fiscal_year={fiscal_year}; districts file May "
                "15 → June; add to KNOWN_FILE_URLS once published."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        csv_bytes = download(url)
        content_hash = sha256_bytes(csv_bytes)
        print(f"  {len(csv_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/ufb_approp.csv"

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
                content=csv_bytes,
                mime_type="text/csv",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="text/csv",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "approp{YY}.csv; sum amount_3 where line_no in "
                "(72260, 88760); group by (county_id, district_id); "
                "match f'{county_id}{district_id}' == state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} NJ User-Friendly Budget (adopted)",
        )

        crosswalk = build_nj_crosswalk(client)
        print(f"  NJ crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_nj_ufb(csv_bytes)
        print(f"  UFB districts with FY{fiscal_year} adopted budget: {len(district_data):,}")

        no_match: list[str] = []
        for d in district_data:
            district = crosswalk.get(d["code"])
            if district is None:
                no_match.append(d["code"])
                continue

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="adopted",
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
            f"unmatched UFB codes (special services / jointures / vocs not in master): {len(no_match)}"
        )

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
