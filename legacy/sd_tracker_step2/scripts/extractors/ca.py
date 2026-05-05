"""
California extractor — CDE SACS Unaudited Actual Financial Data.

Source: cde.ca.gov SACS Web System, Annual Financial Data
        Self-extracting EXE files containing Microsoft Access (.mdb)
        databases. We extract with `unzip` and read with mdbtools.

What this gives us:
  - FY24-25 (released Feb 4, 2026) and FY23-24 unaudited actual expenditures
    for ALL CA LEAs that file in SACS (~1,045 districts + COEs + JPAs +
    SACS-filing charters)
  - YoY change FY24 -> FY25 per LEA
  - General Fund and All Governmental Funds totals separately

What this does NOT give us:
  - FY26 in-flight or FY27 proposed budgets. SACS reports unaudited actuals
    for completed years. CA's adopted-budget data flows through the SACS
    Budget reporting period and county superintendent review process. Could
    be added as a Tier-1.5 extractor pulling SACS Web's budget submissions.
  - Charter schools that file via Alternative Form (~700 charters). They
    submit alt2425data.exe which is a separate, smaller dataset.

Topline definition (matches F-33 'current expenditures' as closely as
possible while staying inside SACS's chart of accounts):
  - Sum of Object codes 1000-7999 in Funds 01-29 (governmental funds)
  - 1xxx Certificated Salaries
  - 2xxx Classified Salaries
  - 3xxx Employee Benefits
  - 4xxx Books, Supplies
  - 5xxx Services and Other Operating
  - 6xxx Capital Outlay
  - 7xxx Other Outgo
  This is broader than F-33's 'current expenditures' (which excludes 6xxx
  capital outlay), but gives a true total. We also compute General Fund only
  (Fund 01) which is closer to the LCFF operating perspective.

LEAID mapping:
  CA SACS uses a 14-digit County-District-School (CDS) code. The county+
  district portion is the 7-digit "CDS district code". Master_districts'
  state_leaid for CA is in format like 'CA-1975309' where 1975309 is the
  7-digit CDS code (concatenation of Ccode + Dcode).
"""

import subprocess
from pathlib import Path
import pandas as pd

from ._base import ExtractorRecord, to_dataframe

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "raw"
SOURCE_URL = "https://www.cde.ca.gov/ds/fd/fd/"

# Year-keyed file metadata
YEAR_FILES = {
    2024: {  # CA fiscal year 2024 = SY 2023-24
        "exe_url": "https://www3.cde.ca.gov/fiscal-downloads/sacs_data/2023-24/sacs2324.exe",
        "exe_name": "sacs2324.exe",
        "mdb_name": "sacs2324.mdb",
        "ugl_csv": "sacs2324_UserGL.csv",
        "leas_csv": "sacs2324_LEAs.csv",
    },
    2025: {  # CA fiscal year 2025 = SY 2024-25
        "exe_url": "https://www3.cde.ca.gov/fiscal-downloads/sacs_data/2024-25/sacs2425.exe",
        "exe_name": "sacs2425.exe",
        "mdb_name": "sacs2425.mdb",
        "ugl_csv": "sacs2425_UserGL.csv",
        "leas_csv": "sacs2425_LEAs.csv",
    },
}


def ensure_extracted(year):
    """Make sure CSVs for this fiscal year exist; download/extract if not."""
    meta = YEAR_FILES[year]
    ugl_path = RAW_DIR / meta["ugl_csv"]
    leas_path = RAW_DIR / meta["leas_csv"]
    if ugl_path.exists() and leas_path.exists():
        return ugl_path, leas_path

    exe_path = RAW_DIR / meta["exe_name"]
    mdb_path = RAW_DIR / meta["mdb_name"]
    if not exe_path.exists():
        print(f"  downloading {meta['exe_name']} from CDE...")
        subprocess.run(["curl", "-s", "-o", str(exe_path), meta["exe_url"]],
                       check=True)
    if not mdb_path.exists():
        subprocess.run(["unzip", "-o", str(exe_path), meta["mdb_name"],
                        "-d", str(RAW_DIR)], check=True, capture_output=True)
    if not ugl_path.exists():
        with ugl_path.open("w") as f:
            subprocess.run(["mdb-export", str(mdb_path), "UserGL"],
                           stdout=f, check=True)
    if not leas_path.exists():
        with leas_path.open("w") as f:
            subprocess.run(["mdb-export", str(mdb_path), "LEAs"],
                           stdout=f, check=True)
    return ugl_path, leas_path


def _compute_topline(ugl_path):
    """Aggregate UserGL to Ccode+Dcode level: total exp + General Fund exp."""
    gl = pd.read_csv(
        ugl_path, dtype=str, low_memory=False,
        usecols=["Ccode", "Dcode", "Fund", "Object", "Value"],
    )
    gl["Value"] = pd.to_numeric(gl["Value"], errors="coerce")
    gl["Object_int"] = pd.to_numeric(gl["Object"], errors="coerce")
    gl["Fund_int"] = pd.to_numeric(gl["Fund"], errors="coerce")

    expense_mask = gl["Object_int"].between(1000, 7999, inclusive="both")
    exp = gl[expense_mask]

    all_gov = exp[exp["Fund_int"].between(1, 29, inclusive="both")]
    total = (all_gov.groupby(["Ccode", "Dcode"])["Value"].sum()
             .reset_index().rename(columns={"Value": "exp_total"}))

    gf_only = exp[exp["Fund_int"] == 1]
    genfund = (gf_only.groupby(["Ccode", "Dcode"])["Value"].sum()
               .reset_index().rename(columns={"Value": "exp_genfund"}))

    return total.merge(genfund, on=["Ccode", "Dcode"], how="outer")


def _load_master_crosswalk():
    """Build CA CDS code (Ccode+Dcode = 7 digit) -> NCES leaid map."""
    master_path = ROOT / "processed" / "master_districts.csv"
    m = pd.read_csv(master_path, dtype={"leaid": str, "state_leaid": str})
    m = m[(m["state_postal"] == "CA") & (m["is_operating_district"])]
    # state_leaid format: 'CA-1975309'. Strip prefix to get CDS district code.
    m["cds_district"] = m["state_leaid"].str.replace("CA-", "", regex=False)
    return dict(zip(m["cds_district"], m["leaid"]))


def extract(source_date=None):
    """Return ExtractorRecord rows for CA districts with FY25 actuals + YoY."""
    print("  ensuring SACS data extracted...")
    ugl_25, leas_25 = ensure_extracted(2025)
    ugl_24, _      = ensure_extracted(2024)

    print("  computing FY25 toplines...")
    fy25 = _compute_topline(ugl_25).rename(columns={
        "exp_total": "exp_total_fy25",
        "exp_genfund": "exp_genfund_fy25",
    })
    print("  computing FY24 toplines (for YoY)...")
    fy24 = _compute_topline(ugl_24).rename(columns={
        "exp_total": "exp_total_fy24",
        "exp_genfund": "exp_genfund_fy24",
    })

    leas = pd.read_csv(leas_25, dtype=str)
    leas["Dname"] = leas["Dname"].str.strip()
    leas["Dtype"] = leas["Dtype"].str.strip()

    df = leas.merge(fy25, on=["Ccode", "Dcode"], how="left")
    df = df.merge(fy24, on=["Ccode", "Dcode"], how="left")
    df["cds_district"] = df["Ccode"] + df["Dcode"]

    crosswalk = _load_master_crosswalk()
    df["leaid"] = df["cds_district"].map(crosswalk)
    matched = df["leaid"].notna().sum()
    print(f"  CA LEAs in SACS: {len(df):,}; matched to NCES: {matched:,}")

    df["yoy_pct"] = (
        (df["exp_total_fy25"] - df["exp_total_fy24"])
        / df["exp_total_fy24"] * 100
    )
    df["yoy_dollars"] = df["exp_total_fy25"] - df["exp_total_fy24"]

    if source_date is None:
        source_date = "2026-02-04"  # CDE publication date for FY25 SACS

    df_matched = df.dropna(subset=["leaid"])
    records = []
    for _, row in df_matched.iterrows():
        records.append(ExtractorRecord(
            leaid=row["leaid"],
            state_postal="CA",
            state_leaid=f"CA-{row['cds_district']}",
            fiscal_year=2025,
            status="actual",
            topline_amount=(
                None if pd.isna(row["exp_total_fy25"])
                else float(row["exp_total_fy25"])
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
                f"SACS unaudited actual; "
                f"obj 1000-7999 funds 01-29; "
                f"dtype='{row['Dtype'].lower()}'"
            ),
        ))
    return to_dataframe(records)


if __name__ == "__main__":
    out = extract()
    print(f"\nExtracted {len(out):,} CA records.")
    print(f"Total FY25 topline: ${out['topline_amount'].sum() / 1e9:,.1f}B")
    increased = (out["yoy_change_dollars"] > 0).sum()
    decreased = (out["yoy_change_dollars"] < 0).sum()
    flat_or_unknown = len(out) - increased - decreased
    print(f"  Increased YoY: {increased:,}")
    print(f"  Decreased YoY: {decreased:,}")
    print(f"  Flat/unknown:  {flat_or_unknown:,}")
    print(f"  Median YoY %:  {out['yoy_change_pct'].median():.1f}%")
    print(f"\nLargest CA districts (by FY25 spend):")
    print(out.nlargest(5, "topline_amount")[
        ["leaid", "state_leaid", "topline_amount", "yoy_change_pct"]
    ].to_string(index=False))
