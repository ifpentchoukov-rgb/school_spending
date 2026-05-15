-- Phase 7.6 — v_per_pupil_metrics view
--
-- Wide-format view over non-superseded budget_events, joined to districts
-- (for enrollment + naming) and budget_event_components (one LEFT JOIN per
-- canonical category from the expenditure_category enum). Exposes:
--   - topline_amount + topline_per_pupil
--   - For each of the 14 canonical categories: {category}_amount,
--     {category}_per_pupil
--
-- Per-pupil divisor is districts.enrollment_fy25. Where enrollment is null
-- or zero, the per-pupil columns are NULL (NULLIF guard).
--
-- Powers Phase 9 rankings, Phase 9.4 per-LEA category breakdown, and
-- Phase 10 API endpoints. RLS is inherited from the underlying tables
-- (anon read where is_superseded=false; service role writes).

CREATE OR REPLACE VIEW public.v_per_pupil_metrics AS
SELECT
  be.id                   AS budget_event_id,
  be.leaid,
  be.fiscal_year,
  be.status,
  be.topline_amount,
  be.topline_definition,
  be.yoy_change_pct,
  be.yoy_change_dollars,
  be.prior_year_baseline,
  be.verification_status,
  d.lea_name,
  d.state_postal,
  d.state_leaid,
  d.county_name,
  d.enrollment_fy25,
  d.is_operating_district,
  be.topline_amount / NULLIF(d.enrollment_fy25, 0)
    AS topline_per_pupil,
  -- Expenditure categories
  bec_instruction.amount AS instruction_amount,
  bec_instruction.amount / NULLIF(d.enrollment_fy25, 0)
    AS instruction_per_pupil,
  bec_ss_student.amount  AS support_services_student_amount,
  bec_ss_student.amount / NULLIF(d.enrollment_fy25, 0)
    AS support_services_student_per_pupil,
  bec_ss_instr.amount    AS support_services_instruction_amount,
  bec_ss_instr.amount / NULLIF(d.enrollment_fy25, 0)
    AS support_services_instruction_per_pupil,
  bec_admin.amount       AS administration_amount,
  bec_admin.amount / NULLIF(d.enrollment_fy25, 0)
    AS administration_per_pupil,
  bec_om.amount          AS operations_maintenance_amount,
  bec_om.amount / NULLIF(d.enrollment_fy25, 0)
    AS operations_maintenance_per_pupil,
  bec_trans.amount       AS transportation_amount,
  bec_trans.amount / NULLIF(d.enrollment_fy25, 0)
    AS transportation_per_pupil,
  bec_food.amount        AS food_service_amount,
  bec_food.amount / NULLIF(d.enrollment_fy25, 0)
    AS food_service_per_pupil,
  bec_benefits.amount    AS employee_benefits_amount,
  bec_benefits.amount / NULLIF(d.enrollment_fy25, 0)
    AS employee_benefits_per_pupil,
  bec_capital.amount     AS capital_outlay_amount,
  bec_capital.amount / NULLIF(d.enrollment_fy25, 0)
    AS capital_outlay_per_pupil,
  bec_debt.amount        AS debt_service_amount,
  bec_debt.amount / NULLIF(d.enrollment_fy25, 0)
    AS debt_service_per_pupil,
  -- Revenue categories (populated where source separates revenue side)
  bec_rev_fed.amount     AS revenue_federal_amount,
  bec_rev_fed.amount / NULLIF(d.enrollment_fy25, 0)
    AS revenue_federal_per_pupil,
  bec_rev_state.amount   AS revenue_state_amount,
  bec_rev_state.amount / NULLIF(d.enrollment_fy25, 0)
    AS revenue_state_per_pupil,
  bec_rev_local.amount   AS revenue_local_amount,
  bec_rev_local.amount / NULLIF(d.enrollment_fy25, 0)
    AS revenue_local_per_pupil,
  bec_other.amount       AS other_amount,
  bec_other.amount / NULLIF(d.enrollment_fy25, 0)
    AS other_per_pupil
FROM public.budget_events be
JOIN public.districts d USING (leaid)
LEFT JOIN public.budget_event_components bec_instruction
  ON bec_instruction.budget_event_id = be.id
  AND bec_instruction.category = 'instruction'
LEFT JOIN public.budget_event_components bec_ss_student
  ON bec_ss_student.budget_event_id = be.id
  AND bec_ss_student.category = 'support_services_student'
LEFT JOIN public.budget_event_components bec_ss_instr
  ON bec_ss_instr.budget_event_id = be.id
  AND bec_ss_instr.category = 'support_services_instruction'
LEFT JOIN public.budget_event_components bec_admin
  ON bec_admin.budget_event_id = be.id
  AND bec_admin.category = 'administration'
LEFT JOIN public.budget_event_components bec_om
  ON bec_om.budget_event_id = be.id
  AND bec_om.category = 'operations_maintenance'
LEFT JOIN public.budget_event_components bec_trans
  ON bec_trans.budget_event_id = be.id
  AND bec_trans.category = 'transportation'
LEFT JOIN public.budget_event_components bec_food
  ON bec_food.budget_event_id = be.id
  AND bec_food.category = 'food_service'
LEFT JOIN public.budget_event_components bec_benefits
  ON bec_benefits.budget_event_id = be.id
  AND bec_benefits.category = 'employee_benefits'
LEFT JOIN public.budget_event_components bec_capital
  ON bec_capital.budget_event_id = be.id
  AND bec_capital.category = 'capital_outlay'
LEFT JOIN public.budget_event_components bec_debt
  ON bec_debt.budget_event_id = be.id
  AND bec_debt.category = 'debt_service'
LEFT JOIN public.budget_event_components bec_rev_fed
  ON bec_rev_fed.budget_event_id = be.id
  AND bec_rev_fed.category = 'revenue_federal'
LEFT JOIN public.budget_event_components bec_rev_state
  ON bec_rev_state.budget_event_id = be.id
  AND bec_rev_state.category = 'revenue_state'
LEFT JOIN public.budget_event_components bec_rev_local
  ON bec_rev_local.budget_event_id = be.id
  AND bec_rev_local.category = 'revenue_local'
LEFT JOIN public.budget_event_components bec_other
  ON bec_other.budget_event_id = be.id
  AND bec_other.category = 'other'
WHERE be.is_superseded = false;

COMMENT ON VIEW public.v_per_pupil_metrics IS
  'Phase 7.6 — wide-format view over non-superseded budget_events with '
  'per-pupil columns for the topline and each of the 14 canonical '
  'expenditure_category enum values. enrollment_fy25 is the divisor '
  '(NULL/0-safe via NULLIF). Powers Phase 9 rankings + Phase 10 API.';

-- Views inherit RLS from underlying tables. budget_events anonymous-read
-- already filters to is_superseded=false; budget_event_components anon
-- policy checks parent's is_superseded; districts is read-anon. So the
-- view is automatically scoped to the published, non-superseded slice.

GRANT SELECT ON public.v_per_pupil_metrics TO anon, authenticated;
