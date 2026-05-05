# Seeds

One-shot scripts that load reference data into Supabase via supabase-py.
Idempotent: re-running upserts (no duplicates).

## Layout

- `_client.py` — Supabase client factory; loads `.env.local`.
- `seed_districts.py` — loads `legacy/sd_tracker_step1/processed/master_districts.csv` into `districts` (operating only, ~11,880 rows).
- `seed_legacy_actuals.py` — loads `legacy/sd_tracker_step2/processed/state_extractions.csv` into `budget_events` as FY25 `actual` records, with one synthetic `source_documents` row per state (TX/CA/FL).

## Running

```bash
.venv/bin/python -m seeds.seed_districts
.venv/bin/python -m seeds.seed_legacy_actuals
```

Both scripts read `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from
`.env.local` (see `.env.example`). The service-role key bypasses RLS, so
seeds work regardless of the policies set in `migrations/0002_rls_policies.sql`.
