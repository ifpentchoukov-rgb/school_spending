-- Phase 8.1 — Cooperative entities (BOCES, ESCs, regional districts)
--
-- Goal: capture spend that today is invisible — NY BOCES (~$3B aggregate),
-- NJ Educational Services Commissions, RI/CT regional districts — and
-- allocate it back to member districts for honest per-pupil rollups.
--
-- Two changes:
--   (1) ALTER districts to add entity_type (default 'district'). Existing
--       rows stay 'district'. Phase 8.2+ extractors set 'cooperative' for
--       BOCES/ESC/regional rows. Charters can later be flipped to 'charter'.
--   (2) NEW cooperative_membership join table — composite PK on
--       (cooperative_leaid, member_leaid, fiscal_year). allocation_share is
--       0..1 (NULL if unknown). allocation_basis is a free-text breadcrumb
--       describing how the share was derived (e.g. 'enrollment_weighted',
--       'fees_paid', 'unknown').

ALTER TABLE public.districts
  ADD COLUMN IF NOT EXISTS entity_type text NOT NULL DEFAULT 'district'
    CHECK (entity_type IN ('district', 'cooperative', 'charter'));

COMMENT ON COLUMN public.districts.entity_type IS
  'Phase 8.1 — district (default), cooperative (BOCES/ESC/regional educational service unit), or charter (charter school operator). Cooperatives spend money that is then allocated to member districts via cooperative_membership.';

CREATE TABLE IF NOT EXISTS public.cooperative_membership (
  cooperative_leaid text NOT NULL REFERENCES public.districts(leaid)
    ON DELETE CASCADE,
  member_leaid      text NOT NULL REFERENCES public.districts(leaid)
    ON DELETE CASCADE,
  fiscal_year       int  NOT NULL,
  allocation_share  numeric
    CHECK (allocation_share IS NULL
           OR (allocation_share >= 0 AND allocation_share <= 1)),
  allocation_basis  text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cooperative_leaid, member_leaid, fiscal_year)
);

CREATE INDEX IF NOT EXISTS cooperative_membership_member_fy_idx
  ON public.cooperative_membership (member_leaid, fiscal_year);

CREATE INDEX IF NOT EXISTS cooperative_membership_cooperative_fy_idx
  ON public.cooperative_membership (cooperative_leaid, fiscal_year);

COMMENT ON TABLE public.cooperative_membership IS
  'Phase 8.1 — links a cooperative LEA (districts.entity_type=cooperative) to its member districts for a given fiscal_year. allocation_share (0..1) is the member''s share of cooperative spend; NULL = unknown. allocation_basis documents the derivation method (e.g. enrollment_weighted, fees_paid, unknown). Used by v_district_full_spend (Phase 8.4).';

-- RLS: anonymous read; authenticated read; service role writes. Mirrors
-- the rest of the data model.
ALTER TABLE public.cooperative_membership ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cooperative_membership_select_anon
  ON public.cooperative_membership;
CREATE POLICY cooperative_membership_select_anon
  ON public.cooperative_membership
  FOR SELECT TO anon
  USING (true);

DROP POLICY IF EXISTS cooperative_membership_select_authenticated
  ON public.cooperative_membership;
CREATE POLICY cooperative_membership_select_authenticated
  ON public.cooperative_membership
  FOR SELECT TO authenticated
  USING (true);

DROP POLICY IF EXISTS cooperative_membership_service_write
  ON public.cooperative_membership;
CREATE POLICY cooperative_membership_service_write
  ON public.cooperative_membership
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

GRANT SELECT ON public.cooperative_membership TO anon, authenticated;
GRANT ALL    ON public.cooperative_membership TO service_role;

-- updated_at trigger (matches the pattern used elsewhere in the schema)
CREATE OR REPLACE FUNCTION public.cooperative_membership_set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS cooperative_membership_updated_at_tr
  ON public.cooperative_membership;
CREATE TRIGGER cooperative_membership_updated_at_tr
  BEFORE UPDATE ON public.cooperative_membership
  FOR EACH ROW EXECUTE FUNCTION public.cooperative_membership_set_updated_at();
