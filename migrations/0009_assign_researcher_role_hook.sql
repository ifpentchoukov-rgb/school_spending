-- Auth: Custom Access Token hook + tighter is_verifier()
--
-- Problem this solves
-- ────────────────────
-- Today `is_verifier()` returns true for every authenticated user, so
-- any signed-in user can mutate verification fields, the allowlist,
-- and trigger extractors. The middleware checks `app_metadata.role`
-- but nothing actually SETS that role.
--
-- Fix
-- ───
-- 1. `public.custom_access_token_hook(event jsonb)` — Supabase Auth
--    calls this when minting a JWT. It looks up the user's email in
--    `researcher_allowlist` (active rows only); if present, sets
--    `app_metadata.role = 'researcher'` on the JWT. If not present,
--    removes any prior role (revocations propagate on next refresh).
--
-- 2. `is_verifier()` — tightened to read `auth.jwt()->'app_metadata'->>
--    'role'` and check membership in {'researcher','admin'}. RLS
--    policies that already use is_verifier() (budget_events update,
--    researcher_allowlist read/write, verification_log insert) get the
--    new gate for free.
--
-- After applying this migration
-- ─────────────────────────────
-- The hook is defined but not yet active. Enable it in the Supabase
-- dashboard:
--
--   Authentication → Hooks (under Configuration) → Custom Access Token
--   → Enable → Hook type: Postgres → Schema: public → Function:
--   custom_access_token_hook → Save.
--
-- Or via Management API: PATCH /v1/projects/{ref}/config/auth with
-- { "hook_custom_access_token_enabled": true,
--   "hook_custom_access_token_uri": "pg-functions://postgres/public/custom_access_token_hook" }

-- ── 1. The hook function ────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  claims        jsonb;
  user_email    text;
  is_researcher boolean;
  app_meta      jsonb;
BEGIN
  claims := event->'claims';
  user_email := lower(coalesce(claims->>'email', ''));

  IF user_email = '' THEN
    RETURN event;
  END IF;

  SELECT EXISTS (
    SELECT 1 FROM public.researcher_allowlist
    WHERE lower(email) = user_email
      AND revoked_at IS NULL
  ) INTO is_researcher;

  app_meta := coalesce(claims->'app_metadata', '{}'::jsonb);

  IF is_researcher THEN
    app_meta := app_meta || jsonb_build_object('role', 'researcher');
  ELSE
    app_meta := app_meta - 'role';
  END IF;

  claims := claims || jsonb_build_object('app_metadata', app_meta);
  RETURN event || jsonb_build_object('claims', claims);
END;
$$;

-- The hook runs as supabase_auth_admin (the role Supabase Auth uses);
-- nobody else should be able to call it.
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) FROM public, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) TO   supabase_auth_admin;

-- The hook needs to read the allowlist; the existing RLS policies
-- on researcher_allowlist gate read access to is_verifier(), but the
-- hook runs SECURITY DEFINER so it bypasses RLS for its lookup.
-- Make the explicit permission grant anyway for clarity.
GRANT SELECT ON public.researcher_allowlist TO supabase_auth_admin;

-- ── 2. Tighten is_verifier() ────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.is_verifier()
RETURNS boolean
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT coalesce(
    (auth.jwt()->'app_metadata'->>'role') IN ('researcher', 'admin'),
    false
  );
$$;
