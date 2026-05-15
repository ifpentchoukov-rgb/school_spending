-- Phase 11.2 — v_fy27_rollup view
--
-- Per-district FY26 baseline vs FY27 adopted. Baseline prefers FY26
-- actual (post-audit) if available, otherwise FY26 adopted (board-
-- approved). One row per LEA that has a non-superseded FY27 adopted
-- event. Dollar + percent change computed against the baseline;
-- per-pupil columns use districts.enrollment_fy25.
--
-- This view is the backbone of Phase 11.3 (/reports/fy27 page) and
-- the FY27 press kit (Phase 11.4). It starts trickling in as states
-- close their adoption windows: NJ 2026-05-15, NY referenda mid-May,
-- most states by 2026-06-30, with PA/CA/TX/WA/IN/CT/KS through
-- 2026-08 to 2026-11.

CREATE OR REPLACE VIEW public.v_fy27_rollup AS
WITH fy27 AS (
  SELECT
    leaid,
    id            AS fy27_event_id,
    topline_amount AS fy27_amount,
    topline_definition AS fy27_definition,
    source_document_id AS fy27_source_document_id
  FROM public.budget_events
  WHERE fiscal_year = 2027
    AND status = 'adopted'
    AND is_superseded = false
),
fy26 AS (
  -- Prefer FY26 actual; fall back to FY26 adopted. DISTINCT ON keeps
  -- the highest-priority row per leaid where 'actual' beats 'adopted'.
  SELECT DISTINCT ON (leaid)
    leaid,
    id            AS fy26_event_id,
    status        AS fy26_status,
    topline_amount AS fy26_amount,
    topline_definition AS fy26_definition
  FROM public.budget_events
  WHERE fiscal_year = 2026
    AND is_superseded = false
    AND status IN ('actual', 'adopted')
  ORDER BY
    leaid,
    CASE status WHEN 'actual' THEN 0 ELSE 1 END,
    updated_at DESC
)
SELECT
  d.leaid,
  d.lea_name,
  d.state_postal,
  d.state_leaid,
  d.county_name,
  d.enrollment_fy25,
  d.entity_type,
  fy27.fy27_event_id,
  fy27.fy27_amount,
  fy27.fy27_definition,
  fy27.fy27_source_document_id,
  fy26.fy26_event_id,
  fy26.fy26_status              AS fy26_baseline_status,
  fy26.fy26_amount              AS fy26_baseline_amount,
  fy26.fy26_definition          AS fy26_baseline_definition,
  CASE
    WHEN fy26.fy26_amount IS NULL THEN NULL
    ELSE fy27.fy27_amount - fy26.fy26_amount
  END                            AS dollar_change,
  CASE
    WHEN fy26.fy26_amount IS NULL OR fy26.fy26_amount = 0 THEN NULL
    ELSE (fy27.fy27_amount - fy26.fy26_amount) / fy26.fy26_amount * 100
  END                            AS pct_change,
  fy27.fy27_amount / NULLIF(d.enrollment_fy25, 0) AS fy27_per_pupil,
  fy26.fy26_amount / NULLIF(d.enrollment_fy25, 0) AS fy26_per_pupil,
  -- Bucket for histogram in /reports/fy27. Keep the boundary semantics
  -- explicit so the UI doesn't have to redo the math.
  CASE
    WHEN fy26.fy26_amount IS NULL OR fy26.fy26_amount = 0 THEN 'no_baseline'
    WHEN (fy27.fy27_amount - fy26.fy26_amount) / fy26.fy26_amount * 100 >= 10  THEN 'gte_10pct'
    WHEN (fy27.fy27_amount - fy26.fy26_amount) / fy26.fy26_amount * 100 >= 5   THEN '5_to_10pct'
    WHEN (fy27.fy27_amount - fy26.fy26_amount) / fy26.fy26_amount * 100 >= 0   THEN '0_to_5pct'
    WHEN (fy27.fy27_amount - fy26.fy26_amount) / fy26.fy26_amount * 100 >= -5  THEN 'neg_5_to_0pct'
    WHEN (fy27.fy27_amount - fy26.fy26_amount) / fy26.fy26_amount * 100 >= -10 THEN 'neg_10_to_neg_5pct'
    ELSE 'lt_neg_10pct'
  END                            AS change_bucket
FROM fy27
JOIN public.districts d ON d.leaid = fy27.leaid
LEFT JOIN fy26 ON fy26.leaid = fy27.leaid
WHERE d.entity_type = 'district';

COMMENT ON VIEW public.v_fy27_rollup IS
  'Phase 11.2 — per-LEA FY26 baseline vs FY27 adopted topline. Baseline '
  'prefers FY26 actual, falls back to FY26 adopted. dollar_change and '
  'pct_change vs baseline; change_bucket pre-computed for the /reports/fy27 '
  'histogram. Backbone of Phase 11.3 (national rollup page) + Phase 11.4 '
  '(press kit).';

GRANT SELECT ON public.v_fy27_rollup TO anon, authenticated;
