-- 0002_rls_policies.sql
-- Phase 1: row-level security per PLAN.md §4.
--
-- Roles:
--   anon          — unauthenticated readers; can read `districts` only.
--   authenticated — verifier-eligible; can read everything; can update
--                   verification fields on `budget_events`; can insert into
--                   `verification_log`.
--   service_role  — bypasses RLS entirely (used by extractors and seed scripts).
--
-- "Verifier" promotion lives in JWT app_metadata. Until that's set, every
-- authenticated user is treated as a verifier — fine for Phase 1 (single
-- known operator). Tighten in a later migration when the verifier pool grows.

-- ---------------------------------------------------------------------------
-- helper: is_verifier()
-- ---------------------------------------------------------------------------

create or replace function public.is_verifier()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select auth.role() = 'authenticated';
$$;

comment on function public.is_verifier() is
  'True for any authenticated user. Tighten later by checking JWT app_metadata.';

-- ---------------------------------------------------------------------------
-- enable RLS on every public table
-- ---------------------------------------------------------------------------

alter table districts        enable row level security;
alter table state_calendars  enable row level security;
alter table source_documents enable row level security;
alter table extraction_runs  enable row level security;
alter table budget_events    enable row level security;
alter table verification_log enable row level security;

-- ---------------------------------------------------------------------------
-- districts: anon + authenticated read; no client writes (service role only).
-- ---------------------------------------------------------------------------

create policy districts_read_all
  on districts for select
  to anon, authenticated
  using (true);

-- ---------------------------------------------------------------------------
-- state_calendars: authenticated read only.
-- ---------------------------------------------------------------------------

create policy state_calendars_read_authed
  on state_calendars for select
  to authenticated
  using (true);

-- ---------------------------------------------------------------------------
-- source_documents: authenticated read only.
-- ---------------------------------------------------------------------------

create policy source_documents_read_authed
  on source_documents for select
  to authenticated
  using (true);

-- ---------------------------------------------------------------------------
-- extraction_runs: authenticated read only.
-- ---------------------------------------------------------------------------

create policy extraction_runs_read_authed
  on extraction_runs for select
  to authenticated
  using (true);

-- ---------------------------------------------------------------------------
-- budget_events: authenticated read; verifiers may update verification fields.
-- ---------------------------------------------------------------------------

create policy budget_events_read_authed
  on budget_events for select
  to authenticated
  using (true);

create policy budget_events_verifier_update
  on budget_events for update
  to authenticated
  using (is_verifier())
  with check (is_verifier());

-- Column-level protection: when a non-service_role user updates budget_events,
-- only the four verification columns may change. Topline / source / status etc.
-- are immutable from the client. service_role bypasses RLS so this is moot for
-- extractors.
create or replace function public.guard_budget_events_verifier_update()
returns trigger
language plpgsql
as $$
begin
  if (select current_setting('request.jwt.claim.role', true)) = 'service_role' then
    return new;
  end if;
  if new.leaid is distinct from old.leaid
     or new.fiscal_year is distinct from old.fiscal_year
     or new.status is distinct from old.status
     or new.topline_amount is distinct from old.topline_amount
     or new.topline_definition is distinct from old.topline_definition
     or new.yoy_change_pct is distinct from old.yoy_change_pct
     or new.yoy_change_dollars is distinct from old.yoy_change_dollars
     or new.prior_year_baseline is distinct from old.prior_year_baseline
     or new.event_date is distinct from old.event_date
     or new.source_document_id is distinct from old.source_document_id
     or new.extraction_run_id is distinct from old.extraction_run_id
     or new.is_superseded is distinct from old.is_superseded
     or new.created_at is distinct from old.created_at
  then
    raise exception 'verifier may update verification_status / verified_by / verified_at / verification_notes only';
  end if;
  return new;
end;
$$;

create trigger budget_events_guard_verifier_update
before update on budget_events
for each row execute function guard_budget_events_verifier_update();

-- ---------------------------------------------------------------------------
-- verification_log: authenticated read; verifiers may insert.
-- (UPDATE/DELETE already blocked by reject_mutation triggers from 0001.)
-- ---------------------------------------------------------------------------

create policy verification_log_read_authed
  on verification_log for select
  to authenticated
  using (true);

create policy verification_log_verifier_insert
  on verification_log for insert
  to authenticated
  with check (is_verifier() and actor is not null);
