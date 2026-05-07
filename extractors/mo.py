"""Missouri actuals extractor — DESE MCDS Finance Data and Statistics XLS.

Per RSMo §165.111, every MO school district files an Annual Secretary
of the Board Report (ASBR) with the Department of Elementary and
Secondary Education (DESE). DESE consolidates ASBR data into the
'Finance Data and Statistics Summary for All Districts' multi-year XLS
published on the Missouri Comprehensive Data System (MCDS) portal.

Source URL: https://apps.dese.mo.gov/MCDS/FileDownloadWebHandler.ashx
            ?filename={GUID-prefix}{filename-with-spaces}
The GUID prefix changes per release; we discover it by parsing
https://apps.dese.mo.gov/MCDS/home.aspx for the current 'Finance Data'
link.

Auth flow (passwordless 2-step + auto-form bridge):
  1. GET DESEApplicationsSignin/OrgSelect?appId=6540&appType=Public
     → grab __RequestVerificationToken from the page.
  2. POST same URL with {ApplicationId=6540, ApplicationScopeId=28371,
     SelectedPersonType=AP, PersonType=None, DESEPublicRedirectId=0,
     __RequestVerificationToken=...} → server returns an HTML page
     with an auto-submit form carrying ~8 opaque session-bridge tokens.
  3. POST those hidden fields to /MCDS/home.aspx → sets session cookies
     and returns the populated home page with file-download links.
  4. Parse home page for FileDownloadWebHandler.ashx?filename=...
     matching 'Finance Data'.
  5. GET that URL with cookies → 3.9 MB XLS.

Network note:
  apps.dese.mo.gov sits behind a TLS-fingerprinting WAF; we use
  curl_cffi with impersonate='chrome120'. verify=False because curl-
  impersonate doesn't pick up macOS's cert bundle automatically.

Topline definition:
  Sheet '{YYYY}', column 'TOTAL EXPENDITURE' per district. This is
  MO's all-funds total expenditure (GF + Teacher + DSF + CPF). NOT
  strict F-33 'current expenditures' — includes Debt Service Fund and
  Capital Projects Fund. The 2025 release of this XLS dropped the
  'CURRENT EXPENDITURE' column; only TOTAL EXPENDITURE remains.

Status: `actual` — ASBR is the audited annual filing.

Crosswalk:
  Master state_leaid format: 'MO-{6-digit zero-padded code}'
                              (e.g. 'MO-048078' Kansas City 33)
  XLS COUNTY DISTRICT CODE:   variable-length integer (e.g. 48078)
  → state_leaid suffix == str(code).zfill(6).
"""

from __future__ import annotations

import argparse
import io
import re
import sys

import pandas as pd
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

EXTRACTOR_NAME = "mo"
STATE = "MO"
BUCKET = "mo"
SOURCE_PORTAL_URL = "https://apps.dese.mo.gov/MCDS/home.aspx"
PUBLISHER = (
    "Missouri Department of Elementary and Secondary Education "
    "(MCDS / School Finance)"
)
DOCUMENT_TYPE = "mo_dese_mcds_finance_summary_xls"
TOPLINE_DEFINITION = (
    "MO DESE MCDS 'Finance Data and Statistics Summary for All "
    "Districts' XLS, sheet '{YYYY}', column 'TOTAL EXPENDITURE'. "
    "All-funds total: GF + Teacher Fund + Debt Service Fund + "
    "Capital Projects Fund. NOT strict F-33 'current expenditures' "
    "(includes debt + capital). The 2025 release dropped the prior "
    "'CURRENT EXPENDITURE' column; we use TOTAL EXPENDITURE."
)
USER_AGENT_NOTE = "via curl-cffi chrome120 (TLS impersonation)"

SIGNIN_URL = (
    "https://apps.dese.mo.gov/DESEApplicationsSignin/OrgSelect"
    "?appId=6540&sort=0&appType=Public"
)
HOME_URL = "https://apps.dese.mo.gov/MCDS/home.aspx"
DOWNLOAD_HANDLER = (
    "https://apps.dese.mo.gov/MCDS/FileDownloadWebHandler.ashx"
)
FINANCE_FILE_PATTERN = re.compile(
    r"Finance Data and Statistics Summary for All Districts",
    re.I,
)


def _new_session() -> "curl_req.Session":
    s = curl_req.Session(impersonate="chrome120")
    s.verify = False
    return s


def _signin(s) -> None:
    """2-step DESE passwordless sign-in. Sets session cookies in `s`."""
    r1 = s.get(SIGNIN_URL, timeout=30)
    r1.raise_for_status()
    m = re.search(
        r'name="__RequestVerificationToken"[^>]+value="([^"]+)"', r1.text
    )
    if not m:
        raise RuntimeError("DESE sign-in: __RequestVerificationToken not found")
    token = m.group(1)

    form = {
        "__RequestVerificationToken": token,
        "ApplicationId": "6540",
        "ApplicationScopeId": "28371",  # any valid scope; ADAIR works
        "SelectedPersonType": "AP",
        "PersonType": "None",
        "DESEPublicRedirectId": "0",
    }
    r2 = s.post(SIGNIN_URL, data=form, timeout=30)
    r2.raise_for_status()

    # The response is an HTML page with an auto-submit form posting to
    # /MCDS/home.aspx with ~8 opaque session-bridge tokens.
    bridge_fields = dict(
        re.findall(
            r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', r2.text
        )
    )
    if not bridge_fields:
        raise RuntimeError("DESE sign-in: no session-bridge fields found")

    r3 = s.post(HOME_URL, data=bridge_fields, timeout=30)
    r3.raise_for_status()


def _resolve_finance_file_url(s) -> str:
    """Parse MCDS home page for the current Finance Data file URL."""
    r = s.get(HOME_URL, timeout=30)
    r.raise_for_status()
    # Format: FileDownloadWebHandler.ashx?filename={GUID8}{Filename...}
    links = re.findall(
        r"FileDownloadWebHandler\.ashx\?filename=([^\"'<>]+)", r.text
    )
    for link in links:
        if FINANCE_FILE_PATTERN.search(link):
            return f"{DOWNLOAD_HANDLER}?filename={link}"
    raise RuntimeError(
        "DESE: could not find Finance Data file in MCDS home page"
    )


def download() -> tuple[bytes, str]:
    """Authenticate, resolve the file URL, and download the XLS.

    Returns (xls_bytes, source_url) where source_url is the resolved
    handler URL with the current GUID prefix (changes per release).
    """
    s = _new_session()
    _signin(s)
    file_url = _resolve_finance_file_url(s)
    r = s.get(file_url, timeout=300)
    r.raise_for_status()
    return r.content, file_url


def parse_mo_finance(
    xls_bytes: bytes, fiscal_year: int
) -> list[dict]:
    """Return [{code, total_op_exp}] from the {fiscal_year} sheet.

    The sheet's first 2 rows are branding; row 3 (0-indexed 2) is the
    real header. Last row is 'STATE TOTALS' (no district code).
    """
    sheet_name = str(fiscal_year)
    df = pd.read_excel(
        io.BytesIO(xls_bytes), sheet_name=sheet_name, header=2,
    )
    # Drop rows where district code is missing/non-numeric (totals row,
    # header artifacts).
    df = df[df["COUNTY DISTRICT CODE"].notna()]
    df["COUNTY DISTRICT CODE"] = df["COUNTY DISTRICT CODE"].astype(
        str
    ).str.replace(r"\.0$", "", regex=True)
    df = df[df["COUNTY DISTRICT CODE"].str.match(r"^\d+$", na=False)]

    out: list[dict] = []
    for _, row in df.iterrows():
        try:
            amt = float(row["TOTAL EXPENDITURE"] or 0)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        code = str(row["COUNTY DISTRICT CODE"]).zfill(6)
        out.append({
            "code": code,
            "total_op_exp": amt,
        })
    return out


def build_mo_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("MO-"):
            out[sl.removeprefix("MO-").strip().zfill(6)] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual",
            xls_path: str | None = None) -> dict:
    print(f"MO actuals extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        if xls_path:
            print(f"  reading from {xls_path} (skip auth flow)...")
            with open(xls_path, "rb") as f:
                xls_bytes = f.read()
            source_url = f"file://{xls_path}"
        else:
            print(
                f"  authenticating to DESE + resolving file URL "
                f"({USER_AGENT_NOTE})..."
            )
            xls_bytes, source_url = download()
            print(f"  resolved file URL: {source_url[:120]}...")

        content_hash = sha256_bytes(xls_bytes)
        print(f"  {len(xls_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/dese_finance_summary.xls"
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
                content=xls_bytes,
                mime_type="application/vnd.ms-excel",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=source_url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/vnd.ms-excel",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                f"Sheet '{fiscal_year}', header row 3; column "
                f"'TOTAL EXPENDITURE' per row; COUNTY DISTRICT CODE "
                f".zfill(6) == state_leaid suffix"
            ),
            notes=(
                f"FY{fiscal_year} MO DESE MCDS Finance Summary. Auth "
                f"flow: passwordless 2-step DESEApplicationsSignin → "
                f"auto-form bridge → cookies → "
                f"FileDownloadWebHandler.ashx. GUID prefix in filename "
                f"changes per release; resolved by parsing MCDS home."
            ),
        )

        crosswalk = build_mo_crosswalk(client)
        print(f"  MO crosswalk: {len(crosswalk):,} state→NCES mappings")

        records = parse_mo_finance(xls_bytes, fiscal_year)
        print(f"  Finance summary records (FY{fiscal_year}): {len(records):,}")

        no_match: list[str] = []
        for d in records:
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
            f"unmatched DESE codes (charters / non-master): {len(no_match)}"
        )
        if no_match[:5]:
            print(f"  sample unmatched: {no_match[:8]}")

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
    p.add_argument(
        "--xls-path",
        default=None,
        help="Local XLS path (skip DESE auth flow; used for testing)",
    )
    args = p.parse_args()
    extract(
        fiscal_year=args.fiscal_year,
        triggered_by=args.triggered_by,
        xls_path=args.xls_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
