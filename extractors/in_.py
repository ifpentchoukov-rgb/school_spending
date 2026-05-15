"""Indiana extractor — DUAB School Corporation Fiscal Indicators (SCFI).

Source: https://hub.mph.in.gov/dataset/school-corporation-fiscal-indicators-dashboard-data-set
File: scfi-data-{YYYY}-release-adm-fund-balances-deficit-surplus-1.xlsx
      (Indiana Data Hub, dataset UUID stable; resource UUID + file name
      include the release year, so we map per FY in KNOWN_FILE_URLS.)

What this gives us:
  - Per-corp current operating expenditures for every IN school
    corporation (290 corps in 2024 release). DUAB-mandated dataset
    under IC 20-19-7; 'Annual Deficit Surplus' sheet has revenue,
    expenditure, deficit/surplus, and fund balance per fund per year.

Topline definition:
  Annual Deficit Surplus sheet — sum of `Expenditure` per Corp ID
  where `Fund Classification` is in:
    Education Fund, Operational Funds, Operating Referendum Fund,
    Federal Funds, Federal Stimulus Funds, State Funds, Local Funds,
    Self-Insurance Funds, Rainy Day Fund.
  Excludes Debt Funds, Capital Funds, Capital Referendum Fund,
  School Safety Referendum Fund (debt service + capital construction).
  Aligned with F-33 'current expenditures' frame (instruction +
  support services + non-instructional + categorical/grant operating).

Status: `actual` — post-AFR audited (DUAB pulls from SBOA-reviewed
Gateway Annual Financial Report submissions).

Indiana school corporation fiscal year is calendar year (Jan-Dec, per
IC 20-40-1). Latest release as of 2026-05-06: 2025-release with data
through CY 2024 (= our fiscal_year=2024). Charters mostly file outside
Gateway; SCFI covers 290 traditional school corporations and select
charter networks.

Crosswalk:
  Master state_leaid format: 'IN-{4-digit}' (e.g. 'IN-5385' Indianapolis)
  SCFI Corp ID:              4-digit string (e.g. '5385')
  → strip IN- prefix == Corp ID directly.
"""

from __future__ import annotations

import argparse
import io
import sys

import httpx
import openpyxl
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

EXTRACTOR_NAME = "in"
STATE = "IN"
BUCKET = "in"
SOURCE_PORTAL_URL = (
    "https://hub.mph.in.gov/dataset/school-corporation-fiscal-indicators-dashboard-data-set"
)
PUBLISHER = "Indiana Distressed Unit Appeal Board (DUAB) / Indiana Management Performance Hub"
DOCUMENT_TYPE = "in_scfi_deficit_surplus_xlsx"
TOPLINE_DEFINITION = (
    "DUAB School Corporation Fiscal Indicators (SCFI), 'Annual Deficit "
    "Surplus' sheet — sum of Expenditure per Corp ID where Fund "
    "Classification is in {Education Fund, Operational Funds, Operating "
    "Referendum Fund, Federal Funds, Federal Stimulus Funds, State "
    "Funds, Local Funds, Self-Insurance Funds, Rainy Day Fund}. "
    "Excludes Debt Funds, Capital Funds, Capital/Safety Referendum "
    "Funds (debt service + capital construction). Aligned with F-33 "
    "'current expenditures' frame."
)
USER_AGENT = "school-budget-tracker/0.1 (https://github.com/ifpentchoukov-rgb/school_spending)"

OPERATING_CLASSES = {
    "Education Fund",
    "Operational Funds",
    "Operating Referendum Fund",
    "Federal Funds",
    "Federal Stimulus Funds",
    "State Funds",
    "Local Funds",
    "Self-Insurance Funds",
    "Rainy Day Fund",
}

# Phase 7.5 — universal floor mapping for IN. Fund Classification values
# from the SCFI sheet that map to canonical categories. The topline
# excludes these (debt + capital); we surface them as components.
IN_COMPONENT_FUND_CLASSES: dict[str, tuple[set[str], str]] = {
    "debt_service": (
        {"Debt Funds"},
        "DUAB SCFI Annual Deficit Surplus — sum Expenditure where "
        "Fund Classification='Debt Funds' (principal + interest on bonds)",
    ),
    "capital_outlay": (
        {"Capital Funds", "Capital Referendum Fund", "School Safety Referendum Fund"},
        "DUAB SCFI Annual Deficit Surplus — sum Expenditure where "
        "Fund Classification in {Capital Funds, Capital Referendum Fund, "
        "School Safety Referendum Fund}",
    ),
}

KNOWN_FILE_URLS: dict[int, str] = {
    # 2025-release covers CY 2014-2024; URL pinned to current release.
    # Update this map when DUAB publishes a 2026-release with CY 2025.
    2024: (
        "https://hub.mph.in.gov/dataset/2f29f743-ecbf-412c-873b-7657139ff9e8"
        "/resource/2a22f5fe-0f05-4cd6-ae2f-9420865522a7/download"
        "/scfi-data-2025-release-adm-fund-balances-deficit-surplus-1.xlsx"
    ),
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    """Use httpx — urllib chokes on this server's chunked-encoding tail."""
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True
    ) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.content


def parse_deficit_surplus(xlsx_bytes: bytes, cal_year: int) -> list[dict]:
    """Return [{code, total_op_exp, components}] from the Annual Deficit
    Surplus sheet. Topline = sum Expenditure across OPERATING_CLASSES;
    components = per-category sums from IN_COMPONENT_FUND_CLASSES (debt,
    capital) which are excluded from topline."""
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb["Annual Deficit Surplus"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    expected = (
        "Corp ID", "Corp Name", "Cal Year", "Fund", "Fund Name",
        "Fund Classification", "Revenue", "Revenue Exception",
        "Expenditure",
    )
    if header[:9] != expected:
        raise RuntimeError(
            f"Unexpected SCFI Annual Deficit Surplus header: {header[:9]}"
        )
    totals: dict[str, float] = {}
    # Map: corp_id -> {category: amount}
    components: dict[str, dict[str, float]] = {}
    # Reverse-index fund class -> category
    fund_to_category: dict[str, str] = {}
    for category, (fund_classes, _def) in IN_COMPONENT_FUND_CLASSES.items():
        for fc in fund_classes:
            fund_to_category[fc] = category
    for r in rows:
        if not r or r[0] is None:
            continue
        if r[2] != cal_year:
            continue
        fund_class = r[5]
        exp = r[8]
        if exp is None:
            continue
        try:
            amt = float(exp)
        except (TypeError, ValueError):
            continue
        code = str(r[0]).strip()
        if fund_class in OPERATING_CLASSES:
            totals[code] = totals.get(code, 0.0) + amt
        elif fund_class in fund_to_category:
            cat = fund_to_category[fund_class]
            components.setdefault(code, {})[cat] = (
                components.get(code, {}).get(cat, 0.0) + amt
            )
    return [
        {
            "code": code,
            "total_op_exp": amt,
            "components": components.get(code, {}),
        }
        for code, amt in totals.items()
        if amt > 0
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


def extract(*, fiscal_year: int = 2024, triggered_by: str = "manual") -> dict:
    print(f"IN extract: fiscal_year={fiscal_year} (CY {fiscal_year})")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No SCFI URL for fiscal_year={fiscal_year}; "
                "add to KNOWN_FILE_URLS when next DUAB release lands."
            )
        print(f"  downloading {url.rsplit('/', 1)[-1]}...")
        xlsx_bytes = download(url)
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.1f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/scfi_deficit_surplus.xlsx"

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
                content=xlsx_bytes,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                "Sheet 'Annual Deficit Surplus'; filter Cal Year=N AND "
                "Fund Classification in OPERATING_CLASSES; sum Expenditure "
                "per Corp ID; match Corp ID == state_leaid suffix"
            ),
            notes=(
                f"CY{fiscal_year} DUAB SCFI; covers ~290 IN school "
                "corporations (charters mostly file outside Gateway/SCFI)."
            ),
        )

        crosswalk = build_in_crosswalk(client)
        print(f"  IN crosswalk: {len(crosswalk):,} state→NCES mappings")

        district_data = parse_deficit_surplus(xlsx_bytes, cal_year=fiscal_year)
        print(f"  SCFI corps with operating exp for CY{fiscal_year}: {len(district_data):,}")

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

            # Phase 7.5 — universal floor: debt + capital from Fund Classification
            components: list[ComponentInput] = []
            for category, amount in d.get("components", {}).items():
                if amount <= 0:
                    continue
                fund_classes, definition = IN_COMPONENT_FUND_CLASSES[category]
                components.append(
                    ComponentInput(
                        category=category,
                        amount=float(amount),
                        definition=definition,
                        line_or_cell_reference=(
                            f"Sheet 'Annual Deficit Surplus'; sum Expenditure "
                            f"where Corp ID={d['code']} AND Cal Year={fiscal_year} "
                            f"AND Fund Classification in {sorted(fund_classes)}"
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
            f"unmatched SCFI corp IDs: {len(no_match)}"
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
    p.add_argument("--fiscal-year", type=int, default=2024,
                   help="IN school FY = calendar year (Jan-Dec)")
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
