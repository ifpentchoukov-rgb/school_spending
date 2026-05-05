# Migrations

Numbered SQL migrations for the Supabase Postgres schema. Apply via the Supabase MCP `apply_migration` tool — do not hand-run them with `psql`.

## Conventions

- Files are named `NNNN_short_snake_case_description.sql` (zero-padded, monotonically increasing).
- One logical change per file.
- Once applied to the live project, **never edit a migration**. Add a new one. To rename a column: add new → backfill → switch reads → drop old, across multiple migrations.
- Every migration should be idempotent-safe where possible (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, etc.) so re-running is harmless.

## Why placeholder

Phase 0 (PLAN.md §6) only requires the directory to exist. The first real migration lands in Phase 1 (`0001_core_schema.sql`).
