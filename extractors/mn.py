"""Minnesota actuals extractor — MDE MFR UFR020 PDFs.

Per Minnesota Statutes 2024, section 123B.10, every MN school district
files Annual UFARS (Uniform Financial Accounting and Reporting Standards)
data with the MN Department of Education. MDE publishes per-district
'2-Year Comparison Reports (Revenues and Expenditures)' as report
UFR020 in the Minnesota Funding Reports (MFR) WebFOCUS portal. Each
district's UFR020 PDF has 3 pages: Revenue Comparison, Expenditure
Comparison, and General Ledger Comparison.

Source URL pattern (FY25 example):
  https://pub.education.mn.gov/mfrreports/UFR020/{YEAR}/{padded}.pdf

Where:
  - YEAR = '24-25' for FY25 (= our fiscal_year=2025)
  - padded = WebFOCUS district code (XXXX-YY) with dash stripped and
    right-padded with zeros to 16 chars: e.g. '0001-03' -> '0001030000000000'

Network/auth notes:
  pub.education.mn.gov sits behind a Reblaze/Stormcaster (Perfdrive)
  captcha. Discovery of the report-fetch flow required:
  1. The user solved the captcha in their browser at
     https://pub.education.mn.gov/MDEAnalytics/DataTopic.jsp?TOPICID=9
  2. Captured DevTools Cookie header AND a 'Copy as cURL' for the
     WebFOCUS POST that fires on 'Display Report'.
  3. We discovered that WFServlet.ibfs is just an HTML wrapper that
     embeds a direct PDF URL at /mfrreports/UFR020/{year}/{padded}.pdf
     — this PDF URL accepts session cookies and is reproducible.

  The session cookies from the user's solve last ~30 minutes. After
  that, the cookies need to be refreshed by re-solving the captcha.
  We store them in `MN_COOKIES_FILE` (default `~/.config/mn-cookies.txt`)
  so the extractor can be re-run without re-solving each time during
  the cookie window.

Topline definition:
  Page 2 of UFR020 PDF, line 'CURRENT OPERATING EXPENDITURES' under
  CATEGORY - FUNDS 1,2,8 (General Fund + Food Service + Trust). This
  excludes Capital Outlay (separate line), Building Construction
  Fund 06, and Debt Service Fund 07. Aligned with F-33 'current
  expenditures' frame.

Status: `actual` — UFR020 contains audited UFARS data.

Crosswalk:
  Master state_leaid format: 'MN-{2-digit-type}{4-digit-number}'
                              (e.g. 'MN-030001' Minneapolis)
  WebFOCUS district code:    '{4-digit-number}-{2-digit-type}'
                              (e.g. '0001-03')
  → Convert master suffix 'YYXXXX' -> 'XXXX-YY'.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pdfplumber
from curl_cffi import requests as curl_req
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

EXTRACTOR_NAME = "mn"
STATE = "MN"
BUCKET = "mn"
SOURCE_PORTAL_URL = "https://pub.education.mn.gov/MDEAnalytics/DataTopic.jsp?TOPICID=9"
PUBLISHER = "Minnesota Department of Education (Division of School Finance)"
DOCUMENT_TYPE = "mde_mfr_ufr020_pdf"
TOPLINE_DEFINITION = (
    "MDE MFR UFR020 ('2-Year Comparison Reports') PDF, page 2 'EXPENDITURE "
    "COMPARISON', line 'CURRENT OPERATING EXPENDITURES' under CATEGORY - "
    "FUNDS 1,2,8 (General + Food Service + Trust). Excludes Capital "
    "Outlay (separate line), Building Construction Fund 06, and Debt "
    "Service Fund 07. F-33 'current expenditures' frame."
)

REPORT_NAME = "UFR020"

# Cookies file format: a single line with the entire Cookie header value
# (semicolon-separated key=value pairs), as captured from DevTools.
# Override with the MN_COOKIES env var to point at a different path.
DEFAULT_COOKIES_PATH = Path(
    os.environ.get(
        "MN_COOKIES_FILE",
        Path.home() / ".config" / "mn-cookies.txt",
    )
)


def _load_cookies(path: Path | None = None) -> str:
    p = path or DEFAULT_COOKIES_PATH
    if not p.exists():
        raise RuntimeError(
            f"MN cookies file not found at {p}. "
            f"Solve the Reblaze/Stormcaster captcha at "
            f"{SOURCE_PORTAL_URL}, then save the DevTools Cookie header "
            f"value to that file. Set MN_COOKIES_FILE env var to override "
            f"the path."
        )
    text = p.read_text().strip()
    if not text:
        raise RuntimeError(f"MN cookies file at {p} is empty.")
    return text


def _to_webfocus_code(state_leaid: str) -> str | None:
    """Convert master 'MN-YYXXXX' (6 digits after MN-) to WebFOCUS 'XXXX-YY'."""
    suf = state_leaid.removeprefix("MN-")
    if len(suf) != 6 or not suf.isdigit():
        return None
    return f"{suf[2:]}-{suf[:2]}"


def _padded(district_code: str) -> str:
    """e.g. '0001-03' -> '0001030000000000' (strip dash, right-pad to 16)."""
    raw = district_code.replace("-", "")
    return raw + "0" * (16 - len(raw))


def _pdf_url(fiscal_year: int, district_code: str) -> str:
    yy1 = (fiscal_year - 1) % 100
    yy2 = fiscal_year % 100
    yy = f"{yy1:02d}-{yy2:02d}"
    return (
        f"https://pub.education.mn.gov/mfrreports/{REPORT_NAME}/"
        f"{yy}/{_padded(district_code)}.pdf"
    )


def _fetch_pdf(url: str, cookies: str, max_attempts: int = 3) -> bytes | None:
    """Fetch a single MFR PDF. Returns bytes if HTTP 200 + %PDF; None
    if 404 (district doesn't have a UFR020 for the year)."""
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            r = curl_req.get(
                url,
                impersonate="chrome120",
                verify=False,
                timeout=45,
                headers={
                    "Cookie": cookies,
                    "Referer": "https://pub.education.mn.gov/",
                },
            )
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return r.content
            if r.status_code == 404:
                return None
            # Other non-200 codes — retry
            last_err = RuntimeError(
                f"Unexpected status {r.status_code}; size={len(r.content)}"
            )
        except Exception as e:
            last_err = e
        time.sleep(0.5 * (2 ** attempt))
    if last_err:
        raise last_err
    return None


# Regex: 'CURRENT OPERATING EXPENDITURES' followed by 2 dollar amounts
# (FY-1 actual, FY actual) and a percent diff. Numbers can have commas
# and decimals; percent can have minus suffix.
_CURRENT_OP_RE = re.compile(
    r"CURRENT OPERATING EXPENDITURES\s+"
    r"([\d,]+\.\d{2})\s+"     # FY-1
    r"([\d,]+\.\d{2})\s+"     # FY (current)
    r"([\d,.\-]+)",            # % diff
    re.M,
)

# Phase 7.5 — UFR020 page-2 line labels → canonical category. Within
# CATEGORY - FUNDS 1,2,8 block plus the separate Capital/Building/Debt
# lines below. PUPIL TRANSPORTAION (sic) is misspelled in the PDF.
_MN_LINE_TO_CATEGORY: list[tuple[str, str]] = [
    ("DISTRICT & SCHOOL ADMINISTRATION", "administration"),
    ("DISTRICT SUPPORT SERVICES", "support_services_instruction"),
    ("REGULAR INSTRUCTION", "instruction"),
    ("VOCATIONAL INSTRUCTION", "instruction"),
    ("SPECIAL EDUCATION INSTRUCTION", "instruction"),
    ("INSTRUCTIONAL SUPPORT SERVICES", "support_services_instruction"),
    ("PUPIL SUPPORT SERVICES", "support_services_student"),
    ("OPERATIONS & MAINTENANCE", "operations_maintenance"),
    ("FOOD SERVICE", "food_service"),
    ("PUPIL TRANSPORTAION", "transportation"),  # PDF misspelling intentional
    ("OTHER OPERATING PROGRAMS", "other"),
    ("CAPITAL OUTLAY - FUNDS 1,2,8", "capital_outlay"),
    ("BUILDING CONSTRUCTION FUND 06", "capital_outlay"),
    ("DEBT SERVICE FUND 07", "debt_service"),
]


def _parse_amount(text: str, label: str) -> float | None:
    """Find LABEL followed by FY-1 amount + FY amount + pct on the same
    line. Returns the FY (current) amount, or None if the line is missing
    or has no values (e.g. FOOD SERVICE blank for some districts)."""
    # Escape regex metachars in label, allow flexible whitespace
    safe = re.escape(label).replace(r"\ ", r"\s+")
    pat = (
        rf"{safe}\s+([\d,]+\.\d{{2}})\s+([\d,]+\.\d{{2}})\s+[\d,.\-]+"
    )
    m = re.search(pat, text)
    if not m:
        return None
    try:
        return float(m.group(2).replace(",", ""))
    except ValueError:
        return None


def parse_ufr020_pdf(pdf_bytes: bytes) -> tuple[int | None, dict[str, float]]:
    """Extract CURRENT OPERATING EXPENDITURES (current FY column) and
    canonical-category components from UFR020 PDF page 2. Returns
    (topline_int, components_dict)."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as p:
            if len(p.pages) < 2:
                return None, {}
            text = p.pages[1].extract_text() or ""
    except Exception:
        return None, {}

    m = _CURRENT_OP_RE.search(text)
    topline = None
    if m:
        try:
            topline = int(round(float(m.group(2).replace(",", ""))))
        except (ValueError, TypeError):
            topline = None

    components: dict[str, float] = {}
    for label, category in _MN_LINE_TO_CATEGORY:
        v = _parse_amount(text, label)
        if v and v > 0:
            components[category] = components.get(category, 0.0) + v
    return topline, components


def build_mn_crosswalk(client: Client) -> dict[str, dict]:
    """Return {WebFOCUS code: district_row} for active MN LEAs."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        wf = _to_webfocus_code(sl)
        if wf:
            out[wf] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual",
            cookies_path: str | None = None,
            max_workers: int = 6) -> dict:
    print(f"MN actuals extract: fiscal_year={fiscal_year}")

    cookies = _load_cookies(Path(cookies_path) if cookies_path else None)

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        crosswalk = build_mn_crosswalk(client)
        print(f"  MN crosswalk: {len(crosswalk):,} state→NCES mappings")

        # First fetch the manifest doc (we hash the crosswalk as the canonical
        # 'set of districts queried this run'; per-district PDFs are not
        # individually stored to avoid Storage bloat).
        import json
        manifest_bytes = json.dumps(
            sorted(
                [{"webfocus_code": k, "leaid": v["leaid"],
                  "lea_name": v["lea_name"]} for k, v in crosswalk.items()],
                key=lambda r: r["webfocus_code"],
            ),
            ensure_ascii=False,
        ).encode("utf-8")
        content_hash = sha256_bytes(manifest_bytes)
        print(f"  manifest sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/ufr020_manifest.json"
        existing_src = (
            client.table("source_documents")
            .select("id")
            .eq("content_hash_sha256", content_hash)
            .execute()
        )
        if not existing_src.data:
            upload_source_document(
                client=client,
                bucket=BUCKET,
                storage_path=storage_relpath,
                content=manifest_bytes,
                mime_type="application/json",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=(
                "https://pub.education.mn.gov/mfrreports/UFR020/"
                f"{(fiscal_year-1)%100:02d}-{fiscal_year%100:02d}/"
                "{padded}.pdf (per-district)"
            ),
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/json",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "UFR020 PDF page 2 'CURRENT OPERATING EXPENDITURES' "
                "(current-FY column); WebFOCUS district code "
                "(state_leaid 'YYXXXX' -> 'XXXX-YY') -> 16-char zero-"
                "padded -> .pdf URL"
            ),
            notes=(
                f"FY{fiscal_year} MN MDE MFR UFR020 batch. Captcha "
                f"bypass via user-solved Reblaze cookies "
                f"(cookies expire ~30 min). Per-district PDFs not "
                f"stored individually (manifest only)."
            ),
        )

        n_total = len(crosswalk)
        n_done = 0
        n_pdf = 0
        n_parsed = 0
        no_pdf: list[str] = []
        parse_fail: list[str] = []

        print(f"  fetching {n_total} UFR020 PDFs ({max_workers}-way parallel)...")

        def worker(wfcode: str, district: dict):
            url = _pdf_url(fiscal_year, wfcode)
            try:
                pdf = _fetch_pdf(url, cookies)
            except Exception as e:
                return wfcode, district, None, str(e)
            return wfcode, district, pdf, None

        n_components_inserted = 0
        n_components_updated = 0
        n_components_unchanged = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [
                ex.submit(worker, wf, d)
                for wf, d in crosswalk.items()
            ]
            for fut in as_completed(futs):
                wfcode, district, pdf_bytes, err = fut.result()
                n_done += 1
                if pdf_bytes is None:
                    no_pdf.append(wfcode)
                else:
                    n_pdf += 1
                    topline, comp_dict = parse_ufr020_pdf(pdf_bytes)
                    if topline and topline > 0:
                        n_parsed += 1
                        event = BudgetEventInput(
                            leaid=district["leaid"],
                            fiscal_year=fiscal_year,
                            status="actual",
                            topline_amount=float(topline),
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

                        components: list[ComponentInput] = []
                        for category, amount in comp_dict.items():
                            if amount <= 0:
                                continue
                            components.append(
                                ComponentInput(
                                    category=category,
                                    amount=float(amount),
                                    definition=(
                                        f"MDE MFR UFR020 PDF page 2 line(s) "
                                        f"mapping to '{category}' (CATEGORY - "
                                        f"FUNDS 1,2,8 block + Building/Debt "
                                        f"fund lines), current-FY column"
                                    ),
                                    line_or_cell_reference=(
                                        f"UFR020 PDF p.2; WebFOCUS code "
                                        f"{wfcode}; per _MN_LINE_TO_CATEGORY"
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
                    else:
                        parse_fail.append(wfcode)
                if n_done % 50 == 0:
                    print(
                        f"    {n_done}/{n_total} done; "
                        f"pdf={n_pdf} parsed={n_parsed}"
                    )

        print(
            f"  inserted/changed={run.records_changed}/{run.records_extracted}; "
            f"pdf-fetched={n_pdf}/{n_total}; parse-fail={len(parse_fail)}; "
            f"no-pdf-published={len(no_pdf)}"
        )
        print(
            f"  components: inserted={n_components_inserted} "
            f"updated={n_components_updated} unchanged={n_components_unchanged}"
        )
        if parse_fail[:5]:
            print(f"  sample parse-fail: {parse_fail[:8]}")
        if no_pdf[:5]:
            print(f"  sample no-pdf: {no_pdf[:8]}")

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_pdf_count": len(no_pdf),
        "parse_fail_count": len(parse_fail),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=2025)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    p.add_argument(
        "--cookies-file",
        default=None,
        help=(
            "Path to file with MN MFR Cookie header value. Defaults to "
            f"{DEFAULT_COOKIES_PATH} (override with MN_COOKIES_FILE env)."
        ),
    )
    p.add_argument("--max-workers", type=int, default=6)
    args = p.parse_args()
    extract(
        fiscal_year=args.fiscal_year,
        triggered_by=args.triggered_by,
        cookies_path=args.cookies_file,
        max_workers=args.max_workers,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
