-- Database webhooks → school-spending-web /api/revalidate
--
-- Three triggers that POST to the Vercel-hosted Next.js revalidate
-- route whenever budget_events / extraction_runs / extractor_triggers
-- change. The web app's RSC pages then refresh within ~10s.
--
-- We invoke supabase_functions.http_request() — the same helper the
-- Supabase dashboard "Database Webhooks" UI uses — so these triggers
-- show up there and can be inspected/edited via the dashboard.
--
-- The webhook secret is shared between this trigger header and the
-- SUPABASE_WEBHOOK_SECRET env var in Vercel. If you rotate the secret,
-- update both: generate a new value, set it in Vercel env, then drop
-- and recreate these three triggers with the new header.

CREATE TRIGGER "revalidate-budget-events"
  AFTER INSERT OR UPDATE ON public.budget_events
  FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request(
    'https://school-spending-web.vercel.app/api/revalidate',
    'POST',
    '{"Content-Type":"application/json","x-webhook-secret":"f93ff205474adeb1ab31d631ffa4008a"}',
    '{}',
    '5000'
  );

CREATE TRIGGER "revalidate-runs"
  AFTER UPDATE ON public.extraction_runs
  FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request(
    'https://school-spending-web.vercel.app/api/revalidate',
    'POST',
    '{"Content-Type":"application/json","x-webhook-secret":"f93ff205474adeb1ab31d631ffa4008a"}',
    '{}',
    '5000'
  );

CREATE TRIGGER "revalidate-triggers"
  AFTER INSERT OR UPDATE ON public.extractor_triggers
  FOR EACH ROW EXECUTE FUNCTION supabase_functions.http_request(
    'https://school-spending-web.vercel.app/api/revalidate',
    'POST',
    '{"Content-Type":"application/json","x-webhook-secret":"f93ff205474adeb1ab31d631ffa4008a"}',
    '{}',
    '5000'
  );
