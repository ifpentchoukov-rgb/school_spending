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
]


def by_state(state_postal: str) -> list[ExtractorSpec]:
    return [s for s in REGISTRY if s.state_postal == state_postal]


def by_kind(kind: str) -> list[ExtractorSpec]:
    return [s for s in REGISTRY if s.kind == kind]
