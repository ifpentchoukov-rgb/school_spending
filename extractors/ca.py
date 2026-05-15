"""California extractor — CDE SACS Unaudited Actual Financial Data.

Source: https://www.cde.ca.gov/ds/fd/fd/
File:   sacs{YY1}{YY2}.exe (self-extracting archive containing a Microsoft
        Access .mdb). Released annually around February.

Pipeline:
  1. Download sacs{YYYY}.exe → SHA-256 → upload to Supabase Storage `ca`
  2. unzip the .exe to extract the .mdb
  3. mdb-export → UserGL.csv (general ledger) and LEAs.csv (LEA roster)
  4. Aggregate UserGL: Object 1000-7999 in Funds 01-29 per (Ccode, Dcode)
     == 'all governmental funds operating expenditures', the topline that
     matches F-33 'current expenditures' as closely as SACS allows
  5. Match LEAs to NCES via state_leaid 'CA-{Ccode}{Dcode}' (7-digit CDS)
  6. For YoY: also process sacs{prior}.exe in memory (not stored as a
     source_document — it's input to the computation, not the final source).

Status: `actual` (SACS reports unaudited actuals).

System dep: mdbtools (`brew install mdbtools` on macOS, `apt install
mdbtools` on Linux).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from io import BytesIO
from pathlib import Path

import pandas as pd
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

EXTRACTOR_NAME = "ca"
STATE = "CA"
BUCKET = "ca"
SOURCE_PORTAL_URL = "https://www.cde.ca.gov/ds/fd/fd/"
PUBLISHER = "California Department of Education"
DOCUMENT_TYPE = "sacs_unaudited_actuals_mdb"
TOPLINE_DEFINITION = (
    "CDE SACS Object codes 1000-7999 in Funds 01-29 (governmental funds), "
    "summed per LEA"
)


def fy_codes(fiscal_year: int) -> tuple[str, str]:
    """2025 → ('2425', '23-24'). Returns (compact, hyphenated) shortcodes
    used in CDE filenames and folder paths."""
    start = fiscal_year - 1
    compact = f"{start % 100:02d}{fiscal_year % 100:02d}"
    hyphenated = f"{start % 100:02d}-{fiscal_year % 100:02d}"
    return compact, hyphenated


def exe_url(fiscal_year: int) -> str:
    compact, _ = fy_codes(fiscal_year)
    start = fiscal_year - 1
    folder = f"20{start % 100:02d}-{fiscal_year % 100:02d}"
    return f"https://www3.cde.ca.gov/fiscal-downloads/sacs_data/{folder}/sacs{compact}.exe"


def download(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "school-budget-tracker/0.1"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def extract_mdb_tables(exe_bytes: bytes, mdb_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Unzip the EXE in a temp dir, mdb-export UserGL and LEAs to CSV, parse."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        exe_path = tdp / "sacs.exe"
        exe_path.write_bytes(exe_bytes)
        subprocess.run(
            ["unzip", "-o", str(exe_path), mdb_name, "-d", str(tdp)],
            check=True,
            capture_output=True,
        )
        mdb_path = tdp / mdb_name
        ugl_csv = subprocess.check_output(["mdb-export", str(mdb_path), "UserGL"])
        leas_csv = subprocess.check_output(["mdb-export", str(mdb_path), "LEAs"])
    ugl = pd.read_csv(BytesIO(ugl_csv), dtype=str, low_memory=False)
    leas = pd.read_csv(BytesIO(leas_csv), dtype=str)
    return ugl, leas


def compute_topline(ugl: pd.DataFrame) -> pd.DataFrame:
    """(Ccode, Dcode) → exp_total (Object 1000-7999, Funds 01-29)."""
    df = ugl[["Ccode", "Dcode", "Fund", "Object", "Value"]].copy()
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["Object_int"] = pd.to_numeric(df["Object"], errors="coerce")
    df["Fund_int"] = pd.to_numeric(df["Fund"], errors="coerce")
    mask = (
        df["Object_int"].between(1000, 7999, inclusive="both")
        & df["Fund_int"].between(1, 29, inclusive="both")
    )
    out = (
        df[mask]
        .groupby(["Ccode", "Dcode"])["Value"]
        .sum()
        .reset_index()
        .rename(columns={"Value": "exp_total"})
    )
    return out


# Phase 7.5 — CA SACS Function code → canonical category. 4-digit
# Function codes within topline filter (Funds 01-29, Object 1000-7999).
def _ca_func_to_category(fn: int) -> str | None:
    if 1000 <= fn <= 1999:
        return "instruction"
    if 2000 <= fn <= 2999:
        return "support_services_instruction"
    if 3100 <= fn <= 3199:
        return "support_services_student"  # Counseling/Health/Psych
    if 3600 <= fn <= 3699:
        return "transportation"
    if 3700 <= fn <= 3799:
        return "food_service"
    if 7000 <= fn <= 7999:
        return "administration"
    if 8000 <= fn <= 8999:
        return "operations_maintenance"
    if 9100 <= fn <= 9199:
        return "debt_service"
    return None


def compute_components(ugl: pd.DataFrame) -> dict[tuple[str, str], dict[str, float]]:
    """(Ccode, Dcode) → {canonical_category: amount}. Computed within the
    same Funds 01-29 / Object 1000-7999 mask as topline so component
    sums are a strict decomposition of the topline."""
    df = ugl[["Ccode", "Dcode", "Fund", "Object", "Function", "Value"]].copy()
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["Object_int"] = pd.to_numeric(df["Object"], errors="coerce")
    df["Fund_int"] = pd.to_numeric(df["Fund"], errors="coerce")
    df["Function_int"] = pd.to_numeric(df["Function"], errors="coerce")
    mask = (
        df["Object_int"].between(1000, 7999, inclusive="both")
        & df["Fund_int"].between(1, 29, inclusive="both")
        & df["Function_int"].notna()
    )
    sub = df[mask].copy()
    sub["category"] = sub["Function_int"].astype(int).apply(_ca_func_to_category)
    func_rolled = (
        sub[sub["category"].notna()]
        .groupby(["Ccode", "Dcode", "category"])["Value"]
        .sum()
        .reset_index()
    )
    # Phase 7.5 — capital_outlay = Object 6000-6999 (within topline mask).
    # Note SACS already captures this in topline (Object 6XXX is part of
    # 1000-7999), so this is a *slice* of topline, not additive outside it.
    cap_mask = (
        df["Object_int"].between(6000, 6999, inclusive="both")
        & df["Fund_int"].between(1, 29, inclusive="both")
    )
    cap = (
        df[cap_mask]
        .groupby(["Ccode", "Dcode"])["Value"]
        .sum()
        .reset_index()
        .rename(columns={"Value": "amount"})
    )
    cap["category"] = "capital_outlay"
    cap = cap[["Ccode", "Dcode", "category", "amount"]].rename(
        columns={"amount": "Value"}
    )
    # employee_benefits = Object 3000-3999 (within topline mask)
    ben_mask = (
        df["Object_int"].between(3000, 3999, inclusive="both")
        & df["Fund_int"].between(1, 29, inclusive="both")
    )
    ben = (
        df[ben_mask]
        .groupby(["Ccode", "Dcode"])["Value"]
        .sum()
        .reset_index()
        .rename(columns={"Value": "amount"})
    )
    ben["category"] = "employee_benefits"
    ben = ben[["Ccode", "Dcode", "category", "amount"]].rename(
        columns={"amount": "Value"}
    )
    all_components = pd.concat([func_rolled, cap, ben], ignore_index=True)
    out: dict[tuple[str, str], dict[str, float]] = {}
    for _, r in all_components.iterrows():
        key = (r["Ccode"], r["Dcode"])
        out.setdefault(key, {})
        out[key].setdefault(r["category"], 0.0)
        out[key][r["category"]] += float(r["Value"])
    return out


def build_ca_crosswalk(client: Client) -> dict[str, dict]:
    """state_leaid suffix (7-digit CDS) → district row."""
    rows = fetch_all(
        client.table("districts")
        .select("leaid, lea_name, state_leaid")
        .eq("state_postal", STATE)
        .eq("is_operating_district", True)
    )
    out: dict[str, dict] = {}
    for r in rows:
        sl = r.get("state_leaid") or ""
        if sl.startswith("CA-"):
            out[sl.removeprefix("CA-")] = r
    return out


def extract(*, fiscal_year: int = 2025, triggered_by: str = "manual") -> dict:
    if not shutil.which("mdb-export"):
        sys.exit("mdb-export not found on PATH. Install mdbtools: `brew install mdbtools`.")

    compact, _ = fy_codes(fiscal_year)
    prior_compact, _ = fy_codes(fiscal_year - 1)
    print(f"CA extract: fiscal_year={fiscal_year} (sacs{compact} + sacs{prior_compact} for YoY)")

    with Run(extractor_name=EXTRACTOR_NAME, triggered_by=triggered_by) as run:
        client = run.client

        url_curr = exe_url(fiscal_year)
        url_prior = exe_url(fiscal_year - 1)

        print(f"  downloading {url_curr.rsplit('/',1)[-1]}...")
        exe_curr = download(url_curr)
        print(f"    {len(exe_curr)/1e6:.1f} MB")
        print(f"  downloading {url_prior.rsplit('/',1)[-1]}... (for YoY)")
        exe_prior = download(url_prior)
        print(f"    {len(exe_prior)/1e6:.1f} MB")

        content_hash = sha256_bytes(exe_curr)
        storage_relpath = f"fy{fiscal_year}/sacs{compact}.exe"

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
                content=exe_curr,
                mime_type="application/x-msdownload",
            )

        src_id = upsert_source_document_row(
            client=client,
            content_hash=content_hash,
            source_url=url_curr,
            storage_path=f"{BUCKET}/{storage_relpath}",
            mime_type="application/x-msdownload",
            publisher=PUBLISHER,
            document_type=DOCUMENT_TYPE,
            line_or_cell_reference=(
                f"sacs{compact}.mdb table 'UserGL'; aggregate Value where "
                "Object 1000-7999 and Fund 01-29; group by (Ccode, Dcode)"
            ),
            notes=(
                f"FY{fiscal_year} unaudited actual SACS data. "
                f"Prior-year baseline computed in-memory from sacs{prior_compact}.exe; "
                "that file is not stored as a separate source_document since it's "
                "intermediate computation, not the source of these records."
            ),
        )

        print("  parsing UserGL + LEAs from current year...")
        ugl_curr, leas_curr = extract_mdb_tables(exe_curr, f"sacs{compact}.mdb")
        topline_curr = compute_topline(ugl_curr)
        print(f"    {len(topline_curr):,} (Ccode,Dcode) totals")
        # Phase 7.5 — canonical category breakdown (current FY only)
        components_curr = compute_components(ugl_curr)
        print(f"    components computed for {len(components_curr):,} LEAs")

        print("  parsing UserGL from prior year for YoY baseline...")
        ugl_prior, _ = extract_mdb_tables(exe_prior, f"sacs{prior_compact}.mdb")
        topline_prior = compute_topline(ugl_prior).rename(
            columns={"exp_total": "exp_total_prior"}
        )

        leas_curr["Dname"] = leas_curr["Dname"].str.strip()
        leas_curr["cds_district"] = leas_curr["Ccode"] + leas_curr["Dcode"]
        df = leas_curr.merge(topline_curr, on=["Ccode", "Dcode"], how="left").merge(
            topline_prior, on=["Ccode", "Dcode"], how="left"
        )

        crosswalk = build_ca_crosswalk(client)
        print(f"  CA crosswalk: {len(crosswalk):,} state→NCES mappings")

        no_match = []
        no_topline = 0
        n_components_inserted = 0
        n_components_updated = 0
        n_components_unchanged = 0
        for _, row in df.iterrows():
            district = crosswalk.get(row["cds_district"])
            if district is None:
                no_match.append(row["cds_district"])
                continue
            if pd.isna(row.get("exp_total")):
                no_topline += 1
                continue

            topline = float(row["exp_total"])
            prior = (
                None if pd.isna(row.get("exp_total_prior"))
                else float(row["exp_total_prior"])
            )
            yoy_dollars = (topline - prior) if prior else None
            yoy_pct = (yoy_dollars / prior * 100) if prior else None

            event = BudgetEventInput(
                leaid=district["leaid"],
                fiscal_year=fiscal_year,
                status="actual",
                topline_amount=topline,
                topline_definition=TOPLINE_DEFINITION,
                source_document_id=src_id,
                extraction_run_id=run.run_id,
                yoy_change_pct=yoy_pct,
                yoy_change_dollars=yoy_dollars,
                prior_year_baseline=prior,
            )
            event_id, changed = upsert_budget_event_with_supersession(
                client=client, event=event
            )
            run.records_extracted += 1
            if changed:
                run.records_changed += 1

            # Phase 7.5 — canonical category components
            comp_dict = components_curr.get(
                (row["Ccode"], row["Dcode"]), {}
            )
            components: list[ComponentInput] = []
            for category, amount in comp_dict.items():
                if amount <= 0:
                    continue
                components.append(
                    ComponentInput(
                        category=category,
                        amount=float(amount),
                        definition=(
                            f"CDE SACS UserGL: sum Value where (Ccode, Dcode) "
                            f"= ({row['Ccode']}, {row['Dcode']}) AND Fund "
                            f"01-29 AND Object 1000-7999 AND Function maps to "
                            f"'{category}' per _ca_func_to_category "
                            f"(employee_benefits = Object 3000-3999; "
                            f"capital_outlay = Object 6000-6999)"
                        ),
                        line_or_cell_reference=(
                            f"sacs{compact}.mdb UserGL; Ccode={row['Ccode']} "
                            f"Dcode={row['Dcode']}; per _ca_func_to_category "
                            f"+ Object range slices"
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
            f"no-topline={no_topline}; unmatched LEAs={len(no_match)}"
        )
        print(
            f"  components: inserted={n_components_inserted} "
            f"updated={n_components_updated} unchanged={n_components_unchanged}"
        )

    return {
        "fiscal_year": fiscal_year,
        "records_extracted": run.records_extracted,
        "records_changed": run.records_changed,
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
