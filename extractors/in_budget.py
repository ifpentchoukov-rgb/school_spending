"""Indiana adopted-budget extractor — DLGF Gateway Form 4B.

Companion to extractors/in_.py (DUAB SCFI actuals). Per IC 6-1.1-17, IN
school corporations adopt budgets by Nov 1 of the year before the
budget year (e.g. budget year 2025 = SY 2024-25 = our FY25, adopted
~Nov 1, 2024). The board-adopted budget is filed in the DLGF Gateway
and certified by DLGF early the following year.

Source:
  https://gateway.ifionline.org/public/download.aspx
  Pipeline: ASP.NET form POST → 'Budget Data' → 'Budget Estimate -
  Financial Statement - Tax Rate (Form 4B)' → School / Year / All
  Counties → returns pipe-delimited TXT named form4b_School{YYYY}.txt.

What this gives us:
  - Per-corporation per-fund 'Total budget estimate_adopted' = the
    board-adopted appropriation. Funds split into:
      EDUCATION                                       (operating)
      OPERATIONS                                      (operating + some capital)
      REFERENDUM FUND - EXEMPT OPERATING [variants]   (operating)
      DEBT SERVICE / SCHOOL PENSION DEBT / BOND       (debt — exclude)
      REFERENDUM DEBT FUND - EXEMPT CAPITAL [variants](debt — exclude)
      RAINY DAY                                       (reserve — exclude)
      SELF INSURANCE                                  (internal — exclude)
      POST RETIREMENT/SEVERANCE                       (benefits — exclude)

Topline definition:
  Sum of 'Total budget estimate_adopted' per unit_code where fund_description
  in {EDUCATION, OPERATIONS, all REFERENDUM ... OPERATING variants}. This
  is aligned with F-33 'current expenditures' frame (excludes debt,
  capital, internal-service funds).

Status: `adopted` — board-approved per IC 6-1.1-17-5; certified by DLGF.

Crosswalk:
  Master state_leaid format: 'IN-{4-digit-unit-code}'
                              (e.g. 'IN-0235' Fort Wayne Community Schools)
  Form 4B unit_code:         4-digit zero-padded school corp code
  → state_leaid suffix == unit_code.

Known gap:
  Indianapolis Public Schools (IN-5385) does NOT appear in Form 4B —
  it files via a separate statutory pathway and isn't in the standard
  DLGF Gateway school download. Documented as follow-up.
"""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import io
import re
import sys
import urllib.error
import urllib.parse
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

EXTRACTOR_NAME = "in_budget"
STATE = "IN"
BUCKET = "in"
SOURCE_PORTAL_URL = "https://gateway.ifionline.org/public/download.aspx"
PUBLISHER = "Indiana Department of Local Government Finance (DLGF) — Gateway"
DOCUMENT_TYPE = "dlgf_gateway_form4b"
TOPLINE_DEFINITION = (
    "DLGF Gateway Form 4B — sum of 'Total budget estimate_adopted' "
    "per unit_code where fund_description in {EDUCATION, OPERATIONS, "
    "REFERENDUM FUND - EXEMPT OPERATING and variants}. Excludes "
    "DEBT SERVICE, REFERENDUM DEBT, RAINY DAY, SELF INSURANCE, "
    "POST RETIREMENT/SEVERANCE. Aligned with F-33 'current "
    "expenditures' frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

# Funds that compose the operating frame (case-insensitive name match —
# DLGF occasionally varies casing of 'Post Retirement Severance').
OPERATING_FUND_NAMES = {
    "EDUCATION",
    "OPERATIONS",
    "REFERENDUM FUND - EXEMPT OPERATING",
    "REFERENDUM FUND - EXEMPT OPERATING - POST 2009",
    "REFERENDUM FUND #2 - EXEMPT OPERATING - POST 2009",
    # Note: en-dash variant on the school-safety referendum fund.
    "REFERENDUM FUND – EXEMPT SCHOOL SAFETY OPERATING",
}

# DLGF "year" parameter convention: for schools, year = beginning of FY.
# So fiscal_year=2026 (SY 2025-26) corresponds to DLGF year=2025.
def _dlgf_year(fiscal_year: int) -> int:
    return fiscal_year - 1


def _grab_hidden(html: str, name: str) -> str:
    m = re.search(r'name="' + re.escape(name) + r'"[^>]+value="([^"]*)"', html)
    return m.group(1) if m else ""


def download_form4b(fiscal_year: int) -> tuple[bytes, str]:
    """3-step ASP.NET postback to download Form 4B for the given FY.

    Returns (body_bytes, source_url) where source_url encodes the
    canonical Gateway URL (postback target is the same for all years —
    we encode the fiscal_year via the year query for traceability).
    """
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    base = SOURCE_PORTAL_URL

    # Step 1: GET initial form.
    with opener.open(base, timeout=60) as r:
        html = r.read().decode("utf-8", errors="replace")
    vs = _grab_hidden(html, "__VIEWSTATE")
    vsg = _grab_hidden(html, "__VIEWSTATEGENERATOR")
    ev = _grab_hidden(html, "__EVENTVALIDATION")
    if not (vs and vsg and ev):
        raise RuntimeError("Could not extract ASP.NET hidden fields from Gateway page.")

    dlgf_year = str(_dlgf_year(fiscal_year))

    # Step 2: select 'Budget Data' (autopostback refreshes RadComboBox2 options).
    form_step = {
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$RadComboBox1",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": vs,
        "__VIEWSTATEGENERATOR": vsg,
        "__EVENTVALIDATION": ev,
        "ctl00$ContentPlaceHolder1$RadComboBox1": "Budget Data",
        "ctl00$ContentPlaceHolder1$RadComboBox1_ClientState":
            '{"value":"Budget Data","text":"Budget Data"}',
        "ctl00$ContentPlaceHolder1$DropDownListUnitType": "School",
        "ctl00$ContentPlaceHolder1$DropDownListYear": dlgf_year,
        "ctl00$ContentPlaceHolder1$DropDownListCountyData": "-99",
    }
    r2 = opener.open(
        base, data=urllib.parse.urlencode(form_step).encode(), timeout=60
    )
    html2 = r2.read().decode("utf-8", errors="replace")
    vs2 = _grab_hidden(html2, "__VIEWSTATE")
    ev2 = _grab_hidden(html2, "__EVENTVALIDATION")
    if not (vs2 and ev2):
        raise RuntimeError("Failed to obtain refreshed ASP.NET state after Budget Data selection.")

    # Step 3: submit download with Form 4B selection.
    target = "Budget Estimate - Financial Statement - Tax Rate (Form 4B)"
    form_dl = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": vs2,
        "__VIEWSTATEGENERATOR": vsg,
        "__EVENTVALIDATION": ev2,
        "ctl00$ContentPlaceHolder1$RadComboBox1": "Budget Data",
        "ctl00$ContentPlaceHolder1$RadComboBox1_ClientState":
            '{"value":"Budget Data","text":"Budget Data"}',
        "ctl00$ContentPlaceHolder1$RadComboBox2": target,
        "ctl00$ContentPlaceHolder1$RadComboBox2_ClientState":
            f'{{"value":"{target}","text":"{target}"}}',
        "ctl00$ContentPlaceHolder1$DropDownListUnitType": "School",
        "ctl00$ContentPlaceHolder1$DropDownListYear": dlgf_year,
        "ctl00$ContentPlaceHolder1$DropDownListCountyData": "-99",
        "ctl00$ContentPlaceHolder1$button_download1": "Download",
    }
    r3 = opener.open(
        base, data=urllib.parse.urlencode(form_dl).encode(), timeout=300
    )
    body = r3.read()
    cd = r3.getheader("Content-Disposition") or ""
    if not body or len(body) < 1000:
        raise RuntimeError(
            f"Form 4B download too small ({len(body)} bytes). "
            f"Content-Disposition={cd!r}"
        )
    if not body.startswith(b"year|"):
        raise RuntimeError(
            f"Form 4B response doesn't look like pipe-delimited data. "
            f"First bytes: {body[:200]!r}"
        )
    # Encode fiscal_year in the source_url for provenance even though the
    # actual endpoint is form-driven.
    source_url = f"{base}?dataset=Budget+Data&form=Form+4B&unitType=School&year={dlgf_year}"
    return body, source_url


def parse_in_form4b(txt_bytes: bytes) -> list[dict]:
    """Return [{code, total_op_exp}] from the IN Gateway Form 4B file.

    code = unit_code (4-digit corp code; state_leaid suffix).
    total_op_exp = sum(Total budget estimate_adopted) where
                   fund_description in OPERATING_FUND_NAMES and
                   unit_type == '4' (Schools).
    """
    text = txt_bytes.decode("utf-8", errors="replace")
    rdr = csv.DictReader(io.StringIO(text), delimiter="|")
    totals: dict[str, float] = {}
    for row in rdr:
        if row.get("unit_type") != "4":
            continue
        if row.get("fund_description", "").strip() not in OPERATING_FUND_NAMES:
            continue
        code = (row.get("unit_code") or "").strip()
        if not code:
            continue
        try:
            amt = float(row.get("Total budget estimate_adopted") or 0)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        totals[code] = totals.get(code, 0.0) + amt
    return [
        {"code": k, "total_op_exp": v}
        for k, v in totals.items()
        if v > 0
    ]


def build_in_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("IN-"):
            out[sl.removeprefix("IN-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"IN adopted-budget extract: fiscal_year={fiscal_year} (DLGF year={_dlgf_year(fiscal_year)})")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        print("  driving DLGF Gateway 3-step ASP.NET form...")
        txt_bytes, source_url = download_form4b(fiscal_year)
        content_hash = sha256_bytes(txt_bytes)
        print(f"  {len(txt_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/dlgf_form4b.txt"

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
                content=txt_bytes,
                mime_type="text/plain",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=source_url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="text/plain",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "form4b_School{YYYY}.txt; sum 'Total budget estimate_adopted' "
                "where fund_description in {EDUCATION, OPERATIONS, REFERENDUM "
                "FUND - EXEMPT OPERATING variants}; group by unit_code; "
                "unit_code == state_leaid suffix"
            ),
            notes=(
                f"FY{fiscal_year} (DLGF year={_dlgf_year(fiscal_year)}) Indiana "
                f"DLGF Gateway Form 4B — Budget Estimate / Financial Statement / "
                f"Tax Rate. Pipe-delimited. Known gap: IPS (IN-5385) not present."
            ),
        )

        crosswalk = build_in_crosswalk(client)
        print(f"  IN crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_in_form4b(txt_bytes)
        print(f"  Form 4B corps with FY{fiscal_year} adopted operating budget: {len(district_data):,}")

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
            f"unmatched unit_codes (charters / state schools / civil city schools): {len(no_match)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    # Default fiscal_year=2025: latest with full Form 4B publication
    # as of 2026-05-07 (DLGF year=2024). FY26 (DLGF year=2025) won't
    # certify until ~early 2026; FY27 won't certify until ~Feb 2027.
    p.add_argument("--fiscal-year", type=int, default=2025)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
