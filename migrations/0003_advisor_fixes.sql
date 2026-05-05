-- 0003_advisor_fixes.sql
-- Address Supabase advisor findings from 0001/0002:
--   ERROR  budget_events_current view is SECURITY DEFINER (default in PG15+)
--   WARN   trigger functions have mutable search_path
--   WARN   is_verifier() is exposed as a public RPC
--   INFO   FK columns on budget_events lack covering indexes

-- ---------------------------------------------------------------------------
-- 1. Recreate budget_events_current as SECURITY INVOKER
-- ---------------------------------------------------------------------------

drop view if exists budget_events_current;

create view budget_events_current
with (security_invoker = true)
as
select *
from budget_events
where is_superseded = false;

comment on view budget_events_current is
  'Convenience view returning only non-superseded events. Primary read path.';

-- ---------------------------------------------------------------------------
-- 2. Pin search_path on every plpgsql/sql helper function we own
-- ---------------------------------------------------------------------------

create or replace function set_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function reject_mutation()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  raise exception 'verification_log is append-only';
end;
$$;

create or replace function guard_budget_events_verifier_update()
returns trigger
language plpgsql
set search_path = public, pg_temp
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

-- ---------------------------------------------------------------------------
-- 3. is_verifier() should not be callable via REST RPC
-- ---------------------------------------------------------------------------

revoke execute on function public.is_verifier() from public, anon, authenticated;
-- Policies still see it because RLS evaluates with the table-owner's privileges.

-- ---------------------------------------------------------------------------
-- 4. Cover the two budget_events FKs with indexes
-- ---------------------------------------------------------------------------

create index if not exists budget_events_source_document_id_idx
  on budget_events (source_document_id);

create index if not exists budget_events_extraction_run_id_idx
  on budget_events (extraction_run_id);
