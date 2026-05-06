"""Registry of which extractors handle which (state, kind).

Two `kind`s today:
  - "budget"  — pulls adopted/proposed/tentative budget submissions for the
                CURRENT calendar fiscal year. Gated by state_calendars in the
                daily runner: only runs while today is within the state's
                proposed_window_start … adoption_deadline + 30 days window.
  - "actuals" — pulls audited or unaudited actual expenditures for a PAST
                fiscal year. Not gated by state_calendars (publication cycles
                are independent of the budget-adoption cycle); runnable on a
                slower cadence or on demand.

Adding a new extractor: add a row here, point at its module path, and the
daily runner picks it up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractorSpec:
    state_postal: str
    kind: str  # "budget" | "actuals"
    module: str  # importable module name; module.extract(fiscal_year=, triggered_by=)
    # Offset relative to the calendar fiscal_year passed to the runner.
    # 0 = same FY as the runner argument; -2 = two years before.
    fy_offset: int = 0
    notes: str = ""


REGISTRY: list[ExtractorSpec] = [
    # FL
    ExtractorSpec(
        state_postal="FL",
        kind="budget",
        module="extractors.fl",
        fy_offset=0,
        notes="FLDOE Summary Budget portal — adopted budgets per county",
    ),
    ExtractorSpec(
        state_postal="FL",
        kind="actuals",
        module="extractors.fl_afr",
        fy_offset=-2,
        notes="FLDOE AFR PDFs — audited actuals; FY-2 from runner FY",
    ),
    # CA
    ExtractorSpec(
        state_postal="CA",
        kind="budget",
        module="extractors.ca_budget",
        fy_offset=0,
        notes="SACS Data Viewer BS1 — adopted budgets via JSON API",
    ),
    ExtractorSpec(
        state_postal="CA",
        kind="actuals",
        module="extractors.ca",
        fy_offset=-2,
        notes="SACS unaudited actuals .exe; FY-2 from runner FY",
    ),
    # TX
    ExtractorSpec(
        state_postal="TX",
        kind="actuals",
        module="extractors.tx",
        fy_offset=-2,
        notes="TEA PEIMS Summarized Financial Data; actuals only — TX has no bulk budget feed",
    ),
    # IL
    ExtractorSpec(
        state_postal="IL",
        kind="actuals",
        module="extractors.il",
        # IL audited actuals lag one more year than TX/CA/FL — latest published
        # in spring 2026 was FY24 (= our fiscal_year=2024), so offset is -3 from FY27.
        fy_offset=-3,
        notes="ISBE OEPP-PCTC bulk Excel; actuals only — adopted-budget Form 50-39 path TBD",
    ),
    # PA
    ExtractorSpec(
        state_postal="PA",
        kind="budget",
        module="extractors.pa",
        # PA GFB filenames use the school year (e.g. 2025-26gfbdata.xlsx for our
        # fiscal_year=2026). Latest available is the year-in-progress; FY27
        # GFB will publish around fall 2026 when districts file with PDE.
        fy_offset=0,
        notes="PDE General Fund Budget bulk Excel; AFR (actuals) extractor TBD",
    ),
    # GA
    ExtractorSpec(
        state_postal="GA",
        kind="actuals",
        module="extractors.ga",
        # GOSA Revenues_and_Expenditures CSV: latest published Feb 2026
        # was FY25 (= our fiscal_year=2025). Audited actuals lag two years
        # behind the FY27 calendar (publishes ~Feb of the year after).
        fy_offset=-2,
        notes="GOSA Revenues_and_Expenditures CSV; URL has timestamp suffix — KNOWN_FILE_URLS map per FY",
    ),
    # OH
    ExtractorSpec(
        state_postal="OH",
        kind="actuals",
        module="extractors.oh",
        # ODE Cupp Report: FY25 published March 2026 — same publication
        # cadence as the others; FY27 calendar maps to FY25 file in hand.
        fy_offset=-2,
        notes="ODE District Profile (Cupp) Excel; topline = ADM × OEPP",
    ),
    # NC
    ExtractorSpec(
        state_postal="NC",
        kind="actuals",
        module="extractors.nc",
        # NCDPI SPSF Excel publishes around fall after FY close. FY25
        # published in fall 2025; FY27 calendar maps to the FY25 file in hand.
        fy_offset=-2,
        notes="NCDPI SPSF Excel; STATE-FUNDED ONLY topline (~55-60% of total operating)",
    ),
    # MI
    ExtractorSpec(
        state_postal="MI",
        kind="actuals",
        module="extractors.mi",
        # MDE Bulletin 1011 published annually after AFR (Form SE-4096)
        # reconciliation. FY25 published 2026; FY27 calendar maps to FY25.
        fy_offset=-2,
        notes="MDE Bulletin 1011 Excel; topline = sum(TOTCUROPEX) across all funds",
    ),
    # VA
    ExtractorSpec(
        state_postal="VA",
        kind="actuals",
        module="extractors.va",
        # APA Comparative Report published annually for FY ending June 30.
        # FY25 published 2025; FY27 calendar maps to FY25 file in hand.
        fy_offset=-2,
        notes="APA Comparative Report Excel; per-locality Education total; opaque GUID URL per FY",
    ),
    # WA
    ExtractorSpec(
        state_postal="WA",
        kind="actuals",
        module="extractors.wa",
        # OSPI F-196 10-year file published Dec of FY-end year. WA fiscal
        # year is Sept-Aug, so FY25 ended Aug 31, 2025; F-196 published
        # Dec 2025. FY27 calendar maps to FY25 file in hand.
        fy_offset=-2,
        notes="OSPI F-196 10-year XLSX; topline = General Fund EXP by District last column",
    ),
    # NJ
    ExtractorSpec(
        state_postal="NJ",
        kind="actuals",
        module="extractors.nj",
        # NJ TGES Detail FY24 published in 2025 — NJDOE lags one year more
        # than the others. FY27 calendar maps to FY24 file in hand.
        fy_offset=-3,
        notes="NJDOE TGES Detail XLSX; topline = Total Spending; county+code crosswalk",
    ),
    # UT
    ExtractorSpec(
        state_postal="UT",
        kind="actuals",
        module="extractors.ut",
        # USBE AFR Summary Expenditure FY24 published in 2025 — same lag
        # pattern as NJ. FY27 calendar maps to FY24 file in hand.
        fy_offset=-3,
        notes="USBE AFR Summary Expenditure XLSX; topline = Gov Funds Total Grand Total; districts only (charters TBD)",
    ),
    # CT
    ExtractorSpec(
        state_postal="CT",
        kind="budget",
        module="extractors.ct",
        # CT OPM publishes adopted municipal budgets via Socrata SODA API
        # almost in real-time (Bridgeport adopted 2025-05-19 for FY26 and
        # was in the dataset). FY27 calendar maps to FY27 directly.
        fy_offset=0,
        notes="CT OPM Adopted Municipal Budget SoQL API; topline = education_expenditures; town districts only (regional districts TBD)",
    ),
    # TN
    ExtractorSpec(
        state_postal="TN",
        kind="actuals",
        module="extractors.tn",
        # TDOE ASR FY25 published Feb 2026; FY27 calendar maps to FY25 file.
        fy_offset=-2,
        notes="TDOE Annual Statistical Report ZIP; topline = Table 51 'TOTAL OPERATING EXPENDITURES'",
    ),
    # MA
    ExtractorSpec(
        state_postal="MA",
        kind="actuals",
        module="extractors.ma",
        # DESE Profiles PPX page only serves the latest balanced FY via
        # plain GET; FY24 is the latest as of 2026-05-05. FY25 publishes
        # after Dec 2025 EOYR audit cycle, then page will auto-flip.
        fy_offset=-3,
        notes="DESE Profiles statereport ppx.aspx HTML; topline = 'Total Expenditures' (all funds, EOYR-derived)",
    ),
    # IN
    ExtractorSpec(
        state_postal="IN",
        kind="actuals",
        module="extractors.in_",
        # IN school FY = calendar year (Jan-Dec) per IC 20-40-1.
        # SCFI 2025-release covers CY 2014-2024; FY27 calendar maps
        # to CY 2024 file in hand. URL pinned per FY in KNOWN_FILE_URLS.
        fy_offset=-3,
        notes="DUAB SCFI Annual Deficit Surplus XLSX; topline = sum Expenditure across operating fund classifications; charters TBD",
    ),
    # MD
    ExtractorSpec(
        state_postal="MD",
        kind="actuals",
        module="extractors.md",
        # MSDE SFD Part 2 PDF, latest is FY24 (SY 2023-24); URL pinned per FY.
        fy_offset=-3,
        notes="MSDE Selected Financial Data Part 2 PDF; topline = Table 1 'Total Current Expense Fund' per LEA",
    ),
    # SC
    ExtractorSpec(
        state_postal="SC",
        kind="actuals",
        module="extractors.sc",
        # SCDE In$ite per-district PDFs (2 alphabetical bundles); FY24 latest.
        fy_offset=-3,
        notes="SCDE In$ite per-district PDFs; topline = 'Function' total (Total Exp - Capital - Out-of-District)",
    ),
    # WI
    ExtractorSpec(
        state_postal="WI",
        kind="actuals",
        module="extractors.wi",
        # DPI Comparative Cost summary; FY24 latest. URL date suffix
        # changes when DPI republishes; pin per FY in KNOWN_FILE_URLS.
        fy_offset=-3,
        notes="DPI Comparative Cost Per Member XLSX; topline = sum 7 cost cols (instruct + support + admin + ops + trans + facility + food)",
    ),
    # AL
    ExtractorSpec(
        state_postal="AL",
        kind="actuals",
        module="extractors.al",
        # ALSDE FY = Oct-Sept (state FY). FY2023 latest; FY24 expected ~mid-2026.
        fy_offset=-4,
        notes="ALSDE System Level Per-Pupil Expenditures PDF; topline = 'Total' row grand total",
    ),
    # OK
    ExtractorSpec(
        state_postal="OK",
        kind="actuals",
        module="extractors.ok",
        # OSDE OCAS publishes XLSX through SY end year 2025 (= FY25); URL
        # is fully predictable from fiscal_year (no KNOWN_FILE_URLS map).
        fy_offset=-2,
        notes="OSDE OCAS Expenditure Summary (With Exclusions) XLSX; topline = sum Expended per County+District",
    ),
    # KY
    ExtractorSpec(
        state_postal="KY",
        kind="actuals",
        module="extractors.ky",
        # KDE AFR R&E XLSX; URL fully predictable from fiscal_year.
        fy_offset=-3,
        notes="KDE AFR Revenues and Expenditures XLSX; topline = sum Function 1000-3900 per district",
    ),
    # LA
    ExtractorSpec(
        state_postal="LA",
        kind="actuals",
        module="extractors.la",
        # LDOE AFSR ZIP (Item 9 EXP); URL pinned per FY due to versioning suffix.
        fy_offset=-3,
        notes="LDOE AFSR Item 9 Expenditures ZIP; topline = E52 'TOTAL EXPENDITURES' Current_Expenditure column",
    ),
    # OR
    ExtractorSpec(
        state_postal="OR",
        kind="actuals",
        module="extractors.or_",
        # ODE Fiscal Transparency Detailed District Expenditure XLSX; URL is
        # predictable from fiscal_year (no KNOWN_FILE_URLS map needed).
        fy_offset=-3,
        notes="ODE Detailed District Expenditure XLSX; topline = sum ActualExpAmt where FunctionCd[0] in (1,2,3)",
    ),
    # IA
    ExtractorSpec(
        state_postal="IA",
        kind="actuals",
        module="extractors.ia",
        # Iowa DE CAR multi-sheet XLSX; URL pinned per FY due to media-id suffix.
        fy_offset=-3,
        notes="Iowa DE CAR XLSX; topline = sum across {General, Activity, Management, Nutrition} fund Exp data sheets",
    ),
    # AR
    ExtractorSpec(
        state_postal="AR",
        kind="actuals",
        module="extractors.ar",
        # ADE/DESE Annual Statistical Report PDF; one page per district.
        fy_offset=-3,
        notes="ADE/DESE Annual Statistical Report PDF; topline = line 79 'Total Current Expenditures' Actual column",
    ),
    # KS
    ExtractorSpec(
        state_postal="KS",
        kind="actuals",
        module="extractors.ks",
        # Kansas Open Gov per-pupil CSV (KSDE CPFS source); FY25 latest.
        # Reconstructs total = per-pupil × master enrollment_fy25.
        fy_offset=-2,
        notes="KS Open Gov per-pupil CSV; topline = (Total - Capital - DebtService) per pupil × enrollment_fy25",
    ),
    # MS
    ExtractorSpec(
        state_postal="MS",
        kind="actuals",
        module="extractors.ms",
        # MDE Sup Annual Report Functional Area XLSX; needs Referer header
        # to bypass Azure Application Gateway 403.
        fy_offset=-3,
        notes="MDE Sup Annual Report Functional Area XLSX; topline = 'Total Current Operational Expenses' col 19",
    ),
    # ID
    ExtractorSpec(
        state_postal="ID",
        kind="actuals",
        module="extractors.id_",
        # ISDE 20-Year R&E XLSX; URL pinned per FY since file name reflects
        # multi-FY span and is republished annually.
        fy_offset=-3,
        notes="ISDE 20-Year R&E XLSX; topline = sum Instruction + Support Services + Non-Instructional from 'FY{N} All Funds Expd' sheet",
    ),
    # HI
    ExtractorSpec(
        state_postal="HI",
        kind="actuals",
        module="extractors.hi",
        # HI is a single statewide district; AFSA{YYYY}.pdf published fall
        # of FY-end year. FY27 calendar maps to FY25 (= AFSA2025.pdf).
        fy_offset=-2,
        notes="HIDOE AFSA PDF; topline = School-related + State/complex area admin from Statement of Revenues, Expenditures, and Changes in Fund Balances",
    ),
    # ME
    ExtractorSpec(
        state_postal="ME",
        kind="actuals",
        module="extractors.me",
        # ME DOE Resident Expenditure Totals PDF; FY25 latest published.
        # Coverage is partial (~55%) because PDF reports per-municipality
        # (small SAUs) while master uses RSU/MSAD groupings.
        fy_offset=-2,
        notes="ME DOE Resident Expenditure Totals PDF; topline = Total - Debt Service per row; partial coverage due to RSU/MSAD granularity mismatch",
    ),
    # SD
    ExtractorSpec(
        state_postal="SD",
        kind="actuals",
        module="extractors.sd",
        # SD DOE All Expenditures workbook; URL pinned per FY (file name
        # has FY suffix). FY25 latest published Jan 2026.
        fy_offset=-2,
        notes="SD DOE All Expenditures XLSX; topline = General Fund + Special Education Expenditures",
    ),
]


def by_state(state_postal: str) -> list[ExtractorSpec]:
    return [s for s in REGISTRY if s.state_postal == state_postal]


def by_kind(kind: str) -> list[ExtractorSpec]:
    return [s for s in REGISTRY if s.kind == kind]
