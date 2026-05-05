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

### Phase 2 — Calendar research + seed

This phase is mostly research. Do it state-by-state. Don't try to bulk-research all 50 states in one pass.

- [ ] For each state, identify the statutory budget adoption deadline. Seed a `state_calendars` row.
- [ ] Identify the *publication* venue for FY27 budgets — is it a centralized SEA portal, a county portal, district websites, board minutes? Note in the row.
- [ ] Identify the *earliest* date FY27 data is expected to appear in that venue.
- [ ] Cite the statute or administrative regulation.

Sources to check (incomplete):
- For most states: Education Commission of the States policy database; SEA "financial reports" page; state legislative code.
- For known-good starting points: CA Educ. Code § 42127 (July 1 budget adoption); TX Educ. Code § 44.004 (Aug 25 deadline for Sept-Aug FY); FL § 1011.03 (Sept 30 finalization); NY EDU § 1716.

Aim for 10 states per session. The full table can take a week of part-time work.

**Acceptance:** at least 15 of the largest-enrollment states have calendar rows with cited statutes. Document in the row's `notes` field anything ambiguous.

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

- [ ] Build `runner/daily.py` that reads `state_calendars`, picks active states, dispatches extractors
- [ ] Wire to GitHub Actions cron at 06:00 UTC
- [ ] Add a daily summary report generator (markdown output as a GitHub Actions artifact)
- [ ] Add basic monitoring: any extractor in `failed` state for two consecutive runs should emit a GitHub Issue automatically (use the `gh` CLI or actions/github-script)

**Acceptance:** workflow runs on schedule, produces a summary, has run successfully for 3 consecutive days without intervention.

### Phase 5 — Verification workflow

- [ ] Create a Supabase Studio "saved query" or view: `unverified_events_high_priority` — events from the largest 200 districts, fiscal_year=2027, where verification_status='unverified', oldest first
- [ ] Document the verifier workflow in `docs/VERIFIER_GUIDE.md`: how to log into Studio, what each field means, how to add a verification row, what counts as "verified" vs "flagged"
- [ ] Create a `verifications_pending_review` view for the user to spot-check verifier work
- [ ] Confirm RLS policies allow verifiers to update `verification_status` but not `topline_amount` or `source_document_id`

**Acceptance:** a non-developer team member can log into Supabase Studio, find an unverified record, view the source document, and mark it verified — without writing any SQL.

### Phase 6 — Add new state extractors (ongoing)

In priority order based on enrollment coverage and tier:

1. NY (1,119 LEAs but ~690 operating; NYSED ST-3 + Comptroller data)
2. IL (1,032 LEAs; ISBE Annual Financial Report)
3. PA (~545 districts; PDE AFR)
4. OH (~646 districts; ODE District Profile + Auditor of State)
5. NJ (~700 LEAs; NJDOE Taxpayers Guide + UEZ)
6. ... continue per the tier table in `legacy/sd_tracker_step1/state_tiers.py`

For each new state extractor, follow the **"adding a state" template** in §7.

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
