"""
Base extractor schema — every per-state extractor returns a DataFrame with
this normalized column set so downstream reconciliation can stack them.

Output schema:
  leaid              str  NCES 7-digit LEAID (the join key into master_districts)
  state_postal       str  2-char state postal
  state_leaid        str  Native state district code, for traceability
  fiscal_year        int  Fiscal year (e.g. 25 for 2024-25, 26 for 2025-26)
  status             str  One of: proposed | tentative | adopted | disapproved
                          | actual | unknown
  topline_amount     float USD — total operating expenditures for the FY
                          (definition normalized to 'all funds, total operating
                          expenditures by object' where possible)
  yoy_change_pct     float % change vs prior FY topline (None if unknown)
  yoy_change_dollars float Dollar change vs prior FY topline (None if unknown)
  source             str  URL or human-readable origin
  source_date        str  ISO date the extractor pulled or source publication
  notes              str  Anything atypical about this row

Status definitions:
  - proposed     : Superintendent's draft, not yet voted on
  - tentative    : Board has tentatively adopted; final vote pending
  - adopted      : Board has finally adopted (this is the headline status)
  - disapproved  : County/state authority disapproved an adopted budget
                   (CA-specific; rare elsewhere)
  - actual       : Audited actual expenditure, not a budget
  - unknown      : Status could not be determined from the source
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

OUTPUT_COLUMNS = [
    "leaid",
    "state_postal",
    "state_leaid",
    "fiscal_year",
    "status",
    "topline_amount",
    "yoy_change_pct",
    "yoy_change_dollars",
    "source",
    "source_date",
    "notes",
]

VALID_STATUS = {
    "proposed", "tentative", "adopted",
    "disapproved", "actual", "unknown",
}


@dataclass
class ExtractorRecord:
    leaid: str
    state_postal: str
    state_leaid: str
    fiscal_year: int
    status: str
    topline_amount: Optional[float] = None
    yoy_change_pct: Optional[float] = None
    yoy_change_dollars: Optional[float] = None
    source: str = ""
    source_date: str = ""
    notes: str = ""

    def __post_init__(self):
        if self.status not in VALID_STATUS:
            raise ValueError(
                f"status='{self.status}' not in {VALID_STATUS}"
            )


def to_dataframe(records):
    """Convert list[ExtractorRecord] -> normalized DataFrame."""
    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    df = pd.DataFrame([r.__dict__ for r in records])
    return df[OUTPUT_COLUMNS]


def validate(df):
    """Sanity-check an extractor output DataFrame."""
    issues = []
    if list(df.columns) != OUTPUT_COLUMNS:
        issues.append(f"columns mismatch: {list(df.columns)}")
    if not df.empty:
        if df["leaid"].str.len().min() != 7 or df["leaid"].str.len().max() != 7:
            issues.append("leaid column not all 7 chars")
        invalid_status = set(df["status"]) - VALID_STATUS
        if invalid_status:
            issues.append(f"invalid status values: {invalid_status}")
    return issues
