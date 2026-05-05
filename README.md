# School District Budget Tracker — Initial Repo Package

This is the initial seed for a new Git repository. Drop the contents of this directory into the root of an empty repo and commit.

## What's here

```
.
├── PLAN.md                  ← project plan (read this first)
├── CLAUDE.md                ← short pointer file for Claude Code
├── README.md                ← this file
├── requirements.txt         ← Python deps for legacy scripts
├── .gitignore               ← standard Python + project-specific exclusions
└── legacy/
    ├── README.md            ← what's in legacy/ and how to re-run it
    ├── sd_tracker_step1/    ← master district universe + F-23 baseline
    │   ├── scripts/
    │   │   ├── build_master.py
    │   │   └── state_tiers.py
    │   └── processed/
    │       ├── master_districts.csv      ← THE seed file for districts table
    │       └── master_districts.xlsx
    └── sd_tracker_step2/    ← three working state extractors (TX/CA/FL)
        ├── scripts/
        │   ├── run_extractors.py
        │   └── extractors/
        │       ├── __init__.py
        │       ├── _base.py
        │       ├── ca.py
        │       ├── fl.py
        │       └── tx.py
        └── processed/
            ├── spending_signal.csv       ← seed for budget_events (FY25 actuals)
            ├── spending_signal.xlsx
            ├── state_extractions.csv
            └── coverage_report.txt
```

Total package size: ~9 MB. No raw source files (PDFs, Excel downloads, .mdb files) are included — the legacy scripts know how to re-fetch them from public state portals.

## Reading order for Claude Code

1. `PLAN.md` — full project plan, architecture, schema, phased work
2. `CLAUDE.md` — short operating instructions
3. `legacy/README.md` — context on the existing code and data
4. `legacy/sd_tracker_step1/scripts/build_master.py` — how the universe was built
5. `legacy/sd_tracker_step2/scripts/extractors/_base.py` — the extractor schema pattern to preserve

## What this seed gives you

- **11,880 operating US school districts** keyed on NCES LEAID, with FY23 audited baseline expenditures from Census F-33 (in `master_districts.csv`)
- **1,607 records of FY25 actual expenditures** with year-over-year comparisons for TX (1,068), CA (474), FL (67) — these become the FY26 prior-year baseline for FY27 comparisons
- **Three working state extractor patterns**: bulk-Excel (TX), Microsoft Access database (CA), PDF-text-parsing (FL). The next 47 states will follow one of these three templates.

## Phase 0 starts here

Per PLAN.md §6, Phase 0 is repo + Supabase setup. Concretely:

1. Initialize git in this directory: `git init && git add . && git commit -m "Initial seed"`
2. Push to a new GitHub repo
3. Create a Supabase project (or use existing) and confirm MCP is connected
4. Set up `pyproject.toml` for the new code (separate from legacy scripts)
5. Stub `.github/workflows/daily.yml`

Don't touch `legacy/` after this point. It's reference material. The new code lives at the repo root in `extractors/`, `runner/`, `migrations/`, etc., as described in PLAN.md.
