-- 0007_widen_verifier_queue.sql
-- Drops the fiscal_year=2027 filter on unverified_events_high_priority.
--
-- The view was originally scoped to FY27 because that's the project's
-- primary tracking target. But during the transition period — before any
-- FY27 events land (expected fall 2026) — the queue would always be empty.
-- Widen to "any unverified, non-superseded event on a top-200 district".
-- Verifiers can still filter by fiscal_year in Studio if they want a
-- specific year.

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
where be.verification_status = 'unverified'
  and be.is_superseded = false
  and d.leaid in (select leaid from top_districts)
order by be.fiscal_year desc, be.created_at;

comment on view unverified_events_high_priority is
  'Top-200-enrollment districts × any unverified non-superseded events. '
  'Most recent fiscal year first. Verifier work queue.';
