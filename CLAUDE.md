# Operating Instructions for Claude Code

Read `PLAN.md` before starting any work in this repo. It is the source of truth for architecture, data model, phases of work, and conventions.

Before each session:
1. Identify the current phase from PLAN.md §6.
2. Identify the next unchecked task in that phase.
3. Briefly confirm the plan with the user before executing — especially before starting a new phase, adding a new dependency, or changing the schema.

When in doubt, fix `PLAN.md` first, then the code. Don't silently diverge.

Use the Supabase MCP for all database operations. Don't hand-write connection strings or use psql directly. Don't disable RLS as a shortcut.

Don't commit raw source documents (PDFs, Excel files) to Git. They belong in Supabase Storage.

`docs/STATUS.md` is the running state-by-state snapshot (live / deferred / next-up / open follow-ups, with FY, coverage %, topline $, and source). Update it whenever an extractor lands, a state is deferred, or a follow-up closes — same commit as the underlying change. Keep counts and topline sums fresh by querying `budget_events` against current `is_superseded=false` rows; bump `_Last updated:_` to today's date.
