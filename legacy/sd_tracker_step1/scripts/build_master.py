"""
Build master school district table.

Inputs:
  1. CCD LEA Universe (school year 2024-25, FY25)  via Urban Institute API
  2. Census Bureau F-33 elsec23.xlsx (FY23 audited)  — already downloaded

Output:
  - processed/master_districts.csv   — full table with FY23 baseline
  - processed/master_districts.xlsx  — same data, summary stats sheet

Run from: /home/claude/sd_tracker/scripts
"""

import json
import time
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

import pandas as pd

from state_tiers import STATE_TIERS, get_tier

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
PROCESSED = ROOT / "processed"
PROCESSED.mkdir(exist_ok=True)

ELSEC23 = RAW / "elsec23.xlsx"
DIRECTORY_CACHE = RAW / "ccd_directory_2024.json"

# ---------------------------------------------------------------------------
# CCD agency type / level decoders (per CCD documentation)
# ---------------------------------------------------------------------------
AGENCY_TYPE = {
    1: "Regular local school district",
    2: "Local school district that is component of a supervisory union",
    3: "Supervisory union administrative center",
    4: "Regional Education Service Agency (RESA)",
    5: "State-operated agency",
    6: "Federally-operated agency",
    7: "Independent charter district",
    8: "Other",
    9: "Specialized PK-12 school district",
}

AGENCY_LEVEL = {
    # "Agency Level Code" — describes data-reporting scope, not operational
    # status. Level 4 = LEA reports at district level (the real operating
    # universe). Level 1-3 = state/federal-level reporting.
    1: "State-level only",
    2: "Federal-level only",
    3: "State + district level",
    4: "District-level (operating)",
}

# Districts that actually adopt operating budgets (vs. service agencies, charter
# authorizers that don't operate schools, etc.). This is the universe we'll
# track approval status for.
OPERATING_AGENCY_TYPES = {1, 2, 7, 9}
OPERATING_AGENCY_LEVEL = 4


# ---------------------------------------------------------------------------
# Step 1: fetch CCD directory from Urban Institute API
# ---------------------------------------------------------------------------
def fetch_ccd_directory(year=2024, force=False):
    """Fetch full LEA directory by iterating states. Cached on disk."""
    if DIRECTORY_CACHE.exists() and not force:
        print(f"[cache] loading {DIRECTORY_CACHE.name}")
        with DIRECTORY_CACHE.open() as f:
            return json.load(f)

    base = f"https://educationdata.urban.org/api/v1/school-districts/ccd/directory/{year}/"
    all_records = []

    for fips, (postal, tier, _note) in sorted(STATE_TIERS.items()):
        url = f"{base}?fips={int(fips)}"
        for attempt in range(3):
            try:
                req = Request(url, headers={"User-Agent": "sd-tracker/0.1"})
                with urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode())
                break
            except URLError as e:
                if attempt == 2:
                    raise
                print(f"  retry {postal} (attempt {attempt + 1}): {e}")
                time.sleep(2 ** attempt)

        n = data.get("count", 0)
        all_records.extend(data.get("results", []))
        print(f"  {postal} ({fips}): {n:>5} records")
        time.sleep(0.15)  # be polite

    print(f"[total] {len(all_records)} LEA records fetched")
    with DIRECTORY_CACHE.open("w") as f:
        json.dump(all_records, f)
    return all_records


# ---------------------------------------------------------------------------
# Step 2: load FY23 finance baseline
# ---------------------------------------------------------------------------
FINANCE_COLUMNS = {
    "NCESID": "leaid",
    "NAME": "elsec_name",
    "FIPST": "fips",
    "STATE": "state_postal_elsec",     # Census state postal code (numeric)
    "V33": "enrollment_fy23",
    "TOTALREV": "rev_total_fy23",
    "TOTALEXP": "exp_total_fy23",
    "TCURELSC": "exp_current_elsec_fy23",
    "TCURINST": "exp_current_instruction_fy23",
    "SCHLEV": "schlev",
}


def load_finance_baseline():
    print(f"[load] {ELSEC23.name}")
    df = pd.read_excel(ELSEC23, sheet_name="elsec23", dtype={"NCESID": str})
    df = df[list(FINANCE_COLUMNS.keys())].rename(columns=FINANCE_COLUMNS)

    # Census F-33 reports values in thousands of dollars. Convert to dollars
    # for joinability with future state-level data which usually reports
    # in actual dollars.
    money_cols = [
        "rev_total_fy23",
        "exp_total_fy23",
        "exp_current_elsec_fy23",
        "exp_current_instruction_fy23",
    ]
    for c in money_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce") * 1000

    df["leaid"] = df["leaid"].astype(str).str.zfill(7)
    print(f"  {len(df):,} rows; "
          f"{df['leaid'].nunique():,} unique LEAIDs")
    return df


# ---------------------------------------------------------------------------
# Step 3: build master table
# ---------------------------------------------------------------------------
def build_master_table(directory_records, finance_df):
    dir_df = pd.DataFrame(directory_records)
    dir_df["leaid"] = dir_df["leaid"].astype(str).str.zfill(7)

    # Decode types/levels to readable strings for the output CSV
    dir_df["agency_type_label"] = dir_df["agency_type"].map(AGENCY_TYPE)
    dir_df["agency_level_label"] = dir_df["agency_level"].map(AGENCY_LEVEL)
    dir_df["is_operating_district"] = (
        dir_df["agency_type"].isin(OPERATING_AGENCY_TYPES)
        & (dir_df["agency_level"] == OPERATING_AGENCY_LEVEL)
        & (dir_df["number_of_schools"].fillna(0) > 0)
    )

    # State tier columns
    tier_rows = []
    for fips_int in dir_df["fips"]:
        postal, tier, note = get_tier(fips_int)
        tier_rows.append({
            "state_postal": postal,
            "data_tier": tier,
            "data_source_note": note,
        })
    tier_df = pd.DataFrame(tier_rows, index=dir_df.index)
    dir_df = pd.concat([dir_df, tier_df], axis=1)

    # Slim the directory to just the columns we want in the master
    keep_dir = [
        "leaid", "lea_name", "state_postal", "fips",
        "state_leaid",
        "city_location", "county_name",
        "agency_type", "agency_type_label",
        "agency_level", "agency_level_label",
        "is_operating_district",
        "agency_charter_indicator",
        "lowest_grade_offered", "highest_grade_offered",
        "number_of_schools", "enrollment",
        "data_tier", "data_source_note",
    ]
    dir_slim = dir_df[keep_dir].copy()
    dir_slim = dir_slim.rename(columns={"enrollment": "enrollment_fy25"})

    # Merge with finance
    finance_slim = finance_df.drop(
        columns=["elsec_name", "fips", "state_postal_elsec", "schlev"]
    )
    master = dir_slim.merge(finance_slim, on="leaid", how="left")

    # FY27 cycle classification — districts in the middle of adopting their
    # FY27 (school year 2026-27) operating budget right now (May 2026).
    # July fiscal-year states are most of the country; Sept-fiscal states
    # (TX, AL) are also relevant.
    master["target_fiscal_year"] = "FY27"
    master["target_school_year"] = "2026-27"
    master["fy_calendar"] = master["state_postal"].map(
        lambda p: "Sept-Aug" if p in {"TX", "AL"} else "July-June"
    )

    return master


# ---------------------------------------------------------------------------
# Step 4: write outputs
# ---------------------------------------------------------------------------
def write_outputs(master):
    csv_path = PROCESSED / "master_districts.csv"
    master.to_csv(csv_path, index=False)
    print(f"[write] {csv_path.relative_to(ROOT)} "
          f"({len(master):,} rows, {len(master.columns)} cols)")

    # Summary statistics
    operating = master[master["is_operating_district"]]
    summary_by_state = (
        operating.groupby("state_postal")
        .agg(
            districts=("leaid", "count"),
            charter_districts=("agency_type",
                               lambda s: (s == 7).sum()),
            total_enrollment_fy25=("enrollment_fy25", "sum"),
            total_exp_fy23=("exp_total_fy23", "sum"),
            finance_matched=("exp_total_fy23",
                             lambda s: s.notna().sum()),
            data_tier=("data_tier", "first"),
        )
        .reset_index()
        .sort_values("state_postal")
    )
    summary_by_state["match_rate_pct"] = (
        summary_by_state["finance_matched"]
        / summary_by_state["districts"] * 100
    ).round(1)

    tier_summary = (
        operating.groupby("data_tier")
        .agg(
            states=("state_postal", "nunique"),
            districts=("leaid", "count"),
            total_enrollment_fy25=("enrollment_fy25", "sum"),
            total_exp_fy23=("exp_total_fy23", "sum"),
        )
        .reset_index()
    )

    # Known quirks / data caveats
    notes = pd.DataFrame([
        {"topic": "NYC",
         "note": "NYC is split into 32 'geographic districts' in CCD; "
                 "consolidated finances roll up to NYC DOE under a separate "
                 "LEAID. NY-specific extractor will reconcile these."},
        {"topic": "Charter districts",
         "note": "Independent charter LEAs (agency_type=7) often report "
                 "finance data inconsistently or roll up to authorizer. "
                 "Expect ~70% finance-match rate on this subset."},
        {"topic": "FY calendar",
         "note": "Texas and Alabama districts run Sept-Aug fiscal year. "
                 "All others use July-June. FY27 adoption window is "
                 "May-Sept 2026 for July-June states."},
        {"topic": "Finance baseline",
         "note": "FY23 = school year 2022-23 audited actuals from "
                 "Census Bureau F-33 (released April 2025). Most recent "
                 "fully audited national dataset available."},
        {"topic": "Universe definition",
         "note": "Operating district = agency_type in {1,2,7,9} AND "
                 "agency_level=4 (district-level reporting) AND "
                 "number_of_schools > 0."},
    ])

    xlsx_path = PROCESSED / "master_districts.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        master_xlsx_cols = [
            "leaid", "lea_name", "state_postal", "county_name",
            "agency_type_label", "agency_level_label",
            "is_operating_district", "enrollment_fy25",
            "rev_total_fy23", "exp_total_fy23",
            "exp_current_elsec_fy23", "exp_current_instruction_fy23",
            "data_tier", "data_source_note",
            "target_fiscal_year", "fy_calendar",
        ]
        master[master_xlsx_cols].to_excel(
            writer, sheet_name="master", index=False
        )
        summary_by_state.to_excel(
            writer, sheet_name="by_state", index=False
        )
        tier_summary.to_excel(writer, sheet_name="by_tier", index=False)
        notes.to_excel(writer, sheet_name="notes", index=False)
    print(f"[write] {xlsx_path.relative_to(ROOT)}")
    return csv_path, xlsx_path, summary_by_state, tier_summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    force = "--refresh" in sys.argv

    print("=" * 60)
    print("Step 1/3 — Fetch CCD LEA Universe (school year 2024-25)")
    print("=" * 60)
    records = fetch_ccd_directory(year=2024, force=force)

    print("\n" + "=" * 60)
    print("Step 2/3 — Load FY23 finance baseline (Census F-33)")
    print("=" * 60)
    finance = load_finance_baseline()

    print("\n" + "=" * 60)
    print("Step 3/3 — Build & write master table")
    print("=" * 60)
    master = build_master_table(records, finance)
    csv_path, xlsx_path, by_state, by_tier = write_outputs(master)

    print("\n" + "=" * 60)
    print("Tier coverage summary")
    print("=" * 60)
    print(by_tier.to_string(index=False))

    print(f"\nTotal LEAs in directory:        {len(master):,}")
    op = master[master['is_operating_district']]
    print(f"Operating districts:            {len(op):,}")
    print(f"  with FY23 finance match:      "
          f"{op['exp_total_fy23'].notna().sum():,}")
    print(f"  unmatched (no FY23 finance):  "
          f"{op['exp_total_fy23'].isna().sum():,}")
    print(f"Total operating enrollment:     "
          f"{op['enrollment_fy25'].sum():,.0f}")
    print(f"Total FY23 expenditure:         "
          f"${op['exp_total_fy23'].sum() / 1e9:,.1f}B")


if __name__ == "__main__":
    main()
