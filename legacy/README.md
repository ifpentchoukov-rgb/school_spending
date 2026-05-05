# Legacy Code & Data — Reference Material

Everything in this directory was produced in two earlier work sessions before the project moved to Claude Code + Supabase. The code here is **reference material and seed data**, not the production system. Don't extend it; read it, port the patterns into the new system, and leave the originals untouched as a record.

## sd_tracker_step1 — district universe

**What it does:** combines NCES Common Core of Data (LEA Universe via Urban Institute API) with Census Bureau F-33 audited finance data to produce one row per US operating district with FY23 baseline expenditures.

**Key output:** `processed/master_districts.csv` — 19,446 LEAs total; 11,880 marked `is_operating_district=true`. **This file is the seed for the `districts` table in Phase 1.**

**Schema reference:** see `scripts/state_tiers.py` for the data-tier classification (1 = centralized, 2 = decentralized, 3 = limited). Tier values are in the `data_tier` column of master_districts.csv.

**Re-running:** `python3 scripts/build_master.py` (uses cached CCD JSON if present in a `raw/` directory; will re-download otherwise; takes ~15 min).

## sd_tracker_step2 — three working state extractors

**What it does:** pulls FY25 audited expenditure data per district for TX, CA, FL; computes year-over-year change vs FY24; outputs a normalized stack.

**Key outputs:**
- `processed/state_extractions.csv` — 1,607 records, normalized schema. **This is the seed for FY25 `actual` records in `budget_events`.**
- `processed/spending_signal.csv` — same data joined to master_districts (one row per district)

**The pattern to preserve** (port to the new system in Phase 3):
- `extractors/_base.py` defines the normalized output schema. New extractors should produce records with the same fields.
- Each state extractor has a single `extract()` function that returns a DataFrame.
- A unified runner (`run_extractors.py`) stacks all extractors and joins to master.

**Three template patterns the next 47 states will follow:**
- **TX** (`tx.py`) — bulk Excel download. Easy. ~15 states will look like this.
- **CA** (`ca.py`) — Microsoft Access `.mdb` extracted via `mdbtools`. ~5 states.
- **FL** (`fl.py`) — fetch a PDF per district, regex-parse the General Fund total. Worst-case fallback.

## Known limitations of the legacy code (intentionally not fixed)

These are the reasons the project moved to a new architecture, not bugs to fix in legacy/:

1. **CSVs, not a database.** Concurrent verification, audit trail, and source-document references all need real tables. PLAN.md §4 specifies the schema.
2. **Status is always `actual`.** Only audited prior-year actuals are pulled. FY27 budget adoption tracking (proposed/tentative/adopted/disapproved) is the new system's purpose.
3. **No source-document references.** Legacy records have a `source` URL but no PDF page number, no content hash, no Supabase Storage path. The new schema fixes this.
4. **No verification workflow.** Legacy data is "what the extractor found," with no human sign-off layer.
5. **Coverage gaps.** CA matches only 474 of 697 operating districts (charter LEAs filing via Alternative Form not handled). FL covers only 67 county districts (lab schools missing). These are documented but not fixed.
6. **Sandbox-relative paths.** Some scripts assume specific directory layouts. Won't work without minor adjustment if you re-run them.

## What to take from this code into the new system

- The **NCES LEAID as the universal join key** — keep using it.
- The **state_leaid format** (e.g. `'TX-054901'`, `'CA-1975309'`) — keep using it; state extractors strip the prefix.
- The **agency_type / agency_level filter** for "operating district" (types 1, 2, 7, 9 with level 4 and at least one school) — keep using it.
- The **TX district number → NCES LEAID crosswalk via state_leaid** — keep using it; same pattern works for every state.
- The **F-33 dollar conversion** (Census reports in thousands; multiply by 1000) — easy to forget.
- The **PEIMS topline definition** (`ALL FUNDS-TOTAL OPERATING EXPENDITURES BY OBJ`) and **SACS topline definition** (Object 1000-7999 in Funds 01-29) — these were chosen carefully to be comparable to F-33's "current expenditures" concept.
