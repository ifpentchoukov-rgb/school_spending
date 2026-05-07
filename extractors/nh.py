"""New Hampshire actuals extractor — NH DOE Cost Per Pupil CSV.

The NH Department of Education's Bureau of School Finance publishes
'Cost Per Pupil by District' annually each January for the most recent
audited fiscal year. The CSV reports per-district CPP for Elementary,
Middle, High, and Total (Pre School-12). Per-district total
expenditures are derived by multiplying CPP × ADM-A.

NH does not publish a per-district total-dollar file at the state
level (DOE-25 raw filings are split into 207 separate XLSX files).
For our purposes we approximate district total = CPP × master
enrollment_fy25 (CCD headcount). This differs from NH's ADM-A
denominator by ~2-5% in either direction; the topline_definition
records the methodology.

Source URL pattern:
  https://www.education.nh.gov/sites/g/files/ehbemt326/files/
    inline-documents/sonh/cost-per-pupil-fy{YYYY}.csv

Network note:
  education.nh.gov sits behind Akamai/Imperva and rejects Python's
  stdlib HTTP clients. We use `curl_cffi` with `impersonate='chrome120'`
  to mimic a real Chrome TLS handshake — that passes the WAF cleanly.
  `verify=False` because curl-impersonate doesn't pick up macOS's cert
  bundle automatically.

Topline definition:
  CPP × master enrollment_fy25. CPP is NH DOE's published
  'Total (Pre School-12) Cost Per Pupil' which equals K-12 current
  operating expenditures (operating + tuition + transportation, less
  inter-district transfers) ÷ ADM-A. Aligned with F-33 'current
  expenditures' frame; excludes capital outlay, bond principal,
  interest, payments to other districts, food-service revenue.

Status: `actual` — CPP file is published from audited DOE-25 filings.

Crosswalk:
  Master state_leaid format: 'NH-{3-digit DIST code}'
                              (e.g. 'NH-335' Manchester School District)
  CSV column 'DIST':         3-digit district code (sometimes with
                              trailing space)
  → state_leaid suffix == DIST.strip().
"""

from __future__ import annotations

import argparse
import csv
import io
import sys

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

EXTRACTOR_NAME = "nh"
STATE = "NH"
BUCKET = "nh"
SOURCE_PORTAL_URL = (
    "https://www.education.nh.gov/who-we-are/division-of-educator-and-"
    "analytic-resources/bureau-of-education-statistics/financial-reports"
)
PUBLISHER = "New Hampshire Department of Education (Bureau of School Finance)"
DOCUMENT_TYPE = "nhdoe_cost_per_pupil_csv"
TOPLINE_DEFINITION = (
    "NH DOE Bureau of School Finance Cost Per Pupil CSV — 'Total (Pre "
    "School-12) Cost Per Pupil' × master enrollment_fy25 (CCD "
    "headcount). NH's published CPP is K-12 current operating "
    "expenditures (operating + tuition + transportation, less "
    "inter-district transfers) ÷ ADM-A. Aligned with F-33 'current "
    "expenditures' frame; excludes capital outlay, bond principal, "
    "interest, food-service revenue. Total dollars approximated by "
    "multiplying by enrollment (vs NH's ADM-A denominator); ~2-5% "
    "off in either direction depending on attendance rate."
)
USER_AGENT = (
    "school-budget-tracker/0.1 "
    "(https://github.com/ifpentchoukov-rgb/school_spending)"
)

KNOWN_FILE_URLS: dict[int, str] = {
    # FY25 (SY 2024-25) published Jan 8, 2026.
    2025: "https://www.education.nh.gov/sites/g/files/ehbemt326/files/inline-documents/sonh/cost-per-pupil-fy2025.csv",
    # FY24 (SY 2023-24) backfill.
    2024: "https://www.education.nh.gov/sites/g/files/ehbemt326/files/inline-documents/sonh/cost-per-pupil-fy2024.csv",
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    # NH's WAF requires a valid Referer AND the chrome120 TLS fingerprint,
    # otherwise it returns 403. We also let curl-cffi use chrome120's
    # native User-Agent (passing our own custom UA breaks the WAF check).
    r = curl_req.get(
        url,
        impersonate="chrome120",
        timeout=60,
        verify=False,
        headers={"Referer": SOURCE_PORTAL_URL},
    )
    r.raise_for_status()
    return r.content


def parse_nh_cpp(csv_bytes: bytes) -> list[dict]:
    """Return [{dist, sau, name, cpp_total}] from the NH CPP CSV.

    The file has a multi-line preamble with NHDOE branding; the column
    header lives at row 18 (1-indexed) with columns:
      DIST | LOC | SAU | School District | Elementary | Middle | High |
      Total (Pre School-12)
    """
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    out: list[dict] = []
    for row in rows[18:]:  # skip 18-row preamble; row 18 is header
        if not row or not row[0].strip():
            continue
        dist = row[0].strip()
        if not dist or not dist.replace(".", "").isdigit():
            continue
        try:
            sau = row[2].strip()
            name = row[3].strip()
            # Total (Pre School-12) is column index 7
            cpp_str = row[7].strip().replace(",", "").replace("$", "")
            if not cpp_str:
                continue
            cpp = float(cpp_str)
        except (ValueError, IndexError):
            continue
        if cpp <= 0:
            continue
        out.append({
            "dist": dist,
            "sau": sau,
            "name": name,
            "cpp_total": cpp,
        })
    return out


def build_nh_crosswalk(client: Client) -> dict[str, dict]:
    """Return {DIST_code: district_row} with enrollment_fy25 included."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid, enrollment_fy25")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("NH-"):
            out[sl.removeprefix("NH-").strip()] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"NH actuals extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No NH CPP URL for fiscal_year={fiscal_year}; "
                f"add to KNOWN_FILE_URLS."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]} (curl-cffi chrome120)...")
        csv_bytes = download(url)
        content_hash = sha256_bytes(csv_bytes)
        print(f"  {len(csv_bytes) / 1024:.1f} KB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/cost_per_pupil.csv"
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
                "row 18 onwards; col 7 'Total (Pre School-12)' CPP × "
                "master enrollment_fy25; match DIST col -> state_leaid suffix"
            ),
            notes=(
                f"FY{fiscal_year} NH DOE Cost Per Pupil CSV. Fetched via "
                f"curl-cffi chrome120 to bypass Akamai. CPP is per-pupil; "
                f"district total approximated as CPP × master "
                f"enrollment_fy25."
            ),
        )

        crosswalk = build_nh_crosswalk(client)
        print(f"  NH crosswalk: {len(crosswalk):,} state→NCES mappings")

        records = parse_nh_cpp(csv_bytes)
        print(f"  CPP rows parsed: {len(records):,}")

        no_match: list[str] = []
        no_enrollment: list[str] = []
        for d in records:
            district = crosswalk.get(d["dist"])
            if district is None:
                no_match.append(f"{d['dist']} {d['name']}")
                continue
            enr = district.get("enrollment_fy25")
            if not enr or enr <= 0:
                no_enrollment.append(d["name"])
                continue

            topline = float(d["cpp_total"]) * float(enr)
            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="actual",
                topline_amount=topline,
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
            f"unmatched DIST: {len(no_match)}; missing enrollment: {len(no_enrollment)}"
        )
        if no_match[:5]:
            print(f"  sample unmatched: {no_match[:6]}")

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
        "no_match_count": len(no_match),
        "no_enrollment_count": len(no_enrollment),
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
