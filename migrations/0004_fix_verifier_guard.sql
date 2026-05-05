-- 0004_fix_verifier_guard.sql
-- Fix the service_role bypass in guard_budget_events_verifier_update.
--
-- The original (0002/0003) used `current_setting('request.jwt.claim.role', true)`
-- — a pre-PostgREST-v10 setting that no longer exists. As a result every
-- service_role UPDATE on budget_events triggered the verifier guard, blocking
-- the supersession path used by extractors.
--
-- The correct check is `auth.role()`, which Supabase exposes precisely for this.

create or replace function guard_budget_events_verifier_update()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  if auth.role() = 'service_role' then
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
