"""
Texas extractor — TEA PEIMS Summarized Financial Data.

Source: tea.texas.gov 2009-2025 summarized PEIMS actual financial data
        (Excel, ~19 MB, refreshed annually each spring after audit close)

What this gives us:
  - FY09 through FY25 audited ACTUAL expenditures for every TX LEA
  - YoY change FY24 -> FY25 is the most recent available signal

What this does NOT give us:
  - FY26 in-flight or FY27 proposed/adopted budgets. Those don't appear in
    PEIMS until fall after district fiscal-year start (Sept 1). For real-time
    budget tracking we'd need to scrape board-meeting platforms; for now
    this gets us the most-recent-completed-year increase/decrease per district.

Topline definition:
  ALL FUNDS-TOTAL OPERATING EXPENDITURES BY OBJ
  (combines instruction, support services, admin, plant, transportation, etc.
   across all funds — most comparable to F-33 'current expenditures total')

Note: Fiscal year in PEIMS is the SCHOOL year ending (e.g. YEAR=2025 means
SY2024-25, fiscal year ending Aug 31 2025).
"""

from pathlib import Path
import pandas as pd

from ._base import ExtractorRecord, to_dataframe

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_FILE = ROOT / "raw" / "tx_peims_2009_2025.xlsx"
SOURCE_URL = (
    "https://tea.texas.gov/finance-and-grants/state-funding/"
    "state-funding-reports-and-data/peims-financial-data-downloads"
)

TOPLINE_COL = "ALL FUNDS-TOTAL OPERATING EXPENDITURES BY OBJ"


def _load_master_crosswalk():
    """Build state_leaid (e.g. 'TX-054901') -> NCES leaid map from master."""
    master_path = ROOT / "processed" / "master_districts.csv"
    m = pd.read_csv(master_path, dtype={"leaid": str, "state_leaid": str})
    m = m[(m["state_postal"] == "TX") & (m["is_operating_district"])]
    # state_leaid format from CCD: 'TX-054901'. PEIMS gives '054901'.
    m["tx_dist_num"] = m["state_leaid"].str.replace("TX-", "", regex=False)
    return dict(zip(m["tx_dist_num"], m["leaid"]))


def extract(latest_only=True, source_date=None):
    """Return ExtractorRecord rows for TX districts.

    latest_only=True returns only the most recent (FY25) actual + YoY,
    which is the typical 'current state' snapshot. Set False to get the
    full history (one row per district per year), useful for backfill.
    """
    if not RAW_FILE.exists():
        raise FileNotFoundError(
            f"Missing {RAW_FILE.name}. Run: download_tx.sh or fetch from {SOURCE_URL}"
        )

    crosswalk = _load_master_crosswalk()
    print(f"  TX crosswalk: {len(crosswalk):,} state→NCES mappings")

    df = pd.read_excel(
        RAW_FILE, sheet_name="DATAMART",
        usecols=["DISTRICT NUMBER", "DISTRICT NAME", "YEAR", TOPLINE_COL],
    )
    df["DISTRICT NUMBER"] = (
        df["DISTRICT NUMBER"].astype(str).str.lstrip("'").str.strip()
    )
    df = df.rename(columns={
        "DISTRICT NUMBER": "tx_dist_num",
        "DISTRICT NAME": "district_name",
        "YEAR": "fiscal_year",
        TOPLINE_COL: "topline",
    })
    df["topline"] = pd.to_numeric(df["topline"], errors="coerce")
    df["leaid"] = df["tx_dist_num"].map(crosswalk)
    matched = df["leaid"].notna().sum()
    print(f"  PEIMS rows: {len(df):,}; matched to NCES: {matched:,}")

    df = df.dropna(subset=["leaid"]).sort_values(["leaid", "fiscal_year"])
    df["prior_topline"] = df.groupby("leaid")["topline"].shift(1)
    df["yoy_dollars"] = df["topline"] - df["prior_topline"]
    df["yoy_pct"] = (df["yoy_dollars"] / df["prior_topline"]) * 100

    if latest_only:
        latest_year = int(df["fiscal_year"].max())
        df = df[df["fiscal_year"] == latest_year]
        print(f"  Filtering to FY{latest_year} (latest); "
              f"{len(df):,} districts")

    if source_date is None:
        source_date = "2026-04-08"  # publication date on the TEA file

    records = []
    for _, row in df.iterrows():
        records.append(ExtractorRecord(
            leaid=row["leaid"],
            state_postal="TX",
            state_leaid=f"TX-{row['tx_dist_num']}",
            fiscal_year=int(row["fiscal_year"]),
            status="actual",
            topline_amount=(
                None if pd.isna(row["topline"]) else float(row["topline"])
            ),
            yoy_change_pct=(
                None if pd.isna(row["yoy_pct"]) else float(row["yoy_pct"])
            ),
            yoy_change_dollars=(
                None if pd.isna(row["yoy_dollars"])
                else float(row["yoy_dollars"])
            ),
            source=SOURCE_URL,
            source_date=source_date,
            notes=(
                f"PEIMS audited actual; "
                f"definition='{TOPLINE_COL.lower()}'"
            ),
        ))
    return to_dataframe(records)


if __name__ == "__main__":
    out = extract(latest_only=True)
    print(f"\nExtracted {len(out):,} TX records.")
    print(f"Total FY25 topline: ${out['topline_amount'].sum() / 1e9:,.1f}B")
    increased = (out["yoy_change_dollars"] > 0).sum()
    decreased = (out["yoy_change_dollars"] < 0).sum()
    flat_or_unknown = len(out) - increased - decreased
    print(f"  Increased YoY: {increased:,}")
    print(f"  Decreased YoY: {decreased:,}")
    print(f"  Flat/unknown:  {flat_or_unknown:,}")
    print(f"\nMedian YoY change: "
          f"{out['yoy_change_pct'].median():.1f}%")
    print(f"\nSample:")
    print(out.head(5).to_string(index=False))
