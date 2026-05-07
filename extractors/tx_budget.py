"""Texas adopted-budget extractor — TEA PEIMS Record 030.

Companion to extractors/tx.py (PEIMS actuals). Per TEC 44.004, TX
school districts adopt FY budgets by Aug 25 (LEA fiscal year is
Sep 1 – Aug 31, NOT Jul-Jun). TEA collects the board-adopted budget
via PEIMS Record 030 ('current school year ESC/LEA board adopted
budget') in the fall snapshot, and publishes bulk per-LEA + per-charter
CSVs each February.

Source URLs (FY26 = SY 2025-26 currently live, posted Feb 12, 2026):
  Districts: https://tea.texas.gov/reports-and-data/financial-reports/
             school-finance-reports-and-data/budget{YYYY}.zip
  Charters:  https://tea.texas.gov/finance-and-grants/
             state-funding/charbud{YY}.zip

Schema:
  Districts (budget{YYYY}.csv):
    DISTRICT, FUND, FUNDYEAR, FUNCTION, OBJECT, FIN_UNIT,
    PROGRAM_INTENT, BUDGAMT, DTUPDATE
  Charters (charbud{YY}.csv) — same concept, different column names:
    DISTRICT, CS_NONPROF_ASSET (=FUND), FISCALYR (=FUNDYEAR),
    CS_NONPROF_FUNC (=FUNCTION), CS_NONPROF_OBJ (=OBJECT),
    FIN_UNIT, CS_NONPROF_PGMIN, BUDGAMT, DTUPDATE

Topline definition:
  All-funds operating expenditures, F-33 'current expenditures' frame:
  sum(BUDGAMT) where OBJECT in 6100-6499 (payroll/services/supplies/other
  operating) and FUNCTION not in {00 (revenue), 71 (debt service),
  81 (facilities acquisition)}. Excludes Object 6500 (debt service),
  6600 (capital outlay) by object filter, and the corresponding
  FUNCTION 71/81 by function filter.

Status: `adopted` — PEIMS Record 030 is the board-adopted budget.

Crosswalk:
  Master state_leaid format: 'TX-{6-digit-CDN}'
                              (e.g. 'TX-101912' Houston ISD,
                                    'TX-227801' KIPP Texas charter)
  CSV column DISTRICT:        6-digit zero-padded County-District Number
  → state_leaid suffix == DISTRICT.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.error
import urllib.request
import zipfile

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

EXTRACTOR_NAME = "tx_budget"
STATE = "TX"
BUCKET = "tx"
SOURCE_PORTAL_URL = (
    "https://tea.texas.gov/finance-and-grants/state-funding/"
    "state-funding-reports-and-data/peims-financial-data-downloads"
)
PUBLISHER = "Texas Education Agency (PEIMS Financial Data)"
DOCUMENT_TYPE_DISTRICT = "tea_peims_record030_budget_csv"
DOCUMENT_TYPE_CHARTER = "tea_peims_charter_budget_csv"
TOPLINE_DEFINITION = (
    "TEA PEIMS Record 030 (board-adopted budget) — all-funds "
    "operating expenditures, F-33 'current expenditures' frame: "
    "sum(BUDGAMT) where OBJECT in 6100-6499 (payroll/services/"
    "supplies/other operating) and FUNCTION not in {00 (revenue), "
    "71 (debt service), 81 (facilities acquisition)}. Excludes "
    "Object 6500 (debt) + 6600 (capital outlay) by object filter."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"


def _district_url(fiscal_year: int) -> str:
    return (
        "https://tea.texas.gov/reports-and-data/financial-reports/"
        f"school-finance-reports-and-data/budget{fiscal_year}.zip"
    )


def _charter_url(fiscal_year: int) -> str:
    yy = fiscal_year % 100
    return (
        "https://tea.texas.gov/finance-and-grants/state-funding/"
        f"charbud{yy:02d}.zip"
    )


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def _read_zip_csv(zip_bytes: bytes) -> str:
    """Return the single .csv inside a one-file ZIP, decoded as UTF-8."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            raise RuntimeError(f"No .csv inside zip; contents: {zf.namelist()}")
        with zf.open(names[0]) as f:
            return f.read().decode("utf-8", errors="replace")


def _is_operating_row(func: str, obj: str) -> bool:
    """True if this row is operating expenditures per F-33 frame.

    OBJECT 6100-6499 = operating outlays (payroll, services, supplies,
    other operating). FUNCTION excludes:
      00 = balance-sheet / revenue rows
      71 = Debt Service
      81 = Facilities Acquisition / Construction
    """
    if not obj or len(obj) < 2:
        return False
    if obj[:2] not in {"61", "62", "63", "64"}:
        return False
    if func in {"00", "71", "81"}:
        return False
    return True


def parse_district_csv(csv_text: str) -> dict[str, float]:
    """{6-digit CDN: operating_budget_total} from district CSV."""
    rdr = csv.DictReader(io.StringIO(csv_text))
    totals: dict[str, float] = {}
    for row in rdr:
        if not _is_operating_row(row.get("FUNCTION", ""), row.get("OBJECT", "")):
            continue
        try:
            amt = float(row.get("BUDGAMT") or 0)
        except (TypeError, ValueError):
            continue
        if amt == 0:
            continue
        cdn = (row.get("DISTRICT") or "").strip()
        if not cdn:
            continue
        totals[cdn] = totals.get(cdn, 0.0) + amt
    return totals


def parse_charter_csv(csv_text: str) -> dict[str, float]:
    """{6-digit CDN: operating_budget_total} from charter CSV.

    Charter file uses CS_NONPROF_FUNC / CS_NONPROF_OBJ instead of
    FUNCTION / OBJECT.
    """
    rdr = csv.DictReader(io.StringIO(csv_text))
    totals: dict[str, float] = {}
    for row in rdr:
        func = row.get("CS_NONPROF_FUNC", "")
        obj = row.get("CS_NONPROF_OBJ", "")
        if not _is_operating_row(func, obj):
            continue
        try:
            amt = float(row.get("BUDGAMT") or 0)
        except (TypeError, ValueError):
            continue
        if amt == 0:
            continue
        cdn = (row.get("DISTRICT") or "").strip()
        if not cdn:
            continue
        totals[cdn] = totals.get(cdn, 0.0) + amt
    return totals


def build_tx_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("TX-"):
            out[sl.removeprefix("TX-")] = r
    return out


def _process_zip(
    *,
    client: Client,
    run: Run,
    crosswalk: dict[str, dict],
    fiscal_year: int,
    url: str,
    label: str,
    document_type: str,
    parse_fn,
    storage_filename: str,
) -> tuple[int, int, list[str]]:
    """Download → upload → parse → upsert events. Returns (n_extracted, n_changed, no_match)."""
    print(f"  [{label}] downloading {url.rsplit('/', 1)[-1]}...")
    zip_bytes = _download(url)
    content_hash = sha256_bytes(zip_bytes)
    print(f"  [{label}] {len(zip_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

    storage_relpath = f"fy{fiscal_year}/{storage_filename}"
    existing_src = (
        client.table("source_documents")
        .select("id")
        .eq("content_hash_sha256", content_hash)
        .execute()
    )
    if not existing_src.data:
        print(f"  [{label}] uploading to {BUCKET}/{storage_relpath}...")
        upload_source_document(
            client=client,
            bucket=BUCKET,
            storage_path=storage_relpath,
            content=zip_bytes,
            mime_type="application/zip",
        )

    src_id = upsert_source_document_row(
        client=client,
        content_hash=content_hash,
        source_url=url,
        storage_path=f"{BUCKET}/{storage_relpath}",
        mime_type="application/zip",
        publisher=PUBLISHER,
        document_type=document_type,
        line_or_cell_reference=(
            f"{label}: sum(BUDGAMT) where OBJECT in 6100-6499 and "
            f"FUNCTION not in (00, 71, 81); group by DISTRICT; "
            f"DISTRICT == state_leaid suffix"
        ),
        notes=f"FY{fiscal_year} TX PEIMS {label} adopted budget (Record 030)",
    )

    csv_text = _read_zip_csv(zip_bytes)
    district_totals = parse_fn(csv_text)
    print(f"  [{label}] LEAs with operating budget: {len(district_totals):,}")

    n_ext = 0
    n_chg = 0
    no_match: list[str] = []
    for cdn, amt in district_totals.items():
        if amt <= 0:
            continue
        district = crosswalk.get(cdn)
        if district is None:
            no_match.append(cdn)
            continue

        event = BudgetEventInput(
            leaid=district["leaid"],
            fiscal_year=fiscal_year,
            status="adopted",
            topline_amount=amt,
            topline_definition=TOPLINE_DEFINITION,
            source_document_id=src_id,
            extraction_run_id=run.run_id,
        )
        _, changed = upsert_budget_event_with_supersession(
            client=client, event=event
        )
        n_ext += 1
        if changed:
            n_chg += 1

    return n_ext, n_chg, no_match


def extract(*, fiscal_year: int = 2026, triggered_by: str = "manual") -> dict:
    print(f"TX adopted-budget extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        crosswalk = build_tx_crosswalk(client)
        print(f"  TX crosswalk: {len(crosswalk):,} state→NCES mappings")

        # Districts
        d_ext, d_chg, d_nm = _process_zip(
            client=client, run=run, crosswalk=crosswalk,
            fiscal_year=fiscal_year, url=_district_url(fiscal_year),
            label="districts", document_type=DOCUMENT_TYPE_DISTRICT,
            parse_fn=parse_district_csv,
            storage_filename=f"peims_budget_districts_{fiscal_year}.zip",
        )

        # Charters
        try:
            c_ext, c_chg, c_nm = _process_zip(
                client=client, run=run, crosswalk=crosswalk,
                fiscal_year=fiscal_year, url=_charter_url(fiscal_year),
                label="charters", document_type=DOCUMENT_TYPE_CHARTER,
                parse_fn=parse_charter_csv,
                storage_filename=f"peims_budget_charters_{fiscal_year}.zip",
            )
        except urllib.error.HTTPError as e:
            print(f"  [charters] download failed ({e.code}); skipping charter file.")
            c_ext, c_chg, c_nm = 0, 0, []

        run.records_extracted = d_ext + c_ext
        run.records_changed = d_chg + c_chg

        print(
            f"  inserted/changed={run.records_changed}/{run.records_extracted} "
            f"(districts: {d_chg}/{d_ext}, charters: {c_chg}/{c_ext}); "
            f"unmatched: districts={len(d_nm)}, charters={len(c_nm)}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_district": len(d_nm),
        "no_match_charter": len(c_nm),
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
