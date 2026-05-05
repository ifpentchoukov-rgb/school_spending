"""
Unified extractor runner.

Runs every available state extractor, stacks the outputs, joins to
master_districts.csv, and produces:

  processed/state_extractions.csv    - all extractor records, normalized
  processed/spending_signal.csv      - master + extracted joined; one row
                                       per district with status/topline/YoY
  processed/spending_signal.xlsx     - same with by_state and notes sheets
  processed/coverage_report.txt      - human-readable summary

Run from: /home/claude/sd_tracker/scripts
    python3 -m run_extractors
"""

import sys
from pathlib import Path

import pandas as pd

from extractors import _base, ca, fl, tx

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "processed"

# Roster of available state extractors. Order doesn't matter; each must
# expose extract() returning a DataFrame in the _base.OUTPUT_COLUMNS schema.
EXTRACTORS = {
    "TX": tx,
    "CA": ca,
    "FL": fl,
}


def run_all():
    print("=" * 60)
    print("Running state extractors")
    print("=" * 60)

    parts = []
    for postal, mod in EXTRACTORS.items():
        print(f"\n[{postal}] {mod.__name__}")
        try:
            df = mod.extract()
            issues = _base.validate(df)
            if issues:
                print(f"  VALIDATION ISSUES: {issues}")
                continue
            parts.append(df)
            print(f"  -> {len(df):,} records")
        except Exception as e:
            print(f"  EXTRACTOR FAILED: {e}")
            continue

    if not parts:
        print("No successful extractions; aborting.")
        sys.exit(1)

    extractions = pd.concat(parts, ignore_index=True)
    extractions["leaid"] = extractions["leaid"].astype(str).str.zfill(7)
    out_path = PROCESSED / "state_extractions.csv"
    extractions.to_csv(out_path, index=False)
    print(f"\n[write] {out_path.relative_to(ROOT)}: {len(extractions):,} rows")

    return extractions


def build_signal_table(extractions):
    """Join extractions to master_districts and produce one-row-per-district
    table with the latest available signal for each district."""
    print("\n" + "=" * 60)
    print("Joining to master & building signal table")
    print("=" * 60)

    master = pd.read_csv(
        PROCESSED / "master_districts.csv",
        dtype={"leaid": str, "state_leaid": str},
    )
    master = master[master["is_operating_district"]].copy()
    print(f"  master operating districts: {len(master):,}")

    # If a district has multiple records (multi-year), keep the latest fiscal year
    extractions_latest = (
        extractions.sort_values(["leaid", "fiscal_year"])
        .drop_duplicates("leaid", keep="last")
    )
    print(f"  extracted unique districts: {len(extractions_latest):,}")

    keep_master = [
        "leaid", "lea_name", "state_postal", "state_leaid",
        "county_name", "enrollment_fy25",
        "exp_total_fy23",
        "data_tier", "data_source_note",
        "target_fiscal_year", "fy_calendar",
    ]
    signal = master[keep_master].merge(
        extractions_latest.drop(columns=["state_postal", "state_leaid"]),
        on="leaid",
        how="left",
    )
    signal["has_extracted_signal"] = signal["topline_amount"].notna()

    # Direction column for easy filtering
    def _direction(row):
        d = row.get("yoy_change_dollars")
        if pd.isna(d):
            return "unknown"
        if d > 0:
            return "increased"
        if d < 0:
            return "decreased"
        return "flat"
    signal["direction"] = signal.apply(_direction, axis=1)

    csv_path = PROCESSED / "spending_signal.csv"
    signal.to_csv(csv_path, index=False)
    print(f"[write] {csv_path.relative_to(ROOT)}: "
          f"{len(signal):,} rows, "
          f"{signal['has_extracted_signal'].sum():,} with signal")

    # Excel summary
    by_state = (
        signal.groupby("state_postal")
        .agg(
            districts=("leaid", "count"),
            with_signal=("has_extracted_signal", "sum"),
            increased=("direction", lambda s: (s == "increased").sum()),
            decreased=("direction", lambda s: (s == "decreased").sum()),
            unknown=("direction", lambda s: (s == "unknown").sum()),
            total_topline=("topline_amount", "sum"),
            data_tier=("data_tier", "first"),
        )
        .reset_index()
        .sort_values("state_postal")
    )
    by_state["coverage_pct"] = (
        by_state["with_signal"] / by_state["districts"] * 100
    ).round(1)

    by_direction = (
        signal[signal["has_extracted_signal"]]
        .groupby("direction")
        .agg(
            districts=("leaid", "count"),
            total_topline=("topline_amount", "sum"),
            median_yoy_pct=("yoy_change_pct", "median"),
        )
        .reset_index()
    )

    notes = pd.DataFrame([
        {"topic": "Coverage scope",
         "note": f"Step-2 covered states: {', '.join(EXTRACTORS.keys())}. "
                 f"Other states report exp_total_fy23 only (F-33 baseline)."},
        {"topic": "Status meaning",
         "note": "All current extractors return status='actual' (audited or "
                 "unaudited actuals). FY27 budget adoption tracking will "
                 "populate 'proposed', 'tentative', 'adopted' statuses "
                 "starting summer 2026."},
        {"topic": "Topline definitions",
         "note": "TX: PEIMS All Funds Total Operating Expenditures. "
                 "CA: SACS Object 1000-7999 in Funds 01-29 (governmental "
                 "funds). FL: AFR General Fund Total Expenditures. These "
                 "are normalized as best as possible but each state's "
                 "chart of accounts differs slightly."},
        {"topic": "YoY computation",
         "note": "TX: FY24 vs FY25 PEIMS actuals. "
                 "CA: FY24 vs FY25 SACS unaudited actuals. "
                 "FL: FY24 vs FY25 AFR PDFs."},
    ])

    xlsx_path = PROCESSED / "spending_signal.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        signal_xlsx_cols = [
            "leaid", "lea_name", "state_postal",
            "enrollment_fy25", "exp_total_fy23",
            "fiscal_year", "status", "topline_amount",
            "yoy_change_pct", "yoy_change_dollars", "direction",
            "source_date", "notes",
        ]
        signal[signal_xlsx_cols].to_excel(
            writer, sheet_name="signal", index=False
        )
        by_state.to_excel(writer, sheet_name="by_state", index=False)
        by_direction.to_excel(writer, sheet_name="by_direction", index=False)
        notes.to_excel(writer, sheet_name="notes", index=False)
    print(f"[write] {xlsx_path.relative_to(ROOT)}")

    return signal, by_state, by_direction


def write_coverage_report(signal, by_state, by_direction):
    """Write a human-readable summary."""
    out_path = PROCESSED / "coverage_report.txt"
    with out_path.open("w") as f:
        op = signal[signal["has_extracted_signal"]]
        total_op = len(signal)
        f.write("=" * 60 + "\n")
        f.write("School District Spending Tracker — Coverage Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Operating districts in master:      {total_op:,}\n")
        f.write(f"Districts with extracted signal:    {len(op):,} "
                f"({len(op)/total_op*100:.1f}%)\n")
        f.write(f"States covered by extractors:       "
                f"{op['state_postal'].nunique()} of "
                f"{signal['state_postal'].nunique()}\n\n")
        f.write(f"Total FY25/latest topline tracked:  "
                f"${op['topline_amount'].sum() / 1e9:.1f}B\n")
        f.write(f"Median YoY change (where known):    "
                f"{op['yoy_change_pct'].median():.1f}%\n\n")

        f.write("Direction summary (extracted records):\n")
        for _, row in by_direction.iterrows():
            f.write(f"  {row['direction']:>10}: {row['districts']:>5,} "
                    f"districts | "
                    f"${row['total_topline']/1e9:>6.1f}B | "
                    f"median YoY {row['median_yoy_pct']:>+6.1f}%\n")
        f.write("\n")

        f.write("By state (top 20 by district count):\n")
        f.write(f"  {'state':<6} {'tier':<5} {'distr':>6} {'signal':>7} "
                f"{'cvg%':>6} {'incr':>5} {'decr':>5} "
                f"{'topln $B':>9}\n")
        for _, row in by_state.nlargest(20, "districts").iterrows():
            tot_b = (row['total_topline'] or 0) / 1e9
            f.write(f"  {row['state_postal']:<6} "
                    f"{int(row['data_tier']):<5} "
                    f"{row['districts']:>6,} "
                    f"{int(row['with_signal']):>7,} "
                    f"{row['coverage_pct']:>5.1f}% "
                    f"{int(row['increased']):>5,} "
                    f"{int(row['decreased']):>5,} "
                    f"{tot_b:>9.1f}\n")
    print(f"[write] {out_path.relative_to(ROOT)}")
    print()
    print(out_path.read_text())


def main():
    extractions = run_all()
    signal, by_state, by_direction = build_signal_table(extractions)
    write_coverage_report(signal, by_state, by_direction)


if __name__ == "__main__":
    main()
