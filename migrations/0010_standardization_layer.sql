-- Phase 7.1–7.3: Standardization layer
--
-- Three parts:
--   1. `expenditure_category` enum — the canonical 14-category taxonomy.
--   2. `budget_event_components` — per-event line-item breakdown, one
--      row per (budget_event_id, category) tuple. RLS mirrors
--      budget_events: anon reads only where the parent event isn't
--      superseded; authenticated reads all; service role writes.
--   3. `state_extractor_metadata` — per-state coverage_tier so consumers
--      can know what's apples-to-apples. Seeded with the classification
--      from docs/STATUS.md (8 rich, 26 moderate, 11 thin, 6 deferred).
--
-- Migration 0011 (Phase 8) will add entity_type to districts and the
-- cooperative_membership table. This migration is independent.

-- ──────────────────────────────────────────────────────────────
-- Part 1 — Canonical category enum
-- ──────────────────────────────────────────────────────────────

CREATE TYPE public.expenditure_category AS ENUM (
  'instruction',
  'support_services_student',
  'support_services_instruction',
  'administration',
  'operations_maintenance',
  'transportation',
  'food_service',
  'employee_benefits',
  'capital_outlay',
  'debt_service',
  'revenue_federal',
  'revenue_state',
  'revenue_local',
  'other'
);

COMMENT ON TYPE public.expenditure_category IS
  'Canonical line-item categories for budget_event_components. See PLAN.md Phase 7.1 for definitions per category.';

-- ──────────────────────────────────────────────────────────────
-- Part 2 — budget_event_components table
-- ──────────────────────────────────────────────────────────────

CREATE TABLE public.budget_event_components (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  budget_event_id uuid NOT NULL
    REFERENCES public.budget_events(id) ON DELETE CASCADE,
  category public.expenditure_category NOT NULL,
  amount numeric NOT NULL,
  -- Source-specific accounting definition for THIS component, e.g.
  -- "PEIMS OBJECT in 6100-6499 where FUNCTION in 11-13" for TX
  -- instruction.
  definition text,
  -- Per-component provenance: which page/cell of the source document
  -- this value came from. Complements source_documents.line_or_cell_reference.
  line_or_cell_reference text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (budget_event_id, category)
);

CREATE INDEX idx_budget_event_components_budget_event_id
  ON public.budget_event_components (budget_event_id);
CREATE INDEX idx_budget_event_components_category
  ON public.budget_event_components (category);

COMMENT ON TABLE public.budget_event_components IS
  'Line-item breakdown of a budget_events topline into canonical categories. Populated by rich/moderate-tier extractors at extraction time. UNIQUE on (budget_event_id, category).';

ALTER TABLE public.budget_event_components ENABLE ROW LEVEL SECURITY;

-- Anonymous read: only components whose parent budget_event is not
-- superseded. Mirrors the budget_events_read_anon pattern.
CREATE POLICY "budget_event_components_read_anon"
  ON public.budget_event_components FOR SELECT
  TO anon
  USING (
    EXISTS (
      SELECT 1 FROM public.budget_events be
      WHERE be.id = budget_event_components.budget_event_id
        AND be.is_superseded = false
    )
  );

-- Authenticated read: all rows (verifiers may need to inspect superseded
-- history).
CREATE POLICY "budget_event_components_read_authed"
  ON public.budget_event_components FOR SELECT
  TO authenticated
  USING (true);

-- service_role bypasses RLS by default — no explicit write policies needed.

-- ──────────────────────────────────────────────────────────────
-- Part 3 — state_extractor_metadata + seed
-- ──────────────────────────────────────────────────────────────

CREATE TABLE public.state_extractor_metadata (
  state_postal text PRIMARY KEY,
  coverage_tier text NOT NULL
    CHECK (coverage_tier IN ('rich', 'moderate', 'thin', 'deferred')),
  tier_rationale text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.state_extractor_metadata IS
  'Per-state coverage classification for the standardization layer (Phase 7.3). rich = ≥8 canonical categories extractable; moderate = 2-5; thin = single topline; deferred = no extractor yet.';

ALTER TABLE public.state_extractor_metadata ENABLE ROW LEVEL SECURITY;

CREATE POLICY "state_extractor_metadata_read_anon"
  ON public.state_extractor_metadata FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "state_extractor_metadata_read_authed"
  ON public.state_extractor_metadata FOR SELECT
  TO authenticated
  USING (true);

-- Seed initial classification per docs/STATUS.md "Tiered standardization
-- coverage" section. Upsert-safe — re-running won't fail.
INSERT INTO public.state_extractor_metadata (state_postal, coverage_tier, tier_rationale) VALUES
  -- rich (8)
  ('TX', 'rich', 'PEIMS Object × Function grid; 8+ canonical categories extractable'),
  ('MI', 'rich', '5 funds × all expenditure objects in Bulletin 1011'),
  ('IL', 'rich', 'ISBE OEPP function detail'),
  ('PA', 'rich', 'GFB FB_Cert function rows'),
  ('KY', 'rich', 'Function 1000-3900 columns in R&E workbook'),
  ('WI', 'rich', 'DPI Comparative Cost: 7 per-FY cost columns (instruct, support, admin, operations, trans, facility, food)'),
  ('KS', 'rich', 'BAG page-4 category rows'),
  ('NY', 'rich', 'ST-3 SAMS XLSX — 4,200+ line items via SED Legacy/RefKey columns'),
  -- moderate (26)
  ('OH', 'moderate', 'Cupp District Profile Report — fund-level breakdown available beyond per-pupil topline'),
  ('CO', 'moderate', 'CDE Financial Transparency — fund-level categories'),
  ('IA', 'moderate', 'CAR multi-sheet — 4 core operating fund sheets'),
  ('AR', 'moderate', 'ASR per-district pages — summary expenditure categories'),
  ('OK', 'moderate', 'OCAS ExpenditureSummary — function + object detail'),
  ('OR', 'moderate', 'Detailed District Expenditure — function-level'),
  ('WA', 'moderate', 'F-196 — General Fund detail available'),
  ('NJ', 'moderate', 'TGES Detail XLSX — fund + categorical detail'),
  ('IN', 'moderate', 'SCFI Annual Deficit Surplus — fund classification detail'),
  ('MA', 'moderate', 'DESE Profiles PPX — categorical totals (instruction, support, etc.)'),
  ('VA', 'moderate', 'APA Comparative — Exhibit C-6 education functions'),
  ('GA', 'moderate', 'GOSA Rev/Exp — 11 expenditure descriptions per district'),
  ('MO', 'moderate', 'DESE MCDS Finance Summary XLS — fund-level totals'),
  ('MN', 'moderate', 'MDE MFR UFR020 PDFs — fund-level breakdown'),
  ('NE', 'moderate', 'SFOS AFR ZIP — Fund 01 GF function detail'),
  ('TN', 'moderate', 'ASR Table 51 — operating expenditure detail'),
  ('AZ', 'moderate', 'ADE SAFR Digital Data — function-level detail (unified districts only)'),
  ('MS', 'moderate', 'MDE Superintendent Annual Report — categorical detail'),
  ('ID', 'moderate', 'ISDE 20-Year R&E — categorical breakdown'),
  ('SD', 'moderate', 'SD DOE All Expenditures — categorical detail'),
  ('ND', 'moderate', 'NDDPI FinFacts PDF — categorical breakdown'),
  ('MT', 'moderate', 'OPI School Expenditures — categorical detail'),
  ('UT', 'moderate', 'USBE AFR — 5 functional categories × 8 object subcategories'),
  ('LA', 'moderate', 'LDOE AFSR Item 9 — categorical breakdown by E11-E52'),
  ('FL', 'moderate', 'FLDOE AFR + Summary Budget — categorical totals'),
  ('CA', 'moderate', 'SACS Funds 01-29 Object 1000-7999 — full detail available; currently only topline pulled'),
  -- thin (11)
  ('AL', 'thin', 'ALSDE System Level Per-Pupil PDF — per-pupil topline only'),
  ('VT', 'thin', 'VT AOE Cohort Spending — per-equiv-pupil only'),
  ('NH', 'thin', 'NH DOE CPP CSV — CPP × enrollment reconstruction'),
  ('HI', 'thin', 'HIDOE AFSA — statewide single district; no per-district detail'),
  ('ME', 'thin', 'RSU/MSAD granularity mismatch — 54.8% coverage; per-district detail not available'),
  ('MD', 'thin', 'MSDE SFD Part 2 — single Current Expense Fund column'),
  ('SC', 'thin', 'SCDE In$ite per-district PDFs — Function total only'),
  ('NC', 'thin', 'NCDPI SPSF — state-funded only (~58%); no categorical breakdown'),
  ('DC', 'thin', 'OSSE Report Card Finance — single topline'),
  ('CT', 'thin', 'OPM SODA API — single education_expenditures line'),
  ('WV', 'thin', 'WVDE PSSP BOE Recon — state-aid frame only'),
  -- deferred (6)
  ('NV', 'deferred', 'per-LEA PDFs unpredictable URLs; Chrome-MCP / FOIA path forward'),
  ('NM', 'deferred', 'openbooks.ped.nm.gov Looker SaaS embed — tile-by-tile scrape required'),
  ('AK', 'deferred', 'No per-district bulk expenditure file published; FOIA DEED'),
  ('RI', 'deferred', 'datacenter.ride.ri.gov Tableau-only; Chrome-MCP / FOIA'),
  ('DE', 'deferred', 'EDSTATS PDF lags 2 years; wait for fresher publication'),
  ('WY', 'deferred', 'edu.wyoming.gov JS-rendered, no bulk download')
ON CONFLICT (state_postal) DO UPDATE
  SET coverage_tier = excluded.coverage_tier,
      tier_rationale = excluded.tier_rationale,
      updated_at = now();
