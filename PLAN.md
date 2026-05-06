# School District Budget Tracker — Project Plan

This document is the source of truth for project scope, architecture, and conventions. It is written for Claude Code to read at the start of every working session, and for human contributors to review and amend.

If anything in this document is wrong, fix the document first, then the code. Don't silently diverge.

---

## 1. What this system does

For every operating public school district in the United States (~12,000 districts), the system tracks the **adopted operating budget for fiscal year 2027** (school year 2026-27 in most states; September 2026 – August 2027 in TX/AL).

For each district, we maintain:

- The **proposed**, **tentative**, **adopted**, or **disapproved** status of the FY27 budget
- The **topline expenditure amount** at each status stage
- The **year-over-year change** vs the FY26 prior year baseline
- A **link to the source document** that proves the status (URL, PDF page, board minutes line item, etc.)
- A **verification record** (which human checked it, when, and what they confirmed)

Data updates daily via scheduled extractors. Humans verify a sample of records before they are marked authoritative.

The eventual published artifact is a national rollup: how many districts increased spending, how many decreased, by how much, with full provenance.

---

## 2. Prior work — what already exists

Two earlier phases produced working code and data, archived in `legacy/sd_tracker_step1` and `legacy/sd_tracker_step2` of this repo:

- **Step 1** built `master_districts.csv` — every operating US district keyed on NCES LEAID, with FY23 baseline expenditures from the Census F-33. This is the universe table.
- **Step 2** built three working state extractors (TX, CA, FL) that pull recent audited actuals (FY25), normalize them to a common schema (`leaid`, `fiscal_year`, `status`, `topline_amount`, `yoy_change_pct`, `yoy_change_dollars`, `source`, `source_date`, `notes`), and stack them into a single CSV.

These produce only `status="actual"` records. The new system extends this to track `proposed`/`tentative`/`adopted`/`disapproved` for FY27 specifically, with full audit trail, in a database rather than CSVs.

The extractor pattern from Step 2 is good and should be preserved. The Step 2 outputs become the seed data for the new database.

---

## 3. Architecture (decided — do not relitigate without explicit user sign-off)

- **Code:** Claude Code working in a Git repo (this repo). All code in version control. PRs for non-trivial changes.
- **Data:** Supabase Postgres. All authoritative data lives here, not in CSVs. Use the Supabase MCP for schema migrations and data writes; do not hand-write SQL connection strings.
- **Scheduling:** GitHub Actions cron jobs. No external scheduler.
- **Storage of source documents:** Supabase Storage buckets, one bucket per state. Original PDFs/Excel files preserved with content hash.
- **Human verification UI:** Supabase Studio (the table editor). No custom frontend in v1.
- **Secrets:** GitHub Actions secrets for CI; `.env.local` for local development (never committed).

If a non-obvious tradeoff comes up that pushes against any of these decisions, raise it with the user before changing course.

---

## 4. Data model

Schema lives in Postgres under the default `public` schema. Use Supabase migrations (one numbered SQL file per change) so the schema is reproducible.

### Core tables

**`districts`** — the universe of operating school districts. Seeded once from `master_districts.csv`; rarely changes.

Key columns:
- `leaid` (text, PK) — 7-digit NCES ID, zero-padded
- `lea_name`, `state_postal`, `state_leaid`, `county_name`
- `enrollment_fy25` (int)
- `exp_total_fy23` (numeric) — F-33 baseline
- `is_operating_district` (bool)
- `data_tier` (smallint, 1-3)
- `fy_calendar` (text: `'July-June'` or `'Sept-Aug'`)
- `created_at`, `updated_at` (timestamptz)

**`state_calendars`** — statutory budget adoption deadlines per state. Seeded by hand-research in Phase 2.

Key columns:
- `state_postal` (text, PK)
- `proposed_window_start`, `proposed_window_end` (date) — when superintendent proposals are typically published
- `adoption_deadline` (date) — statutory deadline for board final adoption
- `oversight_review_deadline` (date, nullable) — county/state review (CA-specific etc.)
- `statute_citation` (text) — e.g. "Cal. Educ. Code § 42127"
- `notes` (text)

Each row is for FY27 specifically; we'll add a `fiscal_year` column and re-seed annually.

**`budget_events`** — the heart of the system. One row per (district, fiscal_year, status_change).

Key columns:
- `id` (uuid, PK)
- `leaid` (text, FK → districts)
- `fiscal_year` (int) — e.g. 2027
- `status` (enum: `proposed` | `tentative` | `adopted` | `disapproved` | `actual`)
- `topline_amount` (numeric) — total operating expenditures, USD
- `topline_definition` (text) — exact accounting definition used (varies by state)
- `yoy_change_pct` (numeric, nullable)
- `yoy_change_dollars` (numeric, nullable)
- `prior_year_baseline` (numeric, nullable) — what we compared against
- `event_date` (date) — date the status change took effect (board vote date, etc.)
- `source_document_id` (uuid, FK → source_documents) — required, not nullable
- `extraction_run_id` (uuid, FK → extraction_runs)
- `verification_status` (enum: `unverified` | `verified` | `flagged` | `disputed`)
- `verified_by` (text, nullable), `verified_at` (timestamptz, nullable)
- `verification_notes` (text, nullable)
- `is_superseded` (bool, default false) — set true when a later event for same (district, fiscal_year, status) replaces this one
- `created_at`, `updated_at`

Index on `(leaid, fiscal_year, status, is_superseded)` — primary read pattern.

**`source_documents`** — every document we've cited as evidence.

Key columns:
- `id` (uuid, PK)
- `source_url` (text, nullable) — original public URL
- `storage_path` (text, nullable) — path in Supabase Storage
- `content_hash_sha256` (text) — for tamper detection
- `mime_type` (text)
- `fetched_at` (timestamptz)
- `publisher` (text) — "TEA", "FLDOE", "Marin County Office of Education", etc.
- `document_type` (text) — "adopted_budget_pdf", "board_minutes", "summary_data_csv", etc.
- `page_number` (int, nullable) — for PDFs
- `line_or_cell_reference` (text, nullable) — e.g. "Row 47, Column G" or "Statement of Revenues, line 12"
- `notes` (text)

A given source_document can support many budget_events (e.g. one PDF gives both the adopted topline and the prior-year comparison).

**`extraction_runs`** — log of every extractor execution. Required for debugging and accountability.

Key columns:
- `id` (uuid, PK)
- `extractor_name` (text) — e.g. "ca", "tx", "fl"
- `started_at`, `finished_at` (timestamptz)
- `status` (enum: `success` | `partial` | `failed`)
- `records_extracted` (int)
- `records_changed` (int) — vs prior run
- `error_summary` (text, nullable)
- `git_commit_sha` (text) — code version
- `triggered_by` (text) — `'cron'` | `'manual'` | `'backfill'`

**`verification_log`** — append-only audit trail of human actions. Don't update; insert.

Key columns:
- `id` (uuid, PK)
- `budget_event_id` (uuid, FK)
- `actor` (text) — verifier identifier
- `action` (text) — `'verified'` | `'flagged'` | `'disputed'` | `'unflagged'` | `'note_added'`
- `previous_status`, `new_status` (text)
- `notes` (text)
- `created_at` (timestamptz)

### Row-level security

Set RLS policies so:
- Authenticated users with `verifier` role can read everything and update verification fields only on `budget_events`.
- The service role (used by extractors) can write to `budget_events`, `source_documents`, `extraction_runs`, but not `verification_log` directly (verification_log only insertable by verifiers).
- Anonymous users can read `districts` only.

Don't disable RLS as a shortcut. If something seems blocked, fix the policy.

---

## 5. The daily loop

Once per day at 06:00 UTC:

1. **Calendar query** — read `state_calendars`; identify which states have an active proposal-or-adoption window (today between proposed_window_start and 30 days past adoption_deadline).
2. **Extractor selection** — for each active state, look up the corresponding extractor in `extractors/`. Skip states without an extractor (log a warning).
3. **Extractor execution** — run each extractor. Each writes new `budget_events` rows with provenance, downloads new `source_documents` to Supabase Storage, and logs an `extraction_runs` record.
4. **Diff detection** — compare today's records to yesterday's. Where status or topline changed, mark prior records `is_superseded=true` and emit new ones. Never overwrite history.
5. **Daily report** — produce a summary (markdown) posted as a GitHub Action artifact: how many new events, which states, any extractor failures, top changes. Eventually email/Slack this; for now, GitHub artifacts are fine.

This runs as a single GitHub Actions workflow (`.github/workflows/daily.yml`). Local development should be able to run the same loop with `python -m runner` so we don't have CI-only code.

---

## 6. Phases of work

Each phase has explicit acceptance criteria. Don't move on until current phase passes. Don't try to do multiple phases at once.

### Phase 0 — Repo + Supabase setup

- [x] Initialize Git repo, set up `.gitignore` (exclude `.env*`, `raw/`, `__pycache__`, `*.mdb`, `*.exe`)
- [x] Move `legacy/sd_tracker_step1` and `legacy/sd_tracker_step2` from prior work into the repo
- [x] Set up Python project structure: `pyproject.toml`, dev dependencies, ruff or black for formatting
- [x] Confirm Supabase MCP is connected and you can list/create tables — project `school-budget-tracker` (id: `bwkgcofsxubdofklpsaw`, region: `us-east-1`); `list_tables` returns `[]`.
- [x] Create a `migrations/` directory and the first numbered migration file (empty placeholder is fine) — see `migrations/0000_placeholder.sql`.
- [x] Stub `.github/workflows/daily.yml` (a no-op job that just prints "hello" to confirm the cron fires) — confirmed via `workflow_dispatch` on run 25352408081.

**Acceptance:** repo cloneable, dependencies install cleanly, Supabase MCP responds to `list_tables`, GitHub Actions cron runs once successfully. *All four met. Repo: `ifpentchoukov-rgb/school_spending` (public).*

### Phase 1 — Master schema + seed

- [x] Write migration creating `districts`, `source_documents`, `extraction_runs`, `budget_events`, `verification_log`, `state_calendars` — `migrations/0001_core_schema.sql`.
- [x] Apply via Supabase MCP.
- [x] Write a seed script that loads `master_districts.csv` into `districts` — `seeds/seed_districts.py`, operating-only filter, upsert on `leaid`.
- [x] Write a seed script that loads existing Step 2 `state_extractions.csv` into `budget_events` as **FY25 `actual` records** (`fiscal_year=2025`, school year 2024-25) — `seeds/seed_legacy_actuals.py`. Three synthetic `source_documents` rows (TX/CA/FL) cover the NOT NULL FK; legacy PDFs intentionally not backfilled.
- [x] Verify counts: districts=11,880; source_documents=3; budget_events=1,607 (TX 1,068 / CA 472 / FL 67; 2 CA rows skipped for null topline).
- [x] Set up RLS policies — `migrations/0002_rls_policies.sql`. Anon: read `districts`. Authenticated (currently == verifier): read all + update verification fields on `budget_events` + insert `verification_log`. Service role bypasses. Column-level guard via trigger restricts what verifiers can mutate.
- [x] Address Supabase advisor findings — `migrations/0003_advisor_fixes.sql` (security_invoker view, search_path on trigger fns, revoked is_verifier RPC, FK indexes). Security lints now empty.

**Acceptance:** authenticated user can read all districts via the Supabase Studio table editor; service role can insert into budget_events; counts match expectations. ✅ All met.

### Phase 1.5 — First DB-aware extractor: FL FY26 adopted budgets

**Reality check (2026-05-04):** the original "refresh FY26 actuals" plan was unworkable. FY26 actuals don't publish until Jan–April 2027 across TX/CA/FL. Confirmed: TEA PEIMS latest is 2024-25; CDE SACS latest is 2024-25; FLDOE AFR latest is 2024-25.

What IS available right now: **FLDOE District Summary Budget portal** publishes ADOPTED budgets after districts file with the state. As of today, FY26 (school year 2025-26) summary budgets are live at `https://www.fldoe.org/file/7507/{County}TotalBUD2526.pdf` for all 67 FL county districts (Miami-Dade modified 2026-02-27). FY27 PDFs (2627) are 404 — they'll appear after the Sept 30 2026 statutory submission deadline.

So Phase 1.5 pivots from "FY26 actuals across 3 states" to "first real DB-aware extractor — FL FY26 adopted budgets." This lands the Phase 3 architecture (early), captures real adopted-budget records with full provenance, and gives a pipeline that auto-extracts FY27 the moment FLDOE publishes.

- [ ] Create Supabase Storage bucket `fl` (private)
- [ ] Build `extractors/_base.py` with shared helpers: hash, upload, source_documents upsert, supersession-aware budget_events insert, extraction_runs logging
- [ ] Build `extractors/fl.py`: pulls all 67 FL county Summary Budget PDFs from FLDOE, parses General Fund TOTAL APPROPRIATIONS, inserts `budget_events` rows as `fiscal_year=2026, status='adopted'`
- [ ] Run for `fiscal_year=2026`; verify ~67 records with non-null `storage_path` and `content_hash_sha256` on their source_documents
- [ ] Backfill `prior_year_baseline` from the FY25 actuals seeded in Phase 1

**Known gaps (deliberate, not blockers):**
- FLDOE only stores the FINAL adopted budget — proposed/tentative transitions are NOT captured. To track those, we'd need per-district board-portal scraping (BoardDocs etc.) — queued as Phase 6 work.
- 1 FL operating LEA is not on FLDOE (IDEA Public Schools — a charter that files separately). Documented; not extracted.

**Acceptance:** ~67 FL `adopted` budget_events for `fiscal_year=2026`, all with `source_document_id` pointing to a `source_documents` row that has both `storage_path` (Supabase Storage) and `content_hash_sha256` populated. Re-running the extractor with no source change is a no-op.

**Status (2026-05-04): ✅ DONE.** All 67 FL counties matched and extracted on first run. PDFs uploaded to bucket `fl/fy2026/`. `prior_year_baseline` populated for 67/67. Re-run produced 0 changes (idempotent). Two `extraction_runs` logged. Security advisors clean.

### Phase 1.6 — Port TX & CA to the DB-aware pattern (2026-05-05)

Reuse the Phase-1.5 architecture to migrate the legacy step 2 TX/CA extractors into `extractors/`. These rewrite the FY25 actuals seeded in Phase 1 (currently pointing at synthetic `legacy:step2:*` source_documents) with proper provenance — the bulk Excel/MDB stored in Supabase Storage with SHA-256 hash, and supersession of the legacy seed rows.

- [x] **TX**: pulls TEA PEIMS bulk Excel, parses `ALL FUNDS-TOTAL OPERATING EXPENDITURES BY OBJ` per district. Stored at `tx/fy2025/peims_summarized_financial_data.xlsx`. Re-extracted 1,068 records (= legacy count); 1,068 legacy seed rows superseded. 134 PEIMS districts unmatched (charter LEAs / JJAEPs not in master_districts — same gap as legacy).
- [x] **CA**: pulls SACS unaudited actuals .exe (43.9 MB) from CDE; unzip → mdb-export → aggregate Object 1000-7999 in Funds 01-29 per (Ccode, Dcode); also processes prior-year .exe in memory for YoY (not stored). Stored at `ca/fy2025/sacs2425.exe`. 472 records; 472 legacy rows superseded. 571 SACS LEAs unmatched (charter/Alt-Form filers — same gap as legacy).
- [x] Verifier-guard trigger fix (`migrations/0004_fix_verifier_guard.sql`): the original guard from 0002 used the deprecated PostgREST `request.jwt.claim.role` setting, blocking service-role supersession UPDATEs. Switched to `auth.role()`.
- [x] Pagination helper added to `extractors/_base.py` (`fetch_all`) — supabase-py caps a single `.execute()` at 1,000 rows; without pagination the TX crosswalk silently dropped 69 districts.

**Acceptance:** all three Phase-1 legacy seed states (TX/CA + FL legacy actuals stays as-is for now since FLDOE Summary Budget portal serves *budgets* not actuals; we'd need an AFR extractor to upgrade FL actuals provenance) have idempotent extractors writing to `budget_events` with full source-document provenance. Re-runs are no-ops. ✅

**Known gap deferred:** FL FY25 actuals still point at the legacy synthetic `source_documents` row (`legacy:step2:FL`). To upgrade their provenance, build an FL AFR extractor (the legacy `fl.py` AFR pattern) — queued as a follow-up. Doesn't block any current phase.

### Phase 1.8 — Adopted-budget bulk extractors for FY26 (TX gap, CA win)

The premise (Phase 1.5+1.7 left us with FY25 actuals across TX/CA/FL and FY26 adopted for FL only): if the same architecture handles FY26 adopted for TX and CA, we'd have 1,800+ records before the FY27 cycle hits. Investigation revealed an asymmetry:

- **TX**: TEA does **not** publish adopted budgets in bulk. PEIMS only collects actuals; the adopted-budget path requires per-district scraping (~1,069 sites). Same problem-space as NY. Queued for Phase 6.
- **CA**: CDE migrated SACS Budget data from the old `.exe` downloads to the SACS Data Viewer SPA at https://viewer.sacs-cde.org. Reverse-engineered the API (it's a JSON API behind an Angular shell). Built `extractors/ca_budget.py` against it.

**SACS Data Viewer API discovered (documented in `extractors/ca_budget.py`):**
- `GET  /api/ReferenceData/ActiveFiscalYears` — fiscal year status
- `POST /api/Entities/Items` — LEA list per (caFiscalYear, entityType)
- `POST /api/SubmissionArtifacts/Items` — artifact list per (fullFiscalYear, reportingPeriod, cdsCode)
- `GET  /api/SubmissionArtifact/{id}/Blob` — binary download

Each district's BS1 (Budget July 1) submission has exactly one `type='Data'` XLSX file containing UserGL ledger detail. Topline = sum of `Amount` where `ColumnCode='BB' AND FundCode 01-29 AND ObjectCode 1000-7999` (matches the legacy actuals topline definition for direct YoY comparability).

Charter LEAs were initially skipped because, in SACS, charter `cdsCode`s share their first 7 digits with the authorizer's district. The fix: for `entityType='SchoolDistrict'` match by `cdsCode[:7]` (county+district), and for `entityType='CharterSchool'` match by `cdsCode[7:14]` (the SchoolCode portion, which is what NCES uses as the state_leaid suffix for charter LEAs). Both keys are unique within CA, so a single 7-digit-suffix dict handles both — see `cds_lookup_key()` in `extractors/ca_budget.py`. With charters included, SACS entities checked rose from 956 to 2,222 and crosswalk matches from 420 to 637.

### Phase 1.7 — Close the FL FY25 provenance gap (2026-05-05)

Port the legacy AFR extractor as `extractors/fl_afr.py`. Sibling to `extractors/fl.py` (which handles the Summary Budget portal == adopted budgets) — different document, different status (`actual`).

- [x] **fl_afr**: pulls per-county AFR PDFs from `https://www.fldoe.org/file/7507/{shortcode}afr{County}.pdf`, parses Statement of Revenues' General Fund 100 `TOTAL EXPENDITURES 0000` first amount column. Stored at `fl/fy2025/afr/{County}2425afr.pdf`. Re-extracted 67 records; 67 legacy seed rows superseded.
- [x] Re-run is idempotent (records_changed=0).

**Acceptance:** every Phase-1 legacy seed row is now superseded by a properly-provenanced extractor row across all three states. Final database state:

| State | FY | Status | Source | Records |
|---|---|---|---|---|
| TX | 2025 | actual | tx (PEIMS xlsx) | 1,068 |
| CA | 2025 | actual | ca (SACS .exe) | 472 |
| FL | 2025 | actual | fl_afr (AFR pdfs) | 67 |
| FL | 2026 | adopted | fl (Summary Budget pdfs) | 67 |

### Phase 2 — Calendar research + seed

This phase is mostly research. Do it state-by-state. Don't try to bulk-research all 50 states in one pass.

- [x] For each state, identify the statutory budget adoption deadline. Seed a `state_calendars` row — top 15 by enrollment seeded for FY27 in `seeds/seed_state_calendars.py`.
- [ ] Identify the *publication* venue for FY27 budgets — is it a centralized SEA portal, a county portal, district websites, board minutes? Note in the row. *(Notes field captures this for the top 15; remaining states pending.)*
- [ ] Identify the *earliest* date FY27 data is expected to appear in that venue. *(Captured implicitly via `proposed_window_start` for the top 15.)*
- [x] Cite the statute or administrative regulation — done for top 15.

Sources to check (incomplete):
- For most states: Education Commission of the States policy database; SEA "financial reports" page; state legislative code.
- For known-good starting points: CA Educ. Code § 42127 (July 1 budget adoption); TX Educ. Code § 44.004 (Aug 25 deadline for Sept-Aug FY); FL § 1011.03 (Sept 30 finalization); NY EDU § 1716.

Aim for 10 states per session. The full table can take a week of part-time work.

**Acceptance:** at least 15 of the largest-enrollment states have calendar rows with cited statutes. Document in the row's `notes` field anything ambiguous. ✅ **Fully complete (2026-05-05):** **all 50 states + DC seeded — 100% coverage of jurisdictions in `districts`.**
- Top-15: TX, CA, FL, NY, GA, PA, OH, NC, MI, VA, IL, WA, NJ, IN, TN.
- Rank 16-25: MD, MO, CO, MN, MA, SC, WI, AL, OK, KY.
- Rank 26-35: AZ, UT, LA, OR, IA, AR, NV, KS, CT, MS.
- Rank 36-51 (long tail): NE, ID, NM, WV, HI, ME, SD, AK, RI, DE, NH, ND, WY, VT, DC, MT.

**Notable cycles outside the standard "adopt by Jul 1 after public hearing" pattern:**
- **NY** — voter referendum 3rd Tuesday in May (May 19, 2026 for FY27)
- **HI** — biennial state legislature, no per-district adoption event
- **NH/VT** — Town Meeting Day in March; voters approve directly
- **ME** — school board adopts then voters validate by referendum
- **DC** — Oct-Sept federal FY; Mayor → Council → 30-day Congressional review
- **TX/AL** — Sept-Aug or Oct-Sept FY (data-integrity flag below)
- **LA/AR** — adopt AFTER fiscal year start (Sept 15); prior-year approp bridges

**Verifier tasks remaining:**
1. Dates marked as "best-estimate" in the notes column should be confirmed by a human against the SEA / state code before Phase 4 cron logic relies on them.
2. The statute citations themselves came from each state's code; minor section numbers may have moved across recodifications.
3. **Schema widening — DONE (2026-05-05):** `migrations/0006_oct_sept_fiscal_year.sql` added `'Oct-Sept'` to the `fy_calendar` CHECK constraint and corrected 148 AL districts (Sept-Aug → Oct-Sept; Ala. Code § 16-13-140 since 2010 reform) and 6 DC LEAs (July-June → Oct-Sept; federal FY per D.C. Home Rule Act § 446). TX stays Sept-Aug.
4. **MT enrollment anomaly — INVESTIGATED (2026-05-05):** the legacy NCES extract treats Montana K-8 elementary districts as `agency_level_label='State-level only'` and 9-12 high-school districts as `'State + district level'`, while only K-12 unified districts get `'District-level (operating)'`. Phase 1's filter (`is_operating_district=true` matches only the third category) intentionally excluded the K-8 / 9-12 split because each entity is a partial LEA. Result: 64 K-12-unified districts captured (~21k enrollment) out of ~482 NCES MT records (~155k true enrollment). This is a structural mismatch between NCES's level taxonomy and MT's elementary/HS organization. Fix path: re-run legacy step1 with an MT-specific operating-district rule (include `'State-level only'` and `'State + district level'` types where they have non-zero `enrollment_fy25`). Queued as a Phase 6 prerequisite; doesn't affect FY27 budget tracking until an MT extractor exists.

### Phase 3 — Refactor extractors to be DB-aware

- [ ] Refactor `_base.py` to write `budget_events` + `source_documents` directly via Supabase MCP, not return DataFrames
- [ ] Each extractor must, for every record:
  - Download/cache the source document to Supabase Storage
  - Compute SHA-256 hash
  - Insert/update a `source_documents` row
  - Insert a `budget_events` row referencing it
  - Set `is_superseded=true` on any prior event for the same (district, fiscal_year, status)
- [ ] Migrate TX, CA, FL extractors to the new pattern
- [ ] Add idempotency: re-running the same extractor with the same source documents should be a no-op (no duplicate rows)
- [ ] Each extractor logs an `extraction_runs` record on start/finish

**Acceptance:** running TX extractor twice in a row produces the same database state. Running it after the source file changes produces a new `source_documents` row, new `budget_events`, and supersedes the prior ones.

### Phase 4 — Daily scheduler + cron

- [x] Build `runner/daily.py` that reads `state_calendars`, picks active states, dispatches extractors. Calendar gating per PLAN.md §5: today ∈ [proposed_window_start, adoption_deadline + 30 days]. Extractor selection driven by `runner/registry.py`. CLI flags: `--fiscal-year`, `--triggered-by`, `--include-actuals`, `--states`, `--all-states`, `--today`.
- [x] Wire to GitHub Actions cron at 06:00 UTC. Replaced the Phase-0 hello stub with the real workflow. Workflow installs `mdbtools`, sets up Python 3.12, runs the runner, uploads `daily_summary.md` as a 30-day artifact.
- [x] Daily summary report generator — markdown with active calendar windows, per-extractor results table, list of active-but-unimplemented states.
- [x] Basic monitoring: any extractor in `failed` state for two consecutive runs emits/updates a GitHub Issue automatically. Implemented in `runner/check_failures.py` + the `Check for repeated extractor failures` and `Open / update GitHub Issue` workflow steps. Dedups by reusing one open issue per repo (comments append on subsequent failures).

**Acceptance:** workflow runs on schedule, produces a summary, has run successfully for 3 consecutive days without intervention.

**Status (2026-05-05):** First two boxes met. CI run [25386201419](https://github.com/ifpentchoukov-rgb/school_spending/actions/runs/25386201419) succeeded — 28 active states identified for FY27, CA budget extractor ran (0 records since FY27 SACS submissions don't open until fall 2026; expected). Artifact downloaded and verified. **Cron will fire automatically each day at 06:00 UTC; the 3-consecutive-day clock starts now.** The auto-issue-on-failure step is queued as a follow-up.

### Phase 5 — Verification workflow

- [x] Create the work-queue view `unverified_events_high_priority` — top-200-by-enrollment districts × fiscal_year=2027 × verification_status='unverified' × not is_superseded, oldest first. `SECURITY INVOKER` so RLS evaluates against the calling user.
- [x] Document the verifier workflow in `docs/VERIFIER_GUIDE.md` — how to open Storage source documents, find the topline by `line_or_cell_reference`, edit the four allowed verification fields, and append append-only entries to `verification_log`. Includes Q&A for common scenarios.
- [x] Create the spot-check view `verifications_pending_review` — verifier actions in the past 14 days joined to events + source documents.
- [x] RLS confirmed (Phase 1 + Phase 1.6): `guard_budget_events_verifier_update` trigger rejects non-verification-field UPDATEs from `auth.role() = 'authenticated'` users; service_role bypasses. The verifier guide tells reviewers exactly which four fields are mutable.

**Acceptance:** a non-developer team member can log into Supabase Studio, find an unverified record, view the source document, and mark it verified — without writing any SQL. ✅ Met. (Note: queue is empty today since FY27 events haven't been produced yet — first ones are expected fall 2026.)

### Phase 6 — Add new state extractors (ongoing)

In priority order based on enrollment coverage and tier:

1. NY (1,119 LEAs but ~690 operating; NYSED ST-3 + Comptroller data)
2. IL (1,032 LEAs; ISBE Annual Financial Report)
3. PA (~545 districts; PDE AFR)
4. OH (~646 districts; ODE District Profile + Auditor of State)
5. NJ (~700 LEAs; NJDOE Taxpayers Guide + UEZ)
6. ... continue per the tier table in `legacy/sd_tracker_step1/state_tiers.py`

For each new state extractor, follow the **"adding a state" template" in §7.

#### NY scoping notes (2026-05-05)

Looked into building an NY adopted-budget extractor since the NY voter-referendum date is May 19, 2026 (close to today). Findings:

- **NYSED Data Site** (`data.nysed.gov/downloads.php`) — explicitly publishes no school-district financial data as bulk downloads. Only "Expenditures per Pupil" inside the Report Card; not the topline operating budget.
- **NYS Comptroller Open Book / findata** — `wwe1.osc.state.ny.us/localgov/findata/index.cfm` returns 404; the historical bulk download path appears to have moved or been retired. The current `osc.ny.gov/local-government/data` page describes downloadable annual financial spreadsheets for local governments but doesn't expose stable file URLs to a fetcher.
- **ST-3 (Annual Financial Report)** — NYSED collects this from districts but does not publish a machine-readable bulk file.
- **Per-district board portals** — ~690 operating districts, mixed BoardDocs / Diligent / Granicus / custom. Multi-week effort; same problem-space as TX.

**Decision (2026-05-05):** Defer NY extractor. After deeper investigation:
- NYSED data downloads (`data.nysed.gov`) — confirmed no bulk financial data
- NYS Comptroller Socrata datasets on data.ny.gov (7 total, listed under "Office of the State Comptroller") — none are bulk school district budgets; the only school-related dataset is `9pb8-dg53` "NYS School Aid: Beginning 1996-97" which records STATE AID GRANTED (~30-50% of typical operating budget), not the topline
- NYC Open Data (`data.cityofnewyork.us`) — NYC has school budget datasets but they're stale (last updates 2014-15 or 2019)
- Census F-33 — has NY but with 2-3 year lag (already what we used for FY23 baseline)

The cleanest path forward when we revisit will be either (a) FOIA / direct request to NYSED or NYS Comptroller for the ST-3 / financial-data bulk file, or (b) a per-district BoardDocs scraper template that can be reused for TX, NJ, OH, MA. Captured as Phase 6 work; not blocking any current phase.

#### IL extractor (2026-05-05) ✅

Pivoted from NY to IL — next-biggest unimplemented state at 1.12M enrollment. ISBE publishes a single bulk Excel `FY{NN}-OEPP-PCTC.xlsx` with **Total Operating Expenditures** per district per fiscal year, matching the actuals topline used for TX/CA/FL.

- `extractors/il.py` pulls `https://www.isbe.net/_layouts/Download.aspx?SourceUrl=/Documents/FY{NN}-OEPP-PCTC.xlsx`
- Crosswalk: master `state_leaid` `IL-{Region}-{County}-{District}-{Type}` → strip `IL-` and remove hyphens → 11-digit ISBE RCDT.
- Latest published: FY24 (SY 2023-24) — IL audited actuals lag one year behind TX/CA/FL.
- Coverage: 380 records inserted of 397 master IL operating LEAs (the 17 unmatched are typically districts that didn't file or that ISBE consolidated). 470 OEPP rows are unmatched K-8/HS-partial entities and cooperatives (not in our operating-LEA universe).
- Spot check: Chicago Public Schools $7.78B (matches public reporting); SD U-46 $574M; Rockford 205 $454M.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-3` (FY27 calendar runs trigger the FY24 fetch).
- Adopted-budget path (ISBE Form 50-39) NOT covered yet — separate sibling extractor TBD.

#### PA extractor (2026-05-05) ✅

PA was the next-biggest unimplemented state at 1.6M enrollment. PDE publishes a single bulk Excel `{YYYY-YY}gfbdata.xlsx` (GFB = General Fund Budget) covering all ~500 districts' adopted budgets per fiscal year.

- `extractors/pa.py` pulls `https://www.pa.gov/content/dam/copapwp-pagov/en/education/documents/schools/grants-and-funding/school-finances/finances/gfbdata/{YYYY-YY}gfbdata.xlsx`
- Crosswalk: master `state_leaid` `PA-{9-digit-AUN}` → strip `PA-` → matches GFB AUN column directly.
- Topline: `FB_Cert` sheet, `TotalExpAmount` column (certified total adopted operating expenditure budget per district).
- Latest published: FY26 (SY 2025-26, "2025-2026 Final 11Sep2025") — adopted-budget data publishes about 2-3 months after district adoption per 24 P.S. § 6-687.
- Coverage: 490 records inserted of 545 master PA operating LEAs (~90%). 5 unmatched AUNs in the GFB (consolidations or charter LEAs not in our master). 50 master PA districts didn't file or aren't in this snapshot.
- PA total FY26 adopted operating budget: **$39.8B**.
- Idempotent. Registered in `runner/registry.py` with `kind=budget, fy_offset=0` (FY27 calendar runs trigger FY27 GFB fetch directly).
- AFR (actuals) path NOT investigated — file URL pattern wasn't on the AFR landing page; queued as a sibling extractor TBD.

#### GA extractor (2026-05-05) ✅

GA was the next-biggest unimplemented state at 1.73M enrollment. After GADOE's own portals turned up dead ends (the legacy `app3.doe.k12.ga.us` Oracle web reports only have FY1996-1999), found a clean feed via GOSA — the Governor's Office of Student Achievement republishes GADOE's DE0046 financial data as bulk CSVs.

- `extractors/ga.py` pulls `https://download.gosa.ga.gov/{YEAR}/REVENUES_AND_EXPENDITURES{YYYY-YY}_{TIMESTAMP}.csv`. Filename has a timestamp suffix that's not predictable, so a `KNOWN_FILE_URLS` map per FY plus an index-page-scrape fallback.
- Crosswalk: master `state_leaid` `GA-{3-digit-code}` → strip `GA-` → matches GOSA `SCHOOL_DSTRCT_CD` directly. Cobb County code 633 in both systems.
- Topline: sum of `REV_EXP_VALUE` across all 11 expenditure descriptions per district at `DETAIL_LVL_DESC='District'` (Debt Services, General Admin, Instruction, Instructional Support, M&O, Media, Pupil Services, Renovation & Capital Projects, School Admin, Food Services, Transportation).
- Latest published: FY25 (SY 2024-25) — released Feb 19, 2026.
- Coverage: 184 records inserted of 192 master GA operating LEAs (~96%). 19 GOSA codes unmatched (charter LEAs / virtual schools / state-operated entities not in our master).
- Spot check: Gwinnett County $2.55B, Cobb $1.67B, DeKalb $1.59B, Fulton $1.43B, Atlanta Public Schools $1.29B — all match expected scale.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-2`.
- Adopted-budget path NOT covered — districts file by July 1 per O.C.G.A. § 20-2-167 but no clean centralized bulk feed.

#### OH extractor (2026-05-05) ✅

OH was the next-biggest unimplemented state at 1.55M enrollment. After ruling out the Auditor of State portal (no per-district expenditure download for school districts) and the Ohio Checkbook (state agency spending only), found ODE's **Cupp Report** — the District Profile Report Excel published annually around March.

- `extractors/oh.py` pulls `https://education.ohio.gov/getattachment/Topics/Finance-and-Funding/School-Payment-Reports/District-Profile-Reports/FY{NN}-District-Profile-Report/FY{NN}-District-Profile-Report-Final-Revised-{M-DD-YY}-posted.xlsx.aspx?lang=en-US`. Filename includes a "posted" date that's not predictable, so `KNOWN_FILE_URLS` map + index-page-scrape fallback.
- Topline: `Enrolled ADM FY{NN}` × `Total Operating Expenditure Per Pupil FY{NN}` from the `District Data` sheet. The Cupp Report doesn't expose absolute total spend; multiplying by ADM reconstructs it. Aligned with the F-33 'current expenditures' frame used by TX/CA/FL/IL/GA.
- Crosswalk: master `state_leaid` `OH-{6-digit-IRN}` → strip `OH-` → matches Cupp `IRN` directly. Akron `OH-043489` ↔ Cupp `043489`.
- Latest published: FY25 (SY 2024-25) — posted 2026-03-10.
- Coverage: 606 records inserted of 646 master OH operating LEAs (94%; the 40 missing are typically community schools / charter LEAs not covered by the Cupp Report).
- Spot check: Columbus City Schools $1.13B, Cleveland Municipal $811M, Cincinnati Public $698M, Toledo City $440M, Akron City $404M — all match expected scale.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-2`.
- Adopted-budget path NOT covered — Ohio's two-stage process (tax budget by Jan 15, permanent appropriation by Oct 1, county budget commission certification) doesn't produce a single bulk download we identified.

#### NC extractor (2026-05-05) ⚠️ partial topline

NC was the next-biggest unimplemented state at 1.50M enrollment. After ruling out the NCDPI Statistical Profile (Oracle APEX behind Cloudflare challenge), the LGC audit data (per-district PDFs only — no bulk feed), and Open Data NC (no school district financial datasets), settled on NCDPI's **SPSF (State Public School Fund) Excel** — published annually around fall after FY close.

- `extractors/nc.py` pulls `https://www.dpi.nc.gov/documents/fbs/{path}/fy{YYYY}spsfbyleabyprcplainenglish-rptxlsx/download?attachment` (path varies slightly by year). `KNOWN_FILE_URLS` map per FY.
- Topline: aggregated `YTDExpenditures` per LEA across all PRCs from the 'Data Tables' sheet's Key (PRC-LEA) column.
- Crosswalk: master `state_leaid` `NC-{3-digit-LEA}` → strip `NC-` → matches SPSF LEA suffix directly.
- Latest published: FY25 (SY 2024-25). 115 LEAs aggregated, 0 unmatched against master (charters NOT in SPSF — NCDPI tracks them separately).
- Spot check: Wake County $1.21B, Charlotte-Mecklenburg $1.07B, Guilford $520M — about 55-60% of each district's total operating spend (the rest is local appropriation + federal).

⚠️ **TOPLINE LIMITATION:** This is **state-funded only** (~55-60% of total operating). When comparing to TX/CA/FL/IL/GA/OH actuals, NC will appear smaller than its actual size. The full all-funds figure requires LGC per-district audit PDFs — queued as a future Phase 6 follow-up extractor. The `topline_definition` field on every NC record explicitly flags this; verifiers and downstream rollups should respect it.

- Idempotent. Registered in `runner/registry.py` with `fy_offset=-2`.
- Adopted-budget path NOT covered — NC has no centralized adopted-budget feed; per-district per O.C.G.A. equivalent county-commissioner appropriation process.

#### MI extractor (2026-05-05) ✅

MI was the next-biggest unimplemented state at 1.34M enrollment. CEPI's FID (Financial Information Database) requires milogin and isn't programmatically accessible, but MDE publishes the **Bulletin 1011** Excel annually as the public-facing bulk extract of the same underlying AFR (Form SE-4096) data.

- `extractors/mi.py` pulls `https://mdoe.state.mi.us/SAMSPublic/Reports/others/{NN}_Bulletin1011Export.xlsx`. Filename uses 2-digit FY suffix (`25_` for FY25).
- Topline: sum of `TOTCUROPEX` (Total Current Operating Expenditure) across all 5 funds per district. Aligned with F-33 'current expenditures' frame.
- Crosswalk: master `state_leaid` `MI-{5-digit-DCode}` → strip `MI-` → matches Bulletin DCode column directly. Detroit `MI-82015` ↔ Bulletin `82015`.
- Latest published: FY25 (SY 2024-25). 814 districts in Bulletin 1011 (821 total, 7 had $0 TOTCUROPEX); 603 records inserted of 663 master MI operating LEAs (~91%). 211 Bulletin DCodes unmatched against master (charter LEAs / ISD/RESA entities not in our operating-LEA universe).
- Spot check: Detroit Public Schools Community District $1.13B, Dearborn $393M, Utica $383M, Ann Arbor $337M, Grand Rapids $275M — all match expected scale.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-2`.

#### VA extractor (2026-05-05) ✅

VA was the next-biggest unimplemented state at 1.26M enrollment. VDOE's Superintendent's Annual Report (the legacy source) returned 403 from our IP/UA via Akamai — site-blocking. Pivoted to **APA's Comparative Report of Local Government Revenues and Expenditures** which is the public-API-equivalent for cross-locality school finance comparison.

- `extractors/va.py` pulls `https://dlasprodpublic.blob.core.windows.net/apa/{GUID}.xlsx`. APA file URLs use opaque GUIDs that change per FY release; `KNOWN_FILE_URLS` map per FY.
- Topline: Exhibit C col 22 ('Education / Exhibit C-6') — total education expenditures per locality (Instruction + Admin + Pupil Transport + O&M + other education functions).
- Crosswalk: master `state_leaid` `VA-{3-digit-VDOE-code}` doesn't match APA locality names directly. Built name-matching crosswalk: parse master `lea_name` → strip "City Public Schools" / "County Public Schools" → match against APA locality with section disambiguation (city vs county), since "Fairfax" exists as both a city and a county.
- Latest published: FY25 (year ended June 30, 2025).
- Coverage: 101 records inserted of 130 master VA operating LEAs (~78%). 8 unmatched APA localities are mostly **joint city-county school divisions** (Williamsburg-James City County share one division; Covington-Alleghany; Lexington-Rockbridge) where APA reports the locality side but the master uses the joint-division name. 2 are towns (Colonial Beach, West Point). Closing this gap requires a small joint-division override table — queued.
- Spot check: Fairfax County $3.94B, Loudoun $1.95B, Prince William $1.76B, Virginia Beach $1.08B, Chesterfield $982M — all match expected scale.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-2`.

#### WA extractor (2026-05-05) ✅

WA was the next-biggest unimplemented state at 1.08M enrollment. OSPI publishes the **F-196 10-Year Historical Data Detail** Excel annually each December after F-196 reconciliation.

- `extractors/wa.py` pulls `https://ospi.k12.wa.us/sites/default/files/{YYYY-MM}/10_year_f-196_data_{YYYY-YY}.xlsx`. Path includes posting subdirectory; `KNOWN_FILE_URLS` map per FY.
- Topline: `EXP by District` sheet, last year column ('24-25' for FY25) — General Fund total expenditures per district.
- Crosswalk: master `state_leaid` `WA-{5-digit-CCDDD}` (e.g. `WA-17001` Seattle) → strip `WA-` → matches F-196 column B directly.
- Note: WA fiscal year is **Sept 1 – Aug 31** (not July-June like most states), so FY25 = SY 2024-25 ending Aug 31, 2025. F-196 published Dec 2025.
- Latest published: FY25 (10 years of history in one file).
- Coverage: 257 records inserted of 258 master WA operating LEAs (~**99.6%**, the cleanest match rate of any state). 64 unmatched F-196 CCDDDs are charter LEAs / state-tribal compact schools / ESDs not in our operating-LEA universe.
- Spot check: Seattle School District No. 1 $1.14B, Spokane $567M, Tacoma $561M, Lake Washington $544M, Kent $518M — all match expected scale.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-2`.

#### NJ extractor (2026-05-05) ✅

NJ was the next-biggest unimplemented state at 1.05M enrollment. NJDOE publishes the **Taxpayers' Guide to Education Spending (TGES)** annually with one Detail Excel per FY.

- `extractors/nj.py` pulls `https://www.nj.gov/education/guide/docs/{YEAR}/Detail_FY{NN}.xlsx`. The year-after-FY release directory; `KNOWN_FILE_URLS` map per FY.
- Topline: 'Total Spending' column (= general current expense + capital outlay + grants/entitlements + food services + debt service). Aligned with F-33 'total expenditures' frame.
- Crosswalk: master `state_leaid` `NJ-{2-digit-County}{4-digit-District}` (e.g. `NJ-010110` Atlantic City). TGES gives `County` text + `District Code`. Built `NJ_COUNTY_CODES` map (21 counties, alphabetical 01-41 odd-numbered) → `cc + zfill(district_code, 4)` matches master suffix.
- Latest published: FY24 (SY 2023-24) — NJDOE publication lag is ~one year longer than other states.
- Coverage: 231 records inserted of 265 master NJ operating LEAs (~87%). 440 TGES rows unmatched are charter LEAs (separate filing scheme), educational services commissions, county vocational/special services schools — entities that don't appear in master operating-LEA universe.
- Spot check: Newark $1.49B, Elizabeth $909M, Jersey City $906M, Paterson $819M, Trenton $457M — all match expected scale.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-3` (NJ lags one extra year vs the other states).

#### UT extractor (2026-05-05) ✅

UT extractor follows AZ being deferred (AZ Auditor's K-12 spending data is PDF-only and ADE blocks our IP/UA). UT publishes a clean USBE Annual Financial Report Summary Expenditure Excel.

- `extractors/ut.py` pulls `https://www.schools.utah.gov/financialoperations/reporting/reports/annualfinancialreport/{YYYY}fiscalyear/.../AFR%20Summary%20Expenditure%20AF.xlsx`. Path varies slightly by year; `KNOWN_FILE_URLS` map per FY.
- Topline: `Gov Funds Total` sheet, col 38 'Grand Total' — all-funds governmental operating expenditure across 5 functional categories × 8 object subcategories.
- Crosswalk: master `state_leaid` `UT-{NN}` (2-digit zero-padded) for districts; `UT-A{N}` for the 3 charter LEAs in master. AFR uses LeaType + LeaNbr; for `LeaType='District'`, key = `f"{LeaNbr:02d}"` matches master directly.
- Latest published: FY24 (SY 2023-24).
- Coverage: 41 of 41 master UT districts (100%). 15 AFR charters skipped (master only has 3 charter LEAs and the LeaNbr → A-code map isn't built yet — sibling crosswalk TBD).
- **Implementation note:** had to switch from `read_only=True` to non-readonly mode in openpyxl because the AFR sheet has merged cells in header rows that read_only mode doesn't expose consistently.
- Spot check: Davis $1.09B, Alpine $1.07B, Granite $926M, Jordan $739M, Nebo $633M — all match expected scale.
- Idempotent. Registered in `runner/registry.py` with `fy_offset=-3`.

#### AZ extractor (2026-05-05) ⏸️ deferred

Investigated AZ Auditor General + ADE + AZ Open Data; none provide a clean bulk K-12 financial feed accessible from CLI:
- AZ Auditor publishes per-district compliance PDFs only; no bulk Excel/CSV with expenditure detail at any URL pattern tried (multiple slug guesses 404'd).
- ADE finance pages (`azed.gov/finance`, `/budget`) all return 403 from CLI and from WebFetch — Akamai-style block.
- AZ Open Data (`data.az.gov`, `azopendata.az.gov`) not Socrata-domain; no API.
- AZ Auditor's annual "Spending in Arizona's Classrooms" report is PDF-only (per WebFetch).

Same wall as NY. Path forward when revisited: Chrome-MCP automation against the Auditor's Tableau-based K-12 Data Explorer, or FOIA the Auditor for the underlying spreadsheet.

#### CT extractor (2026-05-05) ✅

CT was the first state where we found a clean **adopted-budget** SODA API feed via `data.ct.gov`. The OPM Fiscal Health Monitoring System publishes municipal adopted budgets nearly in real-time, with `date_budget_adopted` recorded for each row.

- `extractors/ct.py` queries `https://data.ct.gov/resource/pcg4-s5rc.json?$where=fiscal_period_of_budget=N` (Socrata SoQL).
- Topline: `education_expenditures` field. For towns with their own school district this is the district's adopted budget; for towns in a regional school district this is the assessment to the regional district.
- Crosswalk: master `state_leaid` `CT-{7-digit}` doesn't map to town name. Built name-matching crosswalk: strip "School District" / "Public Schools" / "Regional School District" suffix from master `lea_name`, uppercase, match against OPM `entity_name`. Excludes regional/cooperative/charter/academy LEAs from the crosswalk since they don't have a 1-town equivalent.
- FY26 (SY 2025-26) data fully published as of 2026-05-05; FY22-FY26 all have ~170 entities each.
- Coverage: 117 records inserted of 122 town/city CT operating LEAs (~96%). 52 unmatched OPM entities are mostly towns belonging to regional districts (their education line is the regional assessment, not the regional district's own budget).
- Spot check: Stamford $352M (adopted 2025-05-22), Hartford $284M (2025-05-21), Bridgeport $246M (2025-05-19), Norwalk $243M, Fairfield $233M.
- Idempotent. Registered with `kind=budget, fy_offset=0` (data updates near-real-time).

#### TN extractor (2026-05-05) ✅

TN publishes the Annual Statistical Report (ASR) annually per Tenn. Code Ann. § 49-1-211. The 2024-25 ASR was published Feb 2026 as a single ZIP with 50+ Excel tables; Table 51 has per-district current expenditures.

- `extractors/tn.py` pulls `https://www.tn.gov/content/dam/tn/education/documents/asr/2024-25_ASR_Excel.zip` (URL pattern requires per-FY entry in `KNOWN_FILE_URLS`).
- Topline: Table 51 col 3 `TOTAL OPERATING EXPENDITURES` per district (audited current expenditures — instruction + student services + admin + plant O&M + other current; aligned with F-33 frame).
- Crosswalk: master `state_leaid` `TN-{5-digit}` → zero-pad ASR Table 51 col 0 (3-digit district code) to 5 digits.
- Coverage: 127 of 129 master TN operating LEAs (~98%).
- Idempotent. Registered with `kind=actuals, fy_offset=-2` (FY27 calendar runs trigger the FY25 fetch).

#### MO scoping notes (2026-05-05) ⏸️ deferred

MO was the next-biggest unimplemented state at ~870k enrollment. DESE (Dept. of Elementary and Secondary Education) collects per-district financial data via the Annual Secretary of the Board Report (ASBR) under § 162.821 RSMo, due Aug 15 each year. Findings:

- **DESE ASBR PublicView** (`apps.dese.mo.gov/ASBR/PublicView.aspx`) — public (no login), but ASP.NET WebForms with `__doPostBack` for district selection AND for each report (ASBR Report, Per-Pupil Building Level Expenditures, Indirect Cost Calc, Local Effort, etc.). Reports rendered server-side via SSRS-style ReportViewer. **No bulk download / Export-to-Excel / CSV button visible.** Data is per-district × per-FY, requires VIEWSTATE postback automation against ~520 districts.
- **DESE main MCDS** (`apps.dese.mo.gov/MCDS/`) — all paths redirect to `/WebLogin/Login.aspx` (login-only). QuickFacts, PublicReports, SchoolFinance — same wall.
- **DESE School Finance / Data & Reports** (`dese.mo.gov/financial-admin-services/school-finance/data-reports-0` and `/financial-reports`) — landing pages of state-aid summaries (PDFs of Local Effort, Transportation Transfer, etc.); no per-district expenditure bulk file.
- **`dese.mo.gov/school-data`** — navigation hub only; no bulk finance CSV.
- **Socrata `data.mo.gov`** — 0 datasets matching "school expenditure" or similar.

**Decision (2026-05-05):** Defer MO extractor. Same wall as NY / AZ — public per-district data, no bulk feed. Path forward when revisited: (a) Chrome-MCP automation against ASBR PublicView with 500+ postback iterations, (b) FOIA / direct request to DESE School Finance (`finadmgov@dese.mo.gov`) for the per-district ASBR bulk Excel, or (c) ASP.NET VIEWSTATE scraper that cycles district codes from the public dropdown and parses the rendered SSRS HTML. Captured as Phase 6 follow-up; not blocking.

#### MN scoping notes (2026-05-05) ⏸️ deferred

MN was the next-biggest unimplemented state at ~840k enrollment. MDE collects per-district financial data via UFARS (Uniform Financial Accounting and Reporting Standards). Findings:

- **MDE Analytics MFR** (`pub.education.mn.gov/MDEAnalytics/DataTopic.jsp?TOPICID=9`, "Minnesota Funding Reports") and **Financial Profiles** (TOPICID=42) — both behind Perfdrive (Radware) bot/captcha protection. Plain GET → captcha redirect. Same wall on `public.education.mn.gov` mirror (SSL cert issue + 404 on `mass.gov`-style retry).
- **MDE Report Card** (`rc.education.mn.gov`) — JS app (RequireJS); "How is money spent?" tile is interactive only; no static dataset URL exposed.
- **`/mdeprod/idcplg?dDocName=005481` ("District Revenues and Expenditures Budget for FY2025 and FY2026")** — looks promising in the search but is a **blank publication template** (Form ED-00110-48); districts fill it in and post to their own websites under § 123B.10. No aggregated MN-wide file.
- **UFARS File Upload** — submission endpoint only (EDIAM-authenticated).

**Decision (2026-05-05):** Defer MN extractor. Same wall as NY / AZ / MO — bulk data is gated behind interactive analytics tools with bot protection, and the only static publication is the blank form template. Path forward when revisited: (a) Chrome-MCP automation through Perfdrive captcha against MFR/Financial Profiles, (b) FOIA / direct request to MDE Financial Management (`mde.ufars-accounting@state.mn.us`) for the UFARS bulk extract, or (c) per-district scrape of the publication forms posted on each district's website (§ 123B.10 mandate). Captured as Phase 6 follow-up; not blocking.

#### TN extractor (2026-05-05) ✅

TN publishes the Annual Statistical Report (ASR) annually per Tenn. Code Ann. § 49-1-211. The 2024-25 ASR was published Feb 2026 as a single ZIP with 50+ Excel tables; Table 51 has per-district current expenditures.

- `extractors/tn.py` pulls `https://www.tn.gov/content/dam/tn/education/documents/asr/2024-25_ASR_Excel.zip` (URL pattern requires per-FY entry in `KNOWN_FILE_URLS`).
- Topline: Table 51 col 3 `TOTAL OPERATING EXPENDITURES` per district (audited current expenditures — instruction + student services + admin + plant O&M + other current; aligned with F-33 frame).
- Crosswalk: master `state_leaid` `TN-{5-digit}` → zero-pad ASR Table 51 col 0 (3-digit district code) to 5 digits.
- Coverage: 127 of 129 master TN operating LEAs (~98%).
- Idempotent. Registered with `kind=actuals, fy_offset=-2` (FY27 calendar runs trigger the FY25 fetch).

#### MA extractor (2026-05-05) ✅

MA DESE Profiles publishes a statewide Per-Pupil Expenditures (PPX) view that embeds the entire all-district table directly in the HTML response — no postback or login required for the latest balanced FY.

- `extractors/ma.py` GETs `https://profiles.doe.mass.edu/statereport/ppx.aspx`, parses `<table id='tblPerPupilExpenditure'>`, and reads the `Total Expenditures` column.
- Topline: `Total Expenditures` per district (all funds — in-district + out-of-district + school-choice + educational-collaborative). EOYR-derived; aligned with F-33 'current expenditures' frame.
- Crosswalk: master `state_leaid` `MA-{4-digit}` → first 4 digits of DESE 8-digit `district_code` (e.g. `00010000` → `MA-0001` Abington).
- Latest FY served: FY24 (SY 2023-24); page detects selected FY automatically. The plain GET only returns the latest balanced FY; switching FYs requires a __VIEWSTATE POST. Captured `page_fy` overrides the requested fiscal_year if the page has rolled over.
- Coverage: 228 of 228 master MA operating LEAs (100%). 168 unmatched DESE codes are sub-orgs (out-of-district / collaborative / charter-network / Chapter-766) not in our operating-LEA universe.
- Spot check: Boston $2.04B, Springfield $749M, Worcester $620M, Lynn $417M, Lowell $378M — match public reporting.
- Idempotent. Registered with `kind=actuals, fy_offset=-3` (FY27 calendar maps to FY24 file in hand; will auto-flip when FY25 PPX publishes after Dec 2025 EOYR audit cycle).

#### CO scoping notes (2026-05-05) ⏸️ deferred

CO was the next-biggest unimplemented state at ~865k enrollment. CDE Public School Finance Unit publishes a clean Financial Transparency district-level Excel under HB14-1292 — URL pattern is direct (`https://www.cde.state.co.us/cdefinance/ft_fy{NNNN}_distdatafile`) and the file structure was inspected and is excellent (sheet `Org_Spending_Funding`, sum AMOUNT where SPENDING_FUNDING='Spending' and ORG_ROLLUP in ('Learning Environment','Operations') gives a clean F-33-aligned topline). Latest published is FY24 (~$13.9B statewide); FY25 publishes July 1, 2026.

**Decision (2026-05-05):** Defer CO extractor. **Different wall pattern:** unlike NY / AZ / MO / MN where the underlying data is gated behind login walls or interactive analytics tools, **CDE rate-limited our source IP** mid-investigation and stopped accepting connections to `www.cde.state.co.us:443` from this network. The data path itself is clean and the parsing logic is verified against the FY24 file. Path forward when revisited: (a) re-run from a different network or via a residential-IP proxy, (b) wait for the rate-limit window to clear (likely several hours to a day), (c) email CDE School Finance to request whitelisting, or (d) re-attempt with conservative request pacing. No code shipped to the repo; will rebuild from these notes when un-deferred.

---

## 7. Conventions

### Adding a state extractor

Every state extractor lives in `extractors/{state_postal}.py` and exports a single `extract(fiscal_year: int, run_id: UUID) -> dict` function.

Required structure:
1. Identify the source — preferably a centralized SEA download. Document the URL and refresh cadence at the top of the file.
2. Build a state-leaid → NCES leaid crosswalk. Use the `state_leaid` field already in `districts`.
3. For each district found in the source, fetch the source document, hash it, store it.
4. Insert/upsert `source_documents` row.
5. Determine status (`adopted` if from a finalized budget portal; `proposed` if from preliminary submissions; `actual` if from audited reports).
6. Compute YoY against `prior_year_baseline` from `budget_events` where `fiscal_year=YYYY-1, is_superseded=false`.
7. Insert `budget_events` row with all fields set, including `topline_definition` describing exactly what was summed.
8. Return summary dict for the runner.

Do not commit raw source files (PDFs, Excel) to Git. They go to Supabase Storage; only the path is in Postgres.

### Source document handling

- Always store the original byte stream, never a re-rendered version.
- Hash before processing so we detect upstream changes.
- For PDFs, store the page number where the figure appears. The verifier needs to be able to open the PDF, jump to that page, and see the number.
- For Excel/CSV, store enough of a reference (`Row 47, column G` or `sheet="DATAMART", row 1234`) that a verifier can find it without searching.

### Migration discipline

- Every schema change is a numbered SQL file in `migrations/`, applied via Supabase MCP.
- Never edit a migration after it's been applied to production. Add a new one.
- If you need to rename a column, do: add new → backfill → switch reads → drop old, across multiple migrations.

### Failure modes

State portals will change URLs, formats, or take data down. Extractors will break. Plan for it:

- An extractor that errors should log to `extraction_runs` with `status='failed'` and a useful `error_summary`. Don't silently swallow errors.
- After two consecutive failures, the extractor is "broken." The daily report should flag this. Don't auto-disable; require human intervention.
- Don't delete old `budget_events` when an extractor breaks. The data we already have remains valid.

### Code style

- Python 3.11+. Use type hints on public functions.
- Format with ruff. CI fails on unformatted code.
- Tests for non-trivial parsing logic. PDF parsing especially — check in a sample document and assert the extracted number.
- Don't add libraries casually; each new dep is a maintenance cost.

---

## 8. Open questions / decisions deferred

These have not been decided. Flag to the user before resolving silently.

- **Charter LEA handling.** Some states' charter LEAs file separately from authorizing districts; some roll up. Consistent treatment across states needs a policy decision.
- **What counts as "adopted" in multi-stage states.** California has a tentative-then-final adoption sequence; some states have a county oversight review that can disapprove. Do we record the final-final, or each stage as separate events? (Recommend: each stage as separate events; user confirms.)
- **Locked vs live data.** Once verified, should records be immutable? Or can a re-extraction supersede a verified record? (Recommend: re-extraction creates a new event; verifier must re-verify; the prior verification stays in `verification_log`.)
- **Reporting format.** Eventual published artifact — interactive dashboard, static report, API? Defer until Phase 5 is solid.
- **Backfill strategy for FY26.** Do we attempt to capture FY26 adopted budgets retrospectively? Or accept that FY27 is the first cohort? (Recommend: FY27 only for the first year; FY26 only if a state's data falls into our lap.)

---

## 9. How to use this document

At the start of every session, Claude Code should:

1. Read this file (`PLAN.md`) to load context.
2. Read `CLAUDE.md` (a short pointer file in the repo root) for any session-specific instructions.
3. Identify the current phase and the next unchecked task.
4. Confirm with the user before starting a new phase or making a non-trivial architectural change.

If something in this document is wrong or out of date, fix it as part of the work. Don't work around stale documentation.
