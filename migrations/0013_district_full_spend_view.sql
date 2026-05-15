-- Phase 8.4 — v_district_full_spend view
--
-- Per (member_leaid, fiscal_year, status) row: district's own non-superseded
-- topline + the sum of (cooperative's topline × allocation_share) across
-- every cooperative the member belongs to in that fiscal_year.
--
-- Works with an empty cooperative_membership table — allocated_cooperative_
-- spend is then 0 and total_full_spend == own_spend. Phase 8.2 (NY BOCES)
-- and Phase 8.3 (NJ ESC / RI / CT regional) populate the join table; this
-- view starts returning non-zero allocations automatically.

CREATE OR REPLACE VIEW public.v_district_full_spend AS
WITH coop_allocations AS (
  SELECT
    cm.member_leaid                                 AS leaid,
    coop_be.fiscal_year,
    coop_be.status,
    SUM(coop_be.topline_amount * COALESCE(cm.allocation_share, 0))
                                                    AS allocated_amount,
    COUNT(*)                                        AS cooperative_count
  FROM public.cooperative_membership cm
  JOIN public.budget_events coop_be
    ON coop_be.leaid = cm.cooperative_leaid
    AND coop_be.fiscal_year = cm.fiscal_year
    AND coop_be.is_superseded = false
  GROUP BY cm.member_leaid, coop_be.fiscal_year, coop_be.status
)
SELECT
  be.id                       AS budget_event_id,
  be.leaid,
  d.lea_name,
  d.state_postal,
  d.entity_type,
  d.enrollment_fy25,
  be.fiscal_year,
  be.status,
  be.topline_amount           AS own_spend,
  COALESCE(ca.allocated_amount, 0) AS allocated_cooperative_spend,
  be.topline_amount + COALESCE(ca.allocated_amount, 0) AS total_full_spend,
  COALESCE(ca.cooperative_count, 0) AS cooperative_count,
  (be.topline_amount + COALESCE(ca.allocated_amount, 0))
    / NULLIF(d.enrollment_fy25, 0) AS full_spend_per_pupil
FROM public.budget_events be
JOIN public.districts d USING (leaid)
LEFT JOIN coop_allocations ca
  ON ca.leaid = be.leaid
  AND ca.fiscal_year = be.fiscal_year
  AND ca.status = be.status
WHERE be.is_superseded = false
  AND d.entity_type = 'district';

COMMENT ON VIEW public.v_district_full_spend IS
  'Phase 8.4 — per-district "true" spend = own non-superseded topline + '
  'sum of (cooperative_topline × allocation_share) across cooperatives '
  'the district belongs to in the same fiscal_year. Returns one row per '
  '(district, fiscal_year, status). Cooperatives themselves are filtered '
  'out (entity_type = ''district''). Works with empty cooperative_membership '
  '(allocated = 0); turns on automatically once Phase 8.2 / 8.3 populate '
  'the join table.';

GRANT SELECT ON public.v_district_full_spend TO anon, authenticated;
