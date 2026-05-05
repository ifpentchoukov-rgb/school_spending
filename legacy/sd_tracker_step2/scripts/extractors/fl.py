"""
Florida extractor — FLDOE Annual Financial Reports (AFR).

Source: fldoe.org Annual Financial Reports. The state publishes one PDF per
        county district per year, plus a "State Cumulative Totals" PDF.
        URL pattern: /file/7507/{YY}{YY+1}afr{County}.pdf
        Examples:   2425afrDade.pdf, 2425afrPalmBeach.pdf

What this gives us:
  - FY24-25 General Fund total expenditures per FL district, from the AFR PDF
    (released January 2026)
  - FY23-24 same for YoY comparison

What this does NOT give us:
  - FY26 in-flight or FY27 proposed budgets. FL districts publish "Summary
    Budget" PDFs separately (see school-dis-summary-budget.stml) — also PDFs.
    Same parsing approach would extend to those.
  - Charter schools that file under their authorizing district roll up
    automatically. Independent charter LEAs that file separately need a
    different path (FL Office of Independent Education).

Topline definition:
  TOTAL EXPENDITURES line in the General Fund (Fund 100) statement.
  This is comparable to F-33 'current expenditures' and to CA SACS General
  Fund. Excludes capital projects (Funds 300s) and debt service (Funds 200s).

Note on coverage:
  FL has 67 county districts plus University Lab Schools, Florida Virtual
  School, and the FAU/FSU Lab Schools. The AFR PDFs cover the 67 county
  districts; the lab schools file separately and are not yet handled here.
"""

import re
import subprocess
from pathlib import Path

import pandas as pd
import pdfplumber

from ._base import ExtractorRecord, to_dataframe

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "raw" / "fl_afr"
RAW_DIR.mkdir(parents=True, exist_ok=True)
SOURCE_URL = (
    "https://www.fldoe.org/finance/fl-edu-finance-program-fefp/"
    "school-dis-annual-financial-reports-af.stml"
)
URL_BASE = "https://www.fldoe.org/file/7507"

# Maps county name (as used in FLDOE filename) to canonical title-case spelling
# we'll use for matching against CCD lea_name. FLDOE filenames are
# inconsistent in casing — we generate both upper and title forms.
FL_COUNTIES = [
    "Alachua", "Baker", "Bay", "Bradford", "Brevard", "Broward",
    "Calhoun", "Charlotte", "Citrus", "Clay", "Collier", "Columbia",
    "Dade", "DeSoto", "Dixie", "Duval", "Escambia", "Flagler",
    "Franklin", "Gadsden", "Gilchrist", "Glades", "Gulf", "Hamilton",
    "Hardee", "Hendry", "Hernando", "Highlands", "Hillsborough",
    "Holmes", "IndianRiver", "Jackson", "Jefferson", "Lafayette",
    "Lake", "Lee", "Leon", "Levy", "Liberty", "Madison", "Manatee",
    "Marion", "Martin", "Monroe", "Nassau", "Okaloosa", "Okeechobee",
    "Orange", "Osceola", "PalmBeach", "Pasco", "Pinellas", "Polk",
    "Putnam", "StJohns", "StLucie", "SantaRosa", "Sarasota", "Seminole",
    "Sumter", "Suwannee", "Taylor", "Union", "Volusia", "Wakulla",
    "Walton", "Washington",
]

# County name as it appears in CCD lea_name (varies; usually
# 'XXX COUNTY SCHOOL DISTRICT'). The transformation rule:
# 'Dade' -> 'MIAMI-DADE' (special case)
# 'PalmBeach' -> 'PALM BEACH'
# Most others: just uppercase the county name and look for it.
COUNTY_NAME_OVERRIDES = {
    "Dade": "MIAMI-DADE",
    "PalmBeach": "PALM BEACH",
    "IndianRiver": "INDIAN RIVER",
    "StJohns": "ST. JOHNS",
    "StLucie": "ST. LUCIE",
    "SantaRosa": "SANTA ROSA",
}


def _county_to_lea_match_key(county):
    return COUNTY_NAME_OVERRIDES.get(county, county.upper())


def _afr_filename(county, fy_short):
    """fy_short e.g. '2425' for FY 2024-25. Some counties use lowercase
    'brevard'; we'll just try both casings."""
    return f"{fy_short}afr{county}.pdf"


def ensure_district_pdf(county, fy_short):
    """Download a single county's AFR PDF if missing. Returns local path or None."""
    target = RAW_DIR / _afr_filename(county, fy_short)
    if target.exists() and target.stat().st_size > 1000:
        return target

    # Try as-is, then lowercase county portion
    for variant in [county, county.lower()]:
        url = f"{URL_BASE}/{fy_short}afr{variant}.pdf"
        result = subprocess.run(
            ["curl", "-s", "-f", "-o", str(target), url],
            capture_output=True,
        )
        if result.returncode == 0 and target.stat().st_size > 1000:
            return target

    if target.exists() and target.stat().st_size <= 1000:
        target.unlink()
    return None


# Match a TOTAL EXPENDITURES line under the General Fund statement.
# The first column in the General Fund statement tends to be
# "Current" or summed total. The line looks like:
#   TOTAL EXPENDITURES 0000 4,225,068,746.60 1,887,522,029.02 ...
TOTAL_EXP_RE = re.compile(
    r"TOTAL\s+EXPENDITURES\s+0000\s+([\d,]+\.\d{2})", re.IGNORECASE
)


def parse_general_fund_total(pdf_path):
    """Extract the General Fund TOTAL EXPENDITURES from a district AFR PDF.

    Strategy: scan the first ~10 pages, looking for a page that mentions
    'GENERAL FUND' and contains a 'TOTAL EXPENDITURES 0000 ...' line. Return
    the first dollar amount on that line (the 'current' or first column,
    which is the operating expenditures total)."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:12]:
                text = page.extract_text() or ""
                if "GENERAL FUND" not in text.upper():
                    continue
                m = TOTAL_EXP_RE.search(text)
                if m:
                    return float(m.group(1).replace(",", ""))
    except Exception as e:
        print(f"    parse error on {pdf_path.name}: {e}")
    return None


def _load_master_crosswalk():
    """Build (uppercase-county-keyword) -> NCES leaid map for FL."""
    master_path = ROOT / "processed" / "master_districts.csv"
    m = pd.read_csv(master_path, dtype={"leaid": str, "state_leaid": str})
    m = m[(m["state_postal"] == "FL") & (m["is_operating_district"])].copy()
    m["lea_name_upper"] = m["lea_name"].str.upper()

    out = {}
    for county in FL_COUNTIES:
        key = _county_to_lea_match_key(county)
        # The CCD name may include 'COUNTY' or 'SCHOOL DISTRICT' suffix.
        # Pick the row whose lea_name CONTAINS our county keyword and
        # is the largest (in case of multiple matches).
        candidates = m[m["lea_name_upper"].str.contains(key, regex=False)]
        if not candidates.empty:
            top = candidates.iloc[0]
            out[county] = (top["leaid"], top["state_leaid"])
    return out


def extract(years=("2425", "2324"), source_date=None):
    """Pull FL district AFRs for the given fiscal-year shortcodes.
    Default = FY24-25 ('2425') and FY23-24 ('2324') for YoY comparison."""
    print("  building county→leaid crosswalk...")
    crosswalk = _load_master_crosswalk()
    print(f"  matched {len(crosswalk)} of {len(FL_COUNTIES)} counties")

    per_county = {}  # county -> {'2425': total, '2324': total}
    for fy_short in years:
        print(f"  fetching FY{fy_short[:2]}-{fy_short[2:]} PDFs...")
        for county in FL_COUNTIES:
            path = ensure_district_pdf(county, fy_short)
            if path is None:
                continue
            total = parse_general_fund_total(path)
            if total is None:
                continue
            per_county.setdefault(county, {})[fy_short] = total
        ok = sum(1 for c in per_county.values() if fy_short in c)
        print(f"    parsed {ok} county AFR PDFs for FY{fy_short}")

    if source_date is None:
        source_date = "2026-01-05"  # PDF run date observed on FY25 PDFs

    records = []
    target_fy = "2425"
    prior_fy = "2324"
    target_fy_int = 2025
    for county, totals in per_county.items():
        if county not in crosswalk:
            continue
        leaid, state_leaid = crosswalk[county]
        amount = totals.get(target_fy)
        prior = totals.get(prior_fy)
        yoy_pct = ((amount - prior) / prior * 100) if amount and prior else None
        yoy_dollars = (amount - prior) if amount and prior else None

        records.append(ExtractorRecord(
            leaid=leaid,
            state_postal="FL",
            state_leaid=state_leaid,
            fiscal_year=target_fy_int,
            status="actual",
            topline_amount=amount,
            yoy_change_pct=yoy_pct,
            yoy_change_dollars=yoy_dollars,
            source=SOURCE_URL,
            source_date=source_date,
            notes="FLDOE AFR; General Fund TOTAL EXPENDITURES (Fund 100)",
        ))
    return to_dataframe(records)


if __name__ == "__main__":
    out = extract()
    print(f"\nExtracted {len(out):,} FL records.")
    if len(out) > 0:
        print(f"Total FY25 topline: "
              f"${out['topline_amount'].sum() / 1e9:,.1f}B")
        increased = (out["yoy_change_dollars"] > 0).sum()
        decreased = (out["yoy_change_dollars"] < 0).sum()
        print(f"  Increased YoY: {increased:,}")
        print(f"  Decreased YoY: {decreased:,}")
        print(f"  Median YoY %:  {out['yoy_change_pct'].median():.1f}%")
        print(f"\nLargest:")
        print(out.nlargest(5, "topline_amount")[
            ["leaid", "state_leaid", "topline_amount", "yoy_change_pct"]
        ].to_string(index=False))
