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
]


def by_state(state_postal: str) -> list[ExtractorSpec]:
    return [s for s in REGISTRY if s.state_postal == state_postal]


def by_kind(kind: str) -> list[ExtractorSpec]:
    return [s for s in REGISTRY if s.kind == kind]
