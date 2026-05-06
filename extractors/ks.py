"""Kansas extractor — Kansas Open Gov per-district per-pupil spending CSV.

Source: https://kansasopengov.org/databank/school-spending-per-pupil-database/
File: Spending-per-Pupil-Database.csv — re-publishes KSDE Comparative
Performance and Fiscal System (CPFS) data as a single multi-year CSV
(USD 101..512 across years 2005..latest). KSDE's primary public web
portal (ksde.gov/.../Total-Expenditures-by-District) is currently a
404; their CPFS at datacentral.ksde.gov is interactive-only. Kansas
Open Gov is the most reliable bulk pipeline.

What this gives us:
  - Per-USD per-FY operating expenditure broken down by 8 categories
    (Instruction, Student Support, Staff Support, Administration,
    Operations & Maintenance, Transportation, Food Service, Other),
    plus excluded Capital and Debt Service. Values are dollars per
    weighted FTE pupil — multiply by enrollment_fy25 to recover
    total dollars.

Topline definition:
  Sum of 8 operating per-pupil columns × master.enrollment_fy25 — i.e.
  (Total - Capital - DebtService) per pupil × enrollment. Reconstructs
  per-district operating expenditure from KSDE's per-pupil view.
  Aligned with F-33 'current expenditures' frame; excludes Capital
  Outlay (Function 4XXX) and Debt Service (Function 5XXX).

Status: `actual` — KSDE-published from district AFR submissions.

Caveats:
  - Reconstructed total = per-pupil × master enrollment. KSDE uses
    weighted FTE enrollment as their per-pupil divisor; if our
    enrollment_fy25 differs (typically <2%) the recovered total will
    differ proportionally. Verifier reviews flag any >5% delta from
    public reporting.
  - When master enrollment_fy25 is null we skip the LEA.

Crosswalk:
  Master state_leaid format: 'KS-D{4-digit}' (e.g. 'KS-D0259' Wichita)
  Kansas Open Gov USDNumber: integer (e.g. 259)
  → strip 'KS-D' prefix → int() → match USDNumber.
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

EXTRACTOR_NAME = "ks"
STATE = "KS"
BUCKET = "ks"
SOURCE_PORTAL_URL = "https://kansasopengov.org/databank/school-spending-per-pupil-database/"
PUBLISHER = "Kansas Policy Institute (Kansas Open Gov) — re-publishing KSDE Comparative Performance & Fiscal System (CPFS)"
DOCUMENT_TYPE = "kansas_opengov_spending_per_pupil_csv"
TOPLINE_DEFINITION = (
    "Kansas Open Gov 'Spending per Pupil Database' CSV (KSDE CPFS "
    "re-publication) — per-district operating per-pupil = Total - "
    "Capital - DebtService = sum(Instruction, Student Support, Staff "
    "Support, Administration, Operations & Maintenance, Transportation, "
    "Food Service, Other). Multiplied by master enrollment_fy25 to "
    "reconstruct total dollars. Aligned with F-33 'current expenditures' "
    "frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

CSV_URL = "https://kansasopengov.org/wp-content/uploads/2023/07/Spending-per-Pupil-Database.csv"


def download(url: str = CSV_URL) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _to_int(s: str | None) -> int:
    if s is None or s == "":
        return 0
    try:
        return int(s.replace(",", "").replace('"', ""))
    except (TypeError, ValueError):
        return 0


def parse_ks(csv_bytes: bytes, fiscal_year: int) -> list[dict]:
    """Return [{usd: int, per_pupil_op: int}] for the given fiscal_year."""
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    rdr = csv.DictReader(io.StringIO(text))
    out: list[dict] = []
    for row in rdr:
        if row.get("Year") != str(fiscal_year):
            continue
        try:
            usd = int(row["USDNumber"])
        except (TypeError, ValueError, KeyError):
            continue
        # Skip the *Statewide aggregate row (USD 999)
        if usd >= 900:
            continue
        op = (
            _to_int(row.get("Instruction"))
            + _to_int(row.get("StudentSupport"))
            + _to_int(row.get("StaffSupport"))
            + _to_int(row.get("Administration"))
            + _to_int(row.get("OperationsMaint"))
            + _to_int(row.get("Transportation"))
            + _to_int(row.get("FoodService"))
            + _to_int(row.get("Other"))
        )
        if op <= 0:
            continue
        out.append({"usd": usd, "per_pupil_op": op})
    return out


def build_ks_crosswalk(client: Client) -> dict[int, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid, enrollment_fy25")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[int, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        suffix = sl.removeprefix("KS-").lstrip("D").lstrip("0") or "0"
        try:
            usd = int(suffix)
        except ValueError:
            continue
        out[usd] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"KS extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        print(f"  downloading {CSV_URL.rsplit('/', 1)[-1]}...")
        csv_bytes = download()
        content_hash = sha256_bytes(csv_bytes)
        print(f"  {len(csv_bytes) / 1e6:.2f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/spending_per_pupil_database.csv"

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
            source_url=CSV_URL,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="text/csv",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "Filter Year=N; sum 8 per-pupil operating cols; multiply "
                "by master enrollment_fy25; match USDNumber == "
                "lstrip('KS-D0', state_leaid)"
            ),
            notes=f"FY{fiscal_year} Kansas Open Gov per-pupil spending (KSDE CPFS source)",
        )

        crosswalk = build_ks_crosswalk(client)
        print(f"  KS crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_ks(csv_bytes, fiscal_year=fiscal_year)
        print(f"  KS Open Gov USDs with FY{fiscal_year} data: {len(district_data):,}")

        no_match: list[str] = []
        no_enroll: list[int] = []
        for d in district_data:
            district = crosswalk.get(d["usd"])
            if district is None:
                no_match.append(str(d["usd"]))
                continue
            enrollment = district.get("enrollment_fy25")
            if not enrollment or enrollment <= 0:
                no_enroll.append(d["usd"])
                continue

            total_op_exp = float(d["per_pupil_op"]) * float(enrollment)
            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="actual",
                topline_amount=total_op_exp,
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
            f"unmatched USDs: {len(no_match)}; missing enrollment: {len(no_enroll)}"
        )

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
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
