-- 0001_core_schema.sql
-- Phase 1: core tables, enums, indexes, and FKs per PLAN.md §4.
-- Apply via the Supabase MCP `apply_migration` tool.

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

create type budget_status as enum (
    'proposed',
    'tentative',
    'adopted',
    'disapproved',
    'actual'
);

create type verification_status as enum (
    'unverified',
    'verified',
    'flagged',
    'disputed'
);

create type extraction_run_status as enum (
    'success',
    'partial',
    'failed'
);

create type extraction_trigger as enum (
    'cron',
    'manual',
    'backfill'
);

-- ---------------------------------------------------------------------------
-- updated_at trigger function (shared)
-- ---------------------------------------------------------------------------

create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- districts — universe of operating school districts
-- ---------------------------------------------------------------------------

create table districts (
    leaid text primary key,
    lea_name text not null,
    state_postal text not null,
    state_leaid text,
    county_name text,
    enrollment_fy25 integer,
    exp_total_fy23 numeric,
    is_operating_district boolean not null default true,
    data_tier smallint check (data_tier between 1 and 3),
    fy_calendar text check (fy_calendar in ('July-June', 'Sept-Aug')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index districts_state_idx on districts (state_postal);

create trigger districts_set_updated_at
before update on districts
for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- state_calendars — statutory budget adoption deadlines per (state, fiscal_year)
-- ---------------------------------------------------------------------------

create table state_calendars (
    state_postal text not null,
    fiscal_year integer not null,
    proposed_window_start date,
    proposed_window_end date,
    adoption_deadline date,
    oversight_review_deadline date,
    statute_citation text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (state_postal, fiscal_year)
);

create trigger state_calendars_set_updated_at
before update on state_calendars
for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- source_documents — every cited document
-- ---------------------------------------------------------------------------

create table source_documents (
    id uuid primary key default gen_random_uuid(),
    source_url text,
    storage_path text,
    content_hash_sha256 text,
    mime_type text,
    fetched_at timestamptz not null default now(),
    publisher text,
    document_type text,
    page_number integer,
    line_or_cell_reference text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index source_documents_hash_idx
    on source_documents (content_hash_sha256)
    where content_hash_sha256 is not null;

create trigger source_documents_set_updated_at
before update on source_documents
for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- extraction_runs — log of every extractor execution
-- ---------------------------------------------------------------------------

create table extraction_runs (
    id uuid primary key default gen_random_uuid(),
    extractor_name text not null,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status extraction_run_status not null default 'success',
    records_extracted integer,
    records_changed integer,
    error_summary text,
    git_commit_sha text,
    triggered_by extraction_trigger not null default 'manual'
);

create index extraction_runs_extractor_started_idx
    on extraction_runs (extractor_name, started_at desc);

-- ---------------------------------------------------------------------------
-- budget_events — heart of the system
-- ---------------------------------------------------------------------------

create table budget_events (
    id uuid primary key default gen_random_uuid(),
    leaid text not null references districts (leaid) on delete restrict,
    fiscal_year integer not null,
    status budget_status not null,
    topline_amount numeric not null,
    topline_definition text,
    yoy_change_pct numeric,
    yoy_change_dollars numeric,
    prior_year_baseline numeric,
    event_date date,
    source_document_id uuid not null references source_documents (id) on delete restrict,
    extraction_run_id uuid references extraction_runs (id) on delete set null,
    verification_status verification_status not null default 'unverified',
    verified_by text,
    verified_at timestamptz,
    verification_notes text,
    is_superseded boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index budget_events_lookup_idx
    on budget_events (leaid, fiscal_year, status, is_superseded);

create index budget_events_state_year_idx
    on budget_events (fiscal_year, is_superseded);

create trigger budget_events_set_updated_at
before update on budget_events
for each row execute function set_updated_at();

-- ---------------------------------------------------------------------------
-- verification_log — append-only audit trail
-- ---------------------------------------------------------------------------

create table verification_log (
    id uuid primary key default gen_random_uuid(),
    budget_event_id uuid not null references budget_events (id) on delete restrict,
    actor text not null,
    action text not null check (action in ('verified', 'flagged', 'disputed', 'unflagged', 'note_added')),
    previous_status text,
    new_status text,
    notes text,
    created_at timestamptz not null default now()
);

create index verification_log_event_idx
    on verification_log (budget_event_id, created_at desc);

-- Enforce append-only: block UPDATE and DELETE.
create or replace function reject_mutation()
returns trigger language plpgsql as $$
begin
    raise exception 'verification_log is append-only';
end;
$$;

create trigger verification_log_no_update
before update on verification_log
for each row execute function reject_mutation();

create trigger verification_log_no_delete
before delete on verification_log
for each row execute function reject_mutation();

-- ---------------------------------------------------------------------------
-- Helper view: latest non-superseded events
-- ---------------------------------------------------------------------------

create view budget_events_current as
select *
from budget_events
where is_superseded = false;

comment on view budget_events_current is
    'Convenience view returning only non-superseded events. Use this for the primary read path.';
