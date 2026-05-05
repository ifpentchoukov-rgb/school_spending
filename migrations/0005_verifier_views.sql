-- 0005_verifier_views.sql
-- Phase 5: helper views the verifier UI uses (Supabase Studio table editor).
--
-- Both views are SECURITY INVOKER so RLS evaluates against the calling user's
-- permissions, not the view-owner's. With our policies:
--   - anon              → empty results (no RLS for budget_events)
--   - authenticated     → sees everything in scope (per Phase 1 RLS)
--   - service_role      → bypasses RLS

-- ---------------------------------------------------------------------------
-- unverified_events_high_priority
-- Events for fiscal_year=2027 (the FY27 budget tracking target) on the
-- top-200 largest districts by enrollment, that are unverified and current
-- (not superseded). Oldest first so verifiers chip away at the backlog.
-- ---------------------------------------------------------------------------

drop view if exists unverified_events_high_priority;

create view unverified_events_high_priority
with (security_invoker = true)
as
with top_districts as (
  select leaid
  from districts
  where is_operating_district = true
    and enrollment_fy25 is not null
  order by enrollment_fy25 desc
  limit 200
)
select
  d.lea_name,
  d.state_postal,
  d.enrollment_fy25,
  be.id          as event_id,
  be.fiscal_year,
  be.status,
  be.topline_amount,
  be.yoy_change_pct,
  be.event_date,
  sd.publisher,
  sd.source_url,
  sd.storage_path,
  sd.page_number,
  sd.line_or_cell_reference,
  be.verification_status,
  be.created_at  as event_created_at
from budget_events be
join districts d           on d.leaid = be.leaid
join source_documents sd   on sd.id   = be.source_document_id
where be.fiscal_year = 2027
  and be.verification_status = 'unverified'
  and be.is_superseded = false
  and d.leaid in (select leaid from top_districts)
order by be.created_at;

comment on view unverified_events_high_priority is
  'Top-200-enrollment districts with unverified FY27 events. Verifier work queue.';

-- ---------------------------------------------------------------------------
-- verifications_pending_review
-- Recent verifier actions (last 14 days) — for the user to spot-check the
-- verifier team's work. Joins verification_log → budget_events → districts.
-- ---------------------------------------------------------------------------

drop view if exists verifications_pending_review;

create view verifications_pending_review
with (security_invoker = true)
as
select
  vl.created_at  as action_at,
  vl.actor,
  vl.action,
  vl.previous_status,
  vl.new_status,
  vl.notes       as actor_notes,
  d.lea_name,
  d.state_postal,
  d.enrollment_fy25,
  be.id          as event_id,
  be.fiscal_year,
  be.status,
  be.topline_amount,
  be.verification_status,
  sd.publisher,
  sd.source_url,
  sd.storage_path,
  sd.page_number
from verification_log vl
join budget_events be     on be.id   = vl.budget_event_id
join districts d          on d.leaid = be.leaid
join source_documents sd  on sd.id   = be.source_document_id
where vl.created_at > now() - interval '14 days'
order by vl.created_at desc;

comment on view verifications_pending_review is
  'Verifier actions in the past 14 days — spot-check queue for the project lead.';
