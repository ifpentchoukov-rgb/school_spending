-- Phase 10.2 — api_keys table + is_admin() helper
--
-- Opaque bearer keys (prefix 'ssk_') used by /api/v1/* callers as an
-- alternative to short-lived Supabase session JWTs. Stored as sha256
-- hashes; the cleartext is only visible at creation time. Tier is
-- inherited from the issuing user's researcher_allowlist entry at
-- request time (resolveTierForUserId), not stored on the key itself —
-- so revoking the allowlist entry transparently downgrades all of that
-- user's keys.

CREATE TABLE IF NOT EXISTS public.api_keys (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name         text NOT NULL,
  prefix       text NOT NULL,             -- first 12 chars of the key ("ssk_" + 8)
  key_hash     text NOT NULL,             -- hex sha256 of the full key
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked_at   timestamptz,
  UNIQUE (prefix)                          -- enables single-row lookup by prefix
);

CREATE INDEX IF NOT EXISTS api_keys_user_id_idx ON public.api_keys (user_id);
CREATE INDEX IF NOT EXISTS api_keys_prefix_active_idx
  ON public.api_keys (prefix) WHERE revoked_at IS NULL;

COMMENT ON TABLE public.api_keys IS
  'Phase 10.2 — opaque bearer API keys for /api/v1 callers. ssk_ prefix; sha256 hash stored. Tier is inherited at request time from the issuing user''s researcher_allowlist + app_metadata.role, not stored on the key.';

-- is_admin(): true iff the current JWT carries app_metadata.role = 'admin'.
-- Companion to the existing is_verifier() which returns true for both
-- 'researcher' and 'admin'.
CREATE OR REPLACE FUNCTION public.is_admin() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER AS $$
  SELECT COALESCE(
    (auth.jwt() #>> '{app_metadata,role}') = 'admin',
    false
  )
$$;

GRANT EXECUTE ON FUNCTION public.is_admin() TO anon, authenticated;

ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS api_keys_admin_select ON public.api_keys;
CREATE POLICY api_keys_admin_select ON public.api_keys
  FOR SELECT TO authenticated
  USING (public.is_admin());

DROP POLICY IF EXISTS api_keys_admin_insert ON public.api_keys;
CREATE POLICY api_keys_admin_insert ON public.api_keys
  FOR INSERT TO authenticated
  WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS api_keys_admin_update ON public.api_keys;
CREATE POLICY api_keys_admin_update ON public.api_keys
  FOR UPDATE TO authenticated
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- Service role bypasses RLS; used by detectTier() to authenticate inbound
-- requests carrying a Bearer ssk_ key (RLS-via-user is circular for an
-- authn-time lookup).

GRANT SELECT, INSERT, UPDATE ON public.api_keys TO authenticated;
GRANT ALL ON public.api_keys TO service_role;
