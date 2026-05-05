# Verifier Guide

This document is for the human reviewers who verify that extractor-produced budget records match the underlying source documents. No SQL knowledge is required. Most of the work happens in the Supabase Studio table editor at https://supabase.com/dashboard/project/bwkgcofsxubdofklpsaw.

## What you're checking

For each `budget_events` row, you verify three things by opening the source document:

1. **The dollar amount is correct** — `topline_amount` matches what the source PDF / Excel / spreadsheet shows for the relevant section.
2. **The status is correct** — `status` is one of `proposed | tentative | adopted | disapproved | actual` and matches what the document represents (e.g. an "Annual Financial Report" is `actual`, a "Summary Budget" submitted to the state is `adopted`).
3. **The fiscal year is correct** — `fiscal_year` is the year the budget covers (= ending year of the school year; FY27 = SY 2026-27).

If all three match, you mark it **verified**. If any of them is wrong, you mark it **flagged** (or **disputed** if you're sure it's wrong).

You do **not** need to verify documents that are clearly the canonical source from the state education agency for a known good extractor — your time is best spent on edge cases. The work queue (below) is already filtered to the highest-leverage records.

## Setup (one time)

1. Sign in to https://supabase.com with the email the project lead has invited.
2. Go to the project: **school-budget-tracker**.
3. In the left nav: **Table Editor**. You'll see the schema.

## Your work queue

In the SQL Editor, run:

```sql
select * from unverified_events_high_priority;
```

This view returns up to 200 records: events for **fiscal_year=2027** on the **largest 200 districts by enrollment**, where `verification_status='unverified'` and the row is still current (not superseded by a later extraction). Oldest first — chip away from the top.

If the view is empty, there's nothing to do — extractors haven't produced new FY27 records yet, or someone else has cleared the backlog.

## Per-record workflow

For each row in your queue, open it (click the row in Table Editor):

### 1. Open the source document

The row's source document lives in Supabase Storage. The path is in the `storage_path` column (e.g. `fl/fy2026/DadeTotalBUD2526.pdf`). To open it:

- Go to **Storage** in the left nav
- Find the bucket (`fl`, `tx`, `ca`)
- Navigate to the path
- Click the file → "Get URL" → open in a new tab

If `storage_path` is null but `source_url` is populated, just open `source_url` directly.

### 2. Find the topline value in the document

The `line_or_cell_reference` column on the source document tells you where to look. Common patterns:

- **PDFs** — `page_number` is the 1-indexed page; the reference describes the section ("Section II. GENERAL FUND 100, TOTAL APPROPRIATIONS row, first amount column"). Open the PDF, jump to that page, find the row.
- **Excel files** — the reference describes the sheet and filtering ("Sheet=DATAMART, filter DISTRICT NUMBER == state_leaid suffix"). Open Excel, filter, find the cell.

The value you see should match `topline_amount` exactly (within a few dollars; rounding is fine).

### 3. Decide and act

In the Table Editor row for the event, edit only the four verification fields:

- `verification_status` — set to one of:
  - `verified` — value, status, and fiscal_year all match the document
  - `flagged` — at least one is wrong or you're not confident; needs a second look
  - `disputed` — you're confident the extractor produced the wrong value
- `verified_by` — your identifier (email handle is fine, e.g. `i.f.pentchoukov`)
- `verified_at` — timestamp; Studio fills this if you set "now()"
- `verification_notes` — a sentence about what you checked. Required if you're flagging or disputing.

**Do not** edit any other field. The schema enforces this — the database trigger `guard_budget_events_verifier_update` will reject the change with the error: *"verifier may update verification_status / verified_by / verified_at / verification_notes only."* That's working as intended. Use the verification_notes field to record what you found wrong; the project lead will trigger a re-extraction.

### 4. (Optional) Add a verification_log entry

If you want to leave an audit-trail comment that's separate from the event row itself, insert a row into `verification_log`:

| field | value |
|---|---|
| `budget_event_id` | UUID of the event you just verified |
| `actor` | your identifier |
| `action` | one of `verified | flagged | disputed | unflagged | note_added` |
| `previous_status` / `new_status` | the verification_status before/after your change |
| `notes` | freeform — link to the relevant page, your reasoning, etc. |

This is append-only — once inserted, you cannot edit or delete (the database enforces this).

## Spot-check queue (for the project lead)

To see what verifiers have been doing in the past 14 days:

```sql
select * from verifications_pending_review;
```

This view joins `verification_log` to the events that were touched, with the source document fields. Useful for catching a drift in verifier judgment or auditing a specific actor's work.

## Common scenarios

**Q: The source PDF has multiple "TOTAL EXPENDITURES" rows. Which one is the topline?**

A: The `line_or_cell_reference` field describes the exact one. For FL AFRs, it's "Statement of Revenues, Expenditures and Changes in Fund Balance — General Fund 100, TOTAL EXPENDITURES 0000 row" — that exact row, on the page indicated by `page_number`. If more than one matches, open the project lead's #budget-tracker channel and ask.

**Q: The FY25 actuals on FLDOE has been re-published with a corrected number. The DB has the old number. Now what?**

A: Don't edit the row. The extractor will pick up the new file on its next daily run, hash it, see the hash differs, and supersede the old row with a new one (`is_superseded=true` on the old, fresh row inserted). Both rows stay in history. Your verification of the old row is still valid — the prior verification_log entry preserves what you checked.

**Q: A district doesn't appear in the queue but I know they adopted their FY27 budget.**

A: Either (a) we don't have an extractor for that state yet, or (b) the extractor ran but didn't find the file. Check the `extraction_runs` table for the most recent run of the state's extractor. If the run has `status='success'` but didn't pick up the district, the district's source file likely has a different URL / format from the rest. Tell the project lead.

**Q: I'm not sure if a record is `proposed` vs `tentative` vs `adopted`.**

A: Default to flagging it (`verification_status='flagged'`, with a note explaining why). The project lead has a policy decision (see PLAN.md §8) about how multi-stage adoption sequences should be encoded. When in doubt, surface it.
