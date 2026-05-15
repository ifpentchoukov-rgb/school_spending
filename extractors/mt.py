"""Montana extractor — OPI School Expenditures (OPIEXP) per-LE detail.

Source: https://opi.mt.gov/Leadership/Finance-Grants/School-Finance/OPI-Financial-Data-Files
File: OPIEXP{YY}.xlsx — one sheet per pivot view; sheet
'ExpByLineItemByLE' has detail rows by County × LE × Fund × Program ×
Function × Object.

What this gives us:
  - Per-LE expenditure detail across ~418 Montana LE codes (much
    larger than master's 64 K-12-equivalent districts; the rest are
    small elementary-only or HS-only LEs not in master).

Topline definition:
  Sheet 'ExpByLineItemByLE': sum of SumOfAmount per LE where
  FunctionCode starts with '1', '2', or '3' (Instruction, Support
  Services, Non-Instructional). Excludes Function 4XXX (Facilities
  Acquisition / Capital) and 5XXX (Debt Service / Other Outlays).
  Aligned with F-33 'current expenditures' frame.

Status: `actual` — post-AFR audited.

Crosswalk:
  Master state_leaid format: 'MT-{4-digit}' (only K-12 equivalents)
  XLSX LE col:               4-digit string (e.g. '0003')
  → state_leaid suffix == LE directly.

Note: MT has many elementary-only and HS-only LEs that share
boundaries with a master K-12 district; these don't have a 1:1 match
and won't be captured here. Master coverage is the K-12 set only.
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.error
import urllib.request

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

EXTRACTOR_NAME = "mt"
STATE = "MT"
BUCKET = "mt"
SOURCE_PORTAL_URL = "https://opi.mt.gov/Leadership/Finance-Grants/School-Finance/OPI-Financial-Data-Files"
PUBLISHER = "Montana Office of Public Instruction"
DOCUMENT_TYPE = "mt_opi_expenditures_xlsx"
TOPLINE_DEFINITION = (
    "OPI School Expenditures (OPIEXP) workbook, sheet "
    "'ExpByLineItemByLE': sum of SumOfAmount per LE where Function "
    "code starts with 1, 2, or 3 (Instruction + Support Services + "
    "Non-Instructional). Excludes Function 4XXX (Capital) and 5XXX "
    "(Debt). Aligned with F-33 'current expenditures' frame."
)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

KNOWN_FILE_URLS: dict[int, str] = {
    2025: "https://opi.mt.gov/Portals/182/Page%20Files/School%20Finance/OPI%20Financial%20Data%20Files/School%20Budget%20and%20Expenditure%20Data/School%20Expenditures/School%20Expenditures/OPIEXP25.xlsx?ver=2026-02-18-062820-677",
}


def file_url(fiscal_year: int) -> str | None:
    return KNOWN_FILE_URLS.get(fiscal_year)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# Phase 7.5 — MT Function-code → canonical category. The OPIEXP file
# rolls Function codes up to 3-digit + 'X' level (e.g. '21XX', '23XX')
# or 2-digit + 'XX' (e.g. '1XXX', '4XXX'). String-prefix match.
_MT_FUNC_PREFIX_TO_CATEGORY: dict[str, str | None] = {
    "1XXX": "instruction",
    "21XX": "support_services_student",
    "221X": "support_services_instruction",
    "222X": "support_services_instruction",
    "23XX": "administration",
    "24XX": "administration",
    "25XX": "administration",
    "258X": "administration",
    "26XX": "operations_maintenance",
    "27XX": "transportation",
    "31XX": "food_service",
    "32XX": None,  # enterprise
    "33XX": None,  # community
    "34XX": None,  # extracurricular activities
    "35XX": None,  # extracurricular athletics
    "3XXX": None,  # generic non-educational
    "4XXX": "capital_outlay",
    "51XX": "debt_service",
    "52XX": "debt_service",
    "53XX": "debt_service",
    "61XX": None,  # transfers
    "62XX": None,
    "9999": None,
}


def _mt_func_to_category(fc: str) -> str | None:
    return _MT_FUNC_PREFIX_TO_CATEGORY.get(fc.strip() if fc else "")


def parse_mt(xlsx_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb["ExpByLineItemByLE"]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # row 0: total
    next(rows)  # row 1: header
    totals: dict[str, float] = {}
    components: dict[str, dict[str, float]] = {}
    for r in rows:
        if not r or r[2] is None:
            continue
        le = str(r[2]).strip()
        if not le:
            continue
        # OPIEXP stores Function as 3-digit-prefix + 'X' (e.g. '1XXX',
        # '21XX', '23XX'). Pure string; no numeric coercion.
        func_code = str(r[9]).strip() if r[9] is not None else ""
        amt = r[13]
        if amt is None:
            continue
        try:
            v = float(amt)
        except (TypeError, ValueError):
            continue
        if func_code and func_code[0] in ("1", "2", "3"):
            totals[le] = totals.get(le, 0.0) + v
        # Phase 7.5 — canonical category breakdown (includes 4XXX + 5XXX)
        category = _mt_func_to_category(func_code)
        if category is not None and v > 0:
            components.setdefault(le, {}).setdefault(category, 0.0)
            components[le][category] += v
    return [
        {
            "code": code,
            "total_op_exp": v,
            "components": components.get(code, {}),
        }
        for code, v in totals.items()
        if v > 0
    ]


def build_mt_crosswalk(client: Client) -> dict[str, dict]:
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("MT-"):
            out[sl.removeprefix("MT-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    print(f"MT extract: fiscal_year={fiscal_year}")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url = file_url(fiscal_year)
        if not url:
            raise RuntimeError(
                f"No OPI URL for fiscal_year={fiscal_year}; add to KNOWN_FILE_URLS."
            )
        print(f"  downloading OPIEXP{fiscal_year - 2000}.xlsx...")
        xlsx_bytes = download(url)
        content_hash = sha256_bytes(xlsx_bytes)
        print(f"  {len(xlsx_bytes) / 1e6:.1f} MB; sha256={content_hash[:12]}...")

        storage_relpath = f"fy{fiscal_year}/expenditures.xlsx"

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
                "Sheet 'ExpByLineItemByLE'; sum SumOfAmount per LE "
                "where FunctionCode[0] in (1,2,3); match LE == "
                "state_leaid suffix"
            ),
            notes=f"FY{fiscal_year} OPI School Expenditures (OPIEXP)",
        )

        crosswalk = build_mt_crosswalk(client)
        print(f"  MT crosswalk: {len(crosswalk):,} state→NCES mappings (K-12 only)")

        district_data = parse_mt(xlsx_bytes)
        print(f"  MT LEs in file: {len(district_data):,}")

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

            components: list[ComponentInput] = []
            for category, amount in d.get("components", {}).items():
                if amount <= 0:
                    continue
                components.append(
                    ComponentInput(
                        category=category,
                        amount=float(amount),
                        definition=(
                            f"OPI OPIEXP 'ExpByLineItemByLE': sum SumOfAmount "
                            f"where LE={d['code']} AND FunctionCode maps to "
                            f"'{category}' per NCES function-range bucketing"
                        ),
                        line_or_cell_reference=(
                            f"Sheet 'ExpByLineItemByLE'; LE={d['code']}; "
                            f"function-code range bucketing per _mt_func_to_category"
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
            f"unmatched MT LEs (elementary-only/HS-only not in master): {len(no_match)}"
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
    p.add_argument("--fiscal-year", type=int, default=2025)
    p.add_argument("--triggered-by", default="manual",
                   choices=["cron", "manual", "backfill"])
    args = p.parse_args()
    extract(fiscal_year=args.fiscal_year, triggered_by=args.triggered_by)
    return 0


if __name__ == "__main__":
    sys.exit(main())
