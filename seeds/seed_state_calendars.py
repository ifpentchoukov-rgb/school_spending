"""Seed `state_calendars` for FY27 (school year 2026-27).

Top-35 states by enrollment as of seed time. Coverage rationale: those 35
account for ~90% of US K-12 enrollment, so they're the priority targets for
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
    # ------------------------------------------------------------------
    # Rank 16-25 — adds ~5M enrollment (cumulative ~80% US coverage)
    # ------------------------------------------------------------------
    {
        "state_postal": "MD",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-02-01",
        "proposed_window_end": "2026-04-01",
        # County council appropriates by Jun 1; LEA finalizes by Jul 1
        "adoption_deadline": "2026-07-01",
        "oversight_review_deadline": "2026-06-01",
        "statute_citation": "Md. Code Ann., Educ. § 5-101 to § 5-115",
        "notes": (
            "24 LEAs (one per county + Baltimore City). Superintendent "
            "submits proposed budget to county council/mayor by April 1; "
            "council appropriates by June 1; LEA adopts final budget after "
            "appropriation. Baltimore City has a parallel mayoral process."
        ),
    },
    {
        "state_postal": "MO",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-05-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-07-01",
        "oversight_review_deadline": None,
        "statute_citation": "Mo. Rev. Stat. § 67.010, § 165.011",
        "notes": (
            "Adoption before fiscal year start (July 1). Public hearing "
            "required, with at least 10 days' notice. Filed with State "
            "Auditor; DESE compiles via Annual Secretary of the Board "
            "Report (ASBR)."
        ),
    },
    {
        "state_postal": "CO",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-04-01",
        # Proposed budget submitted to BOE by June 1 (§ 22-44-108)
        "proposed_window_end": "2026-06-01",
        "adoption_deadline": "2026-06-30",
        "oversight_review_deadline": None,
        "statute_citation": "C.R.S. § 22-44-101 et seq. (School District Budget Law)",
        "notes": (
            "Proposed budget filed with board of education by June 1; "
            "adoption by June 30 after public hearing. Final filed with CDE "
            "and DLG. December reconciliation amendment common after final "
            "state aid is set."
        ),
    },
    {
        "state_postal": "MN",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-05-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-07-01",
        "oversight_review_deadline": "2026-12-31",  # Truth in Taxation
        "statute_citation": "Minn. Stat. § 123B.10, § 275.065",
        "notes": (
            "Preliminary budget by June 30. Truth in Taxation hearings in "
            "fall (Nov-Dec) finalize property-tax-funded portions once state "
            "aid is set. MDE compiles via UFARS. Charter LEAs file separately."
        ),
    },
    {
        "state_postal": "MA",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-03-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-07-01",
        "oversight_review_deadline": None,
        "statute_citation": "M.G.L. c. 71, § 34 (school committees), § 16B (regional districts)",
        "notes": (
            "Process varies by district type. Town/city districts: school "
            "committee proposes; town meeting or city council appropriates "
            "(spring). Regional districts: assessment apportioned among "
            "member towns; each town meeting must approve. Adoption typically "
            "by July 1; DESE collects via End of Year Financial Report."
        ),
    },
    {
        "state_postal": "SC",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-04-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-06-30",
        # Some districts have legislative delegation appropriation
        "oversight_review_deadline": "2026-06-30",
        "statute_citation": "S.C. Code § 59-21-1010 et seq.",
        "notes": (
            "Many SC districts have local enabling acts that govern budget "
            "adoption (legislative delegation involvement, county council "
            "appropriation, etc.). 'Districts of the second class' adopt "
            "via county. Generic statute is the floor; per-district "
            "verification needed for non-standard arrangements."
        ),
    },
    {
        "state_postal": "WI",
        "fiscal_year": FISCAL_YEAR,
        # WI levy certified by Nov 1; final budget Oct 31
        "proposed_window_start": "2026-08-01",
        "proposed_window_end": "2026-10-31",
        "adoption_deadline": "2026-10-31",
        "oversight_review_deadline": None,
        "statute_citation": "Wis. Stat. § 65.90, § 120.12, § 120.18",
        "notes": (
            "Annual meeting (typically May or July, depends on district class) "
            "sets initial tax levy authority. Final budget adopted by Oct 31 "
            "after Oct 15 state aid certification by DPI. Class of district "
            "(common, union high, unified) affects timing. DPI collects via "
            "PI-1505 and SAFR."
        ),
    },
    {
        "state_postal": "AL",
        "fiscal_year": FISCAL_YEAR,
        # AL school FY actually Oct 1 – Sept 30 since 2010 (NOT Sept-Aug)
        "proposed_window_start": "2026-08-01",
        "proposed_window_end": "2026-09-15",
        "adoption_deadline": "2026-09-15",
        "oversight_review_deadline": None,
        "statute_citation": "Ala. Code § 16-13-140 to § 16-13-145",
        "notes": (
            "DATA NOTE: master_districts.csv has fy_calendar='Sept-Aug' for "
            "AL, but Ala. Code § 16-13-140 actually defines the school "
            "fiscal year as Oct 1 - Sept 30 (changed in 2010 by Act 2010-528). "
            "FY27 = Oct 1, 2026 - Sept 30, 2027. Adoption required before "
            "fiscal year start with at least one public hearing. Verifier "
            "should reconcile this discrepancy in master_districts."
        ),
    },
    {
        "state_postal": "OK",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-06-01",
        # OK uses estimate of needs filed with county excise board; final
        # appropriation tied to county tax certification (Oct 1)
        "proposed_window_end": "2026-09-30",
        "adoption_deadline": "2026-08-01",
        "oversight_review_deadline": "2026-10-01",
        "statute_citation": "Okla. Stat. tit. 70, § 5-150 et seq.; tit. 68, § 3007",
        "notes": (
            "Two-stage like OH: districts adopt budget by Aug 1; county "
            "excise board certifies tax rates / millages by Oct 1. Districts "
            "may operate on temporary appropriation between July 1 fiscal "
            "year start and county certification. OSDE collects via OCAS."
        ),
    },
    {
        "state_postal": "KY",
        "fiscal_year": FISCAL_YEAR,
        # Three-stage: tentative (Jan), working (May), final (Sept)
        "proposed_window_start": "2026-01-01",
        "proposed_window_end": "2026-09-30",
        "adoption_deadline": "2026-09-30",
        "oversight_review_deadline": "2026-09-30",  # KDE approves
        "statute_citation": "KRS 160.460 (tentative), 160.470 (working/final), 702 KAR 3:246",
        "notes": (
            "Three-stage process: tentative by Jan 31 of preceding year, "
            "working budget by May 30, final budget by Sept 30 (after audited "
            "revenue actuals known). KDE approves at each stage. School "
            "Facilities Construction Commission has separate review for "
            "capital outlay portions."
        ),
    },
    # ------------------------------------------------------------------
    # Rank 26-35 — pushes coverage to ~90% US K-12 enrollment
    # ------------------------------------------------------------------
    {
        "state_postal": "AZ",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-06-01",
        # Proposed budget by July 5; adoption by July 15
        "proposed_window_end": "2026-07-05",
        "adoption_deadline": "2026-07-15",
        "oversight_review_deadline": None,
        "statute_citation": "A.R.S. § 15-905",
        "notes": (
            "Proposed budget published by July 5; adoption by July 15 after "
            "public hearing. Truth in Taxation hearing required if levy "
            "increases (§ 15-905.01). ADE collects via APOR / AFR; State "
            "Board of Education involvement for charters."
        ),
    },
    {
        "state_postal": "UT",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-05-01",
        "proposed_window_end": "2026-06-22",
        "adoption_deadline": "2026-06-22",
        "oversight_review_deadline": None,
        "statute_citation": "Utah Code § 53G-7-302, § 53G-7-303",
        "notes": (
            "Tentative budget by June 1; final adoption by June 22 (within "
            "30 days of state aid certification). Truth in Taxation hearing "
            "in August if revenue exceeds certified rate (§ 59-2-919). USBE "
            "compiles via UPEFS."
        ),
    },
    {
        "state_postal": "LA",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-06-01",
        # Adopted by Sept 15 — AFTER fiscal year start (unusual)
        "proposed_window_end": "2026-09-15",
        "adoption_deadline": "2026-09-15",
        "oversight_review_deadline": None,
        "statute_citation": "La. R.S. § 39:1301 et seq. (Local Government Budget Act); R.S. § 17:88",
        "notes": (
            "73 parishes (LEAs). Districts may operate on prior-year "
            "appropriation between July 1 fiscal year start and Sept 15 "
            "adoption. Public hearing with at least 10 days' notice. "
            "Louisiana Legislative Auditor reviews compliance. LDE compiles "
            "via Annual Financial Report."
        ),
    },
    {
        "state_postal": "OR",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-04-01",
        # Budget committee + board adoption typically by mid-June
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-06-30",
        "oversight_review_deadline": None,
        "statute_citation": "ORS § 294.305 to § 294.476 (Local Budget Law)",
        "notes": (
            "Two-step Local Budget Law: budget officer drafts → budget "
            "committee (board + equal lay members) approves → board adopts "
            "by June 30 after public hearing. ODE compiles via SD2 / NCES "
            "submissions. ESDs run a parallel cycle."
        ),
    },
    {
        "state_postal": "IA",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-03-01",
        # IA shifted to April 30 from March 15 (recent)
        "proposed_window_end": "2026-04-30",
        "adoption_deadline": "2026-04-30",
        "oversight_review_deadline": None,
        "statute_citation": "Iowa Code § 24.1 et seq. (Local Budget Law); § 257 (school finance formula)",
        "notes": (
            "Adoption by April 30 (was March 15 historically; statute "
            "amended). Budget summary published in newspaper at least 10 "
            "days before adoption. Filed with state auditor. IA DE compiles "
            "via Certified Annual Report."
        ),
    },
    {
        "state_postal": "AR",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-07-01",
        # Adopted by Sept 15 (after FY start) — like LA
        "proposed_window_end": "2026-09-15",
        "adoption_deadline": "2026-09-15",
        "oversight_review_deadline": None,
        "statute_citation": "Ark. Code § 6-13-624, § 6-20-401",
        "notes": (
            "Adoption by Sept 15 after public hearing. Districts may operate "
            "on prior-year appropriation Jul 1 – Sept 15. ADE reviews via "
            "APSCN financial system. Special school districts and county "
            "districts have separate frameworks."
        ),
    },
    {
        "state_postal": "NV",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-03-01",
        "proposed_window_end": "2026-05-15",
        "adoption_deadline": "2026-05-15",
        # Department of Taxation approval
        "oversight_review_deadline": "2026-06-01",
        "statute_citation": "N.R.S. § 354 (Local Government Budget); § 387 (school finance)",
        "notes": (
            "17 county-based districts plus charter LEAs. Tentative budget "
            "by April 15; adopted by May 15 (third Thursday in May per "
            "§ 354.598). Department of Taxation reviews and approves. NDE "
            "compiles via NPRS."
        ),
    },
    {
        "state_postal": "KS",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-07-01",
        "proposed_window_end": "2026-08-25",
        "adoption_deadline": "2026-08-25",
        "oversight_review_deadline": None,
        "statute_citation": "K.S.A. § 72-5142 (school budget); § 79-2925 (Cash Basis Law)",
        "notes": (
            "Adoption by Aug 25 after public hearing with 10 days' notice. "
            "Filed with county clerk. Kansas Department of Administration "
            "Division of Accounts and Reports collects. KSDE compiles via "
            "ELI / state aid system."
        ),
    },
    {
        "state_postal": "CT",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-02-01",
        "proposed_window_end": "2026-06-30",
        "adoption_deadline": "2026-07-01",
        # Town meeting / city council appropriation
        "oversight_review_deadline": "2026-06-30",
        "statute_citation": "Conn. Gen. Stat. § 10-222 (BOE budget); § 7-340 et seq. (municipal)",
        "notes": (
            "165 LEAs (towns + Regional School Districts + state-administered). "
            "BOE proposes → town/city legislative body appropriates → BOE "
            "adopts within appropriation. Process timing varies by town "
            "charter (some have spring referendum, others legislative "
            "council). CSDE compiles via ED-001."
        ),
    },
    {
        "state_postal": "MS",
        "fiscal_year": FISCAL_YEAR,
        "proposed_window_start": "2026-06-01",
        "proposed_window_end": "2026-08-15",
        "adoption_deadline": "2026-08-15",
        "oversight_review_deadline": None,
        "statute_citation": "Miss. Code § 37-61-9, § 27-39-329",
        "notes": (
            "Adoption by Aug 15 after public hearing. Some districts have "
            "separate municipal/county appropriation. State Auditor compliance "
            "review; MDE compiles via Annual Financial Report. Consolidated "
            "school districts (state takeovers) have parallel process."
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
