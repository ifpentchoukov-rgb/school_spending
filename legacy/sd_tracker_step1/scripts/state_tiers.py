"""
State data-source tier classification for budget approval / topline tracking.

TIER 1 — State Education Agency (or comparable) publishes adopted district budget
         data in a centralized, machine-readable form. Automation feasible via
         scrape or download.

TIER 2 — State requires district publication (transparency mandate or general
         open-records norms) but aggregation is decentralized. Practical path:
         scrape board-meeting platforms (BoardDocs / Simbli / Diligent
         Community) + district websites.

TIER 3 — Limited central publication and weak/no transparency mandate.
         Practical path: news-monitoring + manual review.

Notes per state are deliberately brief; full source URLs and scrape selectors
go into per-state extractor modules in step 2.
"""

STATE_TIERS = {
    # FIPS : (postal, tier, primary_source_note)
    "01": ("AL", 2, "ALSDE Annual Financial Reports — PDFs per district"),
    "02": ("AK", 2, "DEED audited financial reports — PDFs per district"),
    "04": ("AZ", 1, "AZ Auditor General district financial transparency portal"),
    "05": ("AR", 1, "ADE Statewide Information System (SIS) financial reports"),
    "06": ("CA", 1, "CDE Fiscal Status / SACS — adoption + interim reporting"),
    "08": ("CO", 1, "CDE Public School Finance Unit — adopted budget files"),
    "09": ("CT", 2, "CSDE ED001 reports; budget vote calendars decentralized"),
    "10": ("DE", 2, "DDOE district budget summaries; small N"),
    "11": ("DC", 2, "DC has one LEA cluster; budget tracked via OCFO"),
    "12": ("FL", 1, "FLDOE financial reports + truth-in-millage TRIM"),
    "13": ("GA", 1, "GADOE Financial Reports + DOAA school audit reports"),
    "15": ("HI", 1, "Hawaii is a single statewide district — direct"),
    "16": ("ID", 2, "SDE district financial summaries; decentralized adoption"),
    "17": ("IL", 1, "ISBE Annual Financial Report (AFR) + budget Form 50-39"),
    "18": ("IN", 1, "IDOE + DLGF Gateway public budget portal"),
    "19": ("IA", 1, "Iowa DOE Certified Annual Report + budget filings"),
    "20": ("KS", 1, "KSDE budget summary documents per district"),
    "21": ("KY", 1, "KDE Annual Financial Report; uniform timeline"),
    "22": ("LA", 1, "LDOE Financial Reports / MFP allocations"),
    "23": ("ME", 2, "Maine DOE; town-meeting adoption is fragmented"),
    "24": ("MD", 1, "MSDE Selected Financial Data + county council adoption"),
    "25": ("MA", 1, "DESE district profiles + DOR municipal data"),
    "26": ("MI", 1, "CEPI Bulletin 1014 + Treasury Form B"),
    "27": ("MN", 1, "MDE finance data + TruthInTaxation filings"),
    "28": ("MS", 2, "MDE district financial reports — PDF-heavy"),
    "29": ("MO", 1, "DESE Annual Secretary of the Board Report (ASBR)"),
    "30": ("MT", 2, "OPI district financial reports; small districts dominate"),
    "31": ("NE", 2, "NDE Annual Financial Report; adoption decentralized"),
    "32": ("NV", 1, "NDE district budget submissions (small N — 17 districts)"),
    "33": ("NH", 3, "Town-meeting adoption — extremely fragmented"),
    "34": ("NJ", 1, "NJDOE Taxpayers Guide to Education Spending + UEZ"),
    "35": ("NM", 1, "NMPED Operational Budget Management System (OBMS)"),
    "36": ("NY", 1, "NYSED ST-3 + Comptroller financial data; school-budget vote"),
    "37": ("NC", 1, "NCDPI Statistical Profile + LGC budget data"),
    "38": ("ND", 2, "NDDPI district profiles; small N"),
    "39": ("OH", 1, "ODE District Profile Report + Auditor of State"),
    "40": ("OK", 1, "OSDE State Aid + OCAS district reports"),
    "41": ("OR", 1, "ODE district expenditure reports + LGOC"),
    "42": ("PA", 1, "PDE Finances reports + AFR Annual Financial Report"),
    "44": ("RI", 1, "RIDE Uniform Chart of Accounts UCOA — small N"),
    "45": ("SC", 1, "SCDE InSite financial data per district"),
    "46": ("SD", 2, "SD-DOE district financial reports — PDF-heavy"),
    "47": ("TN", 1, "TDOE Annual Statistical Report + budget submissions"),
    "48": ("TX", 1, "TEA PEIMS Summary of Finances + adopted budget data"),
    "49": ("UT", 1, "USBE Transparent Utah district financial portal"),
    "50": ("VT", 3, "Town-meeting adoption + supervisory unions — fragmented"),
    "51": ("VA", 1, "VDOE Superintendent's Annual Report + APA local audits"),
    "53": ("WA", 1, "OSPI F-196 Annual Financial Statements + apportionment"),
    "54": ("WV", 1, "WVDE Office of School Finance budget reports"),
    "55": ("WI", 1, "DPI Comparative Cost Per Member + budget data"),
    "56": ("WY", 1, "WDE district financial reports — small N (48 districts)"),
}


def get_tier(fips_code):
    """Return (postal, tier, source_note) for an integer or string FIPS code."""
    key = str(fips_code).zfill(2)
    return STATE_TIERS.get(key, ("??", 3, "Unknown / territory"))


if __name__ == "__main__":
    # Quick summary
    from collections import Counter
    tiers = Counter(t[1] for t in STATE_TIERS.values())
    print(f"Tier 1 (centralized):   {tiers[1]} states")
    print(f"Tier 2 (decentralized): {tiers[2]} states")
    print(f"Tier 3 (limited):       {tiers[3]} states")
    print(f"Total:                  {sum(tiers.values())} jurisdictions")
