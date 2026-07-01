> # 🛑 PROJECT DECOMMISSIONED — 2026-07-01
>
> This project was **permanently retired** on 2026-07-01. The Supabase project
> (`bwkgcofsxubdofklpsaw`) and the Vercel portal (`school-spending-web`) have
> been **deleted**; the daily GitHub Actions cron is disabled and the DB webhook
> triggers are dropped. **Do not run extractors, the runner, or migrations, and
> do not recreate the infrastructure** without explicit user sign-off.
>
> A complete, integrity-verified archive (DB schema + data, all 614 Storage
> source documents, git bundles of both repos) is at
> `~/school_spending_archive_2026-07-01/` — see its `MANIFEST.md`.
>
> The operating instructions below are retained for historical reference only.

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
