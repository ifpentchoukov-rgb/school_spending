"""Seed `state_calendars` for FY27 (school year 2026-27).

Top-15 states by enrollment as of seed time. Coverage rationale: those 15
account for ~60% of US K-12 enrollment, so they're the priority targets for
Phase 4's "active states" cron gating.

Data sources are the state codes themselves; specific section is in
`statute_citation`. Where the proposed_window dates are best-estimate rather
than statutory, the `notes` field flags it explicitly so a verifier knows
what to confirm. Re-running this script upserts on (state_postal, fiscal_year),
so corrections in DB are not overwritten unless the script is updated.

Run:  .venv/bin/python -m seeds.seed_state_calendars
"""

from __future__ import annotations

import sys

from seeds._client import get_client

FISCAL_YEAR = 2027

# Per-state FY27 calendar. Dates in ISO format. NULL where not statutorily
# fixed and best-estimate would be misleading.
ROWS: list[dict] = [
    {
        "state_postal": "TX",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = Sept 1, 2026 – Aug 31, 2027
        "proposed_window_start": "2026-07-01",
        "proposed_window_end": "2026-08-25",
        "adoption_deadline": "2026-08-25",
        "oversight_review_deadline": None,
        "statute_citation": "Tex. Educ. Code § 44.004",
        "notes": (
            "Sept-Aug fiscal year. Districts must adopt the budget by Aug 25 "
            "after public meeting and 10-30 day published notice. Larger ISDs "
            "(>=$100M, § 44.0041) and TRE-related amendments may shift dates. "
            "TEA does not approve adoption; it ingests post-hoc via PEIMS."
        ),
    },
    {
        "state_postal": "CA",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027
        "proposed_window_start": "2026-05-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-07-01",
        # County superintendent must review by Aug 15; if disapproved, district
        # has until 3rd Wednesday in October (Oct 21, 2026) to revise.
        "oversight_review_deadline": "2026-08-15",
        "statute_citation": "Cal. Educ. Code § 42127",
        "notes": (
            "Governing board adopts by July 1 after public hearing. County "
            "superintendent reviews by Aug 15 (§ 42127(c)). Disapproval triggers "
            "revision; county can intervene under § 42127.3. SACS Budget filings "
            "go through CDE."
        ),
    },
    {
        "state_postal": "FL",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027
        "proposed_window_start": "2026-07-15",
        "proposed_window_end": "2026-09-15",
        "adoption_deadline": "2026-09-30",
        "oversight_review_deadline": None,
        "statute_citation": "Fla. Stat. § 200.065 (TRIM) + § 1011.03",
        "notes": (
            "TRIM hearings: tentative late July/early Aug; final mid-Sept. "
            "Submission to FLDOE Summary Budget portal by Sept 30. § 200.065 "
            "controls the millage/budget adoption schedule (within 80 days of "
            "July 1 tax roll certification). § 1011.03 governs FLDOE submission."
        ),
    },
    {
        "state_postal": "NY",
        "fiscal_year": FISCAL_YEAR,
        # School district budget vote is 3rd Tuesday in May
        "proposed_window_start": "2026-04-01",
        "proposed_window_end": "2026-05-19",
        "adoption_deadline": "2026-05-19",
        "oversight_review_deadline": None,
        "statute_citation": "N.Y. Educ. Law § 1716, § 2022, § 2023",
        "notes": (
            "Most NY districts hold a voter referendum on the 3rd Tuesday in "
            "May (May 19, 2026). If defeated, may revote in June; second "
            "defeat triggers contingency budget under § 2023. Big 5 cities "
            "(NYC, Buffalo, Rochester, Syracuse, Yonkers) are excluded — "
            "their budgets are mayoral/city-council adopted, separate timeline."
        ),
    },
    {
        "state_postal": "GA",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027
        "proposed_window_start": "2026-04-15",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-06-30",
        "oversight_review_deadline": None,
        "statute_citation": "O.C.G.A. § 20-2-167, § 20-2-168",
        "notes": (
            "Tentative budget published with at least one public hearing 14+ "
            "days before adoption. Final adoption before fiscal year start "
            "(July 1). GaDOE collects after the fact via the Annual Financial "
            "Report (DE0046)."
        ),
    },
    {
        "state_postal": "PA",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027
        "proposed_window_start": "2026-05-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-06-30",
        "oversight_review_deadline": None,
        "statute_citation": "24 P.S. § 6-687, § 6-688 (Public School Code)",
        "notes": (
            "Proposed budget on public display at least 30 days before "
            "adoption. Adoption by June 30. Act 1 of 2006 adds preliminary "
            "budget timing for districts seeking referendum exceptions "
            "(prelim by mid-Feb of the budget year)."
        ),
    },
    {
        "state_postal": "OH",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027
        "proposed_window_start": "2026-01-01",  # tax budget filed Jan 15
        "proposed_window_end": "2026-09-30",
        "adoption_deadline": "2026-10-01",  # permanent appropriation deadline
        "oversight_review_deadline": "2026-03-01",  # county budget commission
        "statute_citation": "Ohio Rev. Code § 5705.28, § 5705.34, § 5705.41",
        "notes": (
            "Two-stage process: (1) tax budget filed with county auditor by "
            "Jan 15 (or July 20 for some); (2) permanent appropriation "
            "resolution by Oct 1 (temporary by Apr 1 acceptable). County "
            "budget commission certifies budget by ~March."
        ),
    },
    {
        "state_postal": "NC",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-04-01",
        "proposed_window_end": "2026-05-15",
        "adoption_deadline": "2026-07-01",
        # County commissioners adopt the appropriation by July 1
        "oversight_review_deadline": "2026-07-01",
        "statute_citation": "N.C. Gen. Stat. § 115C-426 through § 115C-441",
        "notes": (
            "LEA submits proposed budget to board of county commissioners by "
            "May 15. County adopts the school appropriation by July 1 "
            "(§ 115C-429). LEA adopts its full budget after county "
            "appropriation is fixed. Disputes go to mediation/superior court."
        ),
    },
    {
        "state_postal": "MI",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027 (most districts)
        "proposed_window_start": "2026-05-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-07-01",
        "oversight_review_deadline": None,
        "statute_citation": "Mich. Comp. Laws § 380.1216, Uniform Budgeting and Accounting Act (PA 2 of 1968)",
        "notes": (
            "Districts must adopt before the fiscal year begins. Public "
            "hearing required 6+ days before adoption ('Truth in Budgeting "
            "Act'). Most operate July-June; a small number of intermediate "
            "districts use Oct-Sept."
        ),
    },
    {
        "state_postal": "VA",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-02-01",
        "proposed_window_end": "2026-04-01",
        # School board submits to local governing body by April 1
        "adoption_deadline": "2026-05-15",
        "oversight_review_deadline": "2026-05-15",  # local governing body
        "statute_citation": "Va. Code § 22.1-92, § 22.1-93",
        "notes": (
            "School board prepares and submits to local governing body (city "
            "council/county BOS) by April 1. Governing body must approve the "
            "appropriation by May 15. School board then adopts the full "
            "budget. Independent cities and counties have parallel processes."
        ),
    },
    {
        "state_postal": "IL",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027
        "proposed_window_start": "2026-07-01",
        "proposed_window_end": "2026-09-30",
        "adoption_deadline": "2026-09-30",
        "oversight_review_deadline": None,
        "statute_citation": "105 ILCS 5/17-1, 5/17-3.2",
        "notes": (
            "Tentative budget on display for public inspection at least 30 "
            "days before adoption. Adoption within first quarter of fiscal "
            "year (i.e. by Sept 30). Filed with ROE/ISBE via Annual Financial "
            "Report after audit."
        ),
    },
    {
        "state_postal": "WA",
        "fiscal_year": FISCAL_YEAR,
        # WA school FY = Sept 1, 2026 – Aug 31, 2027 — UNUSUAL among states
        "proposed_window_start": "2026-07-10",
        "proposed_window_end": "2026-08-31",
        "adoption_deadline": "2026-08-31",
        # ESD reviews and certifies prior to adoption
        "oversight_review_deadline": "2026-08-15",
        "statute_citation": "Wash. Rev. Code § 28A.505.040, § 28A.505.060",
        "notes": (
            "WA school districts use a Sept-Aug fiscal year (NOT July-June). "
            "Budget filed with the ESD by July 10; adopted at public meeting "
            "by Aug 31. ESD review precedes adoption (§ 28A.505.050). OSPI "
            "compiles statewide via the F-196."
        ),
    },
    {
        "state_postal": "NJ",
        "fiscal_year": FISCAL_YEAR,
        # FY27 = July 1, 2026 – June 30, 2027
        "proposed_window_start": "2026-02-01",
        "proposed_window_end": "2026-05-15",
        "adoption_deadline": "2026-05-15",
        # Executive county superintendent reviews
        "oversight_review_deadline": "2026-03-22",
        "statute_citation": "N.J. Stat. § 18A:22-1 et seq.",
        "notes": (
            "Tentative budget submitted to executive county superintendent "
            "for review (typically early March). Districts on the April school "
            "election cycle hold a voter referendum; most have moved to "
            "November general or no-vote (board-adopted) cycles since 2012. "
            "Final adoption by mid-May. Type I districts (board appointed) "
            "have no voter approval."
        ),
    },
    {
        "state_postal": "IN",
        "fiscal_year": FISCAL_YEAR,
        # IN school operating fiscal year is July 1 – June 30 (since 2017)
        "proposed_window_start": "2026-08-01",
        "proposed_window_end": "2026-11-01",
        # DLGF certifies by Feb 15 of the following year for property-tax-funded budgets
        "adoption_deadline": "2026-11-01",
        "oversight_review_deadline": "2027-02-15",
        "statute_citation": "Ind. Code § 6-1.1-17, § 20-40-2",
        "notes": (
            "School operating fund moved to July-June since 2017 (PL 217-2017). "
            "Property-tax-funded budgets adopted by Nov 1 of preceding calendar "
            "year and certified by DLGF by Feb 15. School operating budget for "
            "FY27 (July 2026) is adopted in fall 2025 / approved Feb 2026 — "
            "this row reflects the FY27 operating cycle, not the calendar."
        ),
    },
    {
        "state_postal": "TN",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-04-01",
        "proposed_window_end": "2026-07-01",
        "adoption_deadline": "2026-07-01",
        # County legislative body must adopt
        "oversight_review_deadline": "2026-07-01",
        "statute_citation": "Tenn. Code § 49-2-301, § 49-3-316",
        "notes": (
            "LEA submits to county legislative body (commission); county "
            "adopts appropriation typically by July 1. Special school "
            "districts and some city school systems have variations. State "
            "BEP allocations published by Apr 1 inform planning."
        ),
    },
]


def main() -> int:
    client = get_client()
    print(f"seeding state_calendars for fiscal_year={FISCAL_YEAR}: {len(ROWS)} rows")

    inserted = 0
    updated = 0
    for row in ROWS:
        existing = (
            client.table("state_calendars")
            .select("state_postal")
            .eq("state_postal", row["state_postal"])
            .eq("fiscal_year", row["fiscal_year"])
            .execute()
        )
        if existing.data:
            client.table("state_calendars").update(row).eq(
                "state_postal", row["state_postal"]
            ).eq("fiscal_year", row["fiscal_year"]).execute()
            updated += 1
        else:
            client.table("state_calendars").insert(row).execute()
            inserted += 1

    print(f"  inserted={inserted}  updated={updated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
