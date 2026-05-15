"""Daily extractor runner — implements PLAN.md §5.

Reads state_calendars for the target fiscal year, identifies states whose
adoption window is currently open ("today between proposed_window_start and
30 days past adoption_deadline"), and dispatches the registered extractors
for each active state.

Outputs a markdown summary at `daily_summary.md` (CI uploads as an artifact).

Usage:
    python -m runner.daily                    # FY27, budget kind, cron mode
    python -m runner.daily --include-actuals  # also run actuals
    python -m runner.daily --states FL TX     # only specific states
    python -m runner.daily --all-states       # ignore calendar gating
"""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from extractors._client import get_client
from runner.registry import REGISTRY, ExtractorSpec

POST_DEADLINE_GRACE = timedelta(days=30)
DEFAULT_FY = 2027  # PLAN.md §1: FY27 is the primary tracking target
SUMMARY_PATH = Path(__file__).parent.parent / "daily_summary.md"


@dataclass
class JobResult:
    state: str
    kind: str
    module: str
    fiscal_year: int
    status: str  # "success" | "failed" | "skipped"
    records_extracted: int = 0
    records_changed: int = 0
    error: str | None = None
    skipped_reason: str | None = None


def fetch_active_states(target_fy: int, today: date) -> list[dict[str, Any]]:
    """Return state_calendars rows where today is within the active window."""
    client = get_client()
    rows = (
        client.table("state_calendars")
        .select("state_postal, fiscal_year, proposed_window_start, "
                "adoption_deadline, statute_citation")
        .eq("fiscal_year", target_fy)
        .execute()
    ).data or []

    active = []
    for row in rows:
        ws = row.get("proposed_window_start")
        ad = row.get("adoption_deadline")
        if not ws or not ad:
            continue
        ws_d = date.fromisoformat(ws)
        ad_d = date.fromisoformat(ad)
        if ws_d <= today <= ad_d + POST_DEADLINE_GRACE:
            active.append(row)
    return active


def run_extractor(spec: ExtractorSpec, runner_fy: int, triggered_by: str) -> JobResult:
    fy_target = runner_fy + spec.fy_offset
    job = JobResult(
        state=spec.state_postal, kind=spec.kind, module=spec.module,
        fiscal_year=fy_target, status="success",
    )
    try:
        mod = importlib.import_module(spec.module)
        result = mod.extract(fiscal_year=fy_target, triggered_by=triggered_by)
        job.records_extracted = int(result.get("records_extracted", 0))
        job.records_changed = int(result.get("records_changed", 0))
    except SystemExit as e:
        job.status = "failed"
        job.error = f"SystemExit: {e}"
    except Exception as e:
        # Late-binding import — this module is also imported by the daily
        # runner before extractors[] is populated, so importing at module
        # scope would be fine, but keeping it here documents the linkage.
        from extractors._exceptions import SourceNotYetPublished
        if isinstance(e, SourceNotYetPublished):
            job.status = "partial"
            job.error = f"SourceNotYetPublished: {e}"
        else:
            job.status = "failed"
            job.error = f"{type(e).__name__}: {e}"
    return job


def write_summary(
    *,
    today: date,
    target_fy: int,
    triggered_by: str,
    active_calendar_rows: list[dict[str, Any]],
    skipped_no_extractor: list[str],
    job_results: list[JobResult],
) -> None:
    lines: list[str] = []
    lines.append(f"# Daily extractor summary — {today.isoformat()}")
    lines.append("")
    lines.append(f"- Target fiscal year: **{target_fy}**")
    lines.append(f"- Triggered by: `{triggered_by}`")
    lines.append(f"- Active states (within proposal-or-adoption window): "
                 f"**{len(active_calendar_rows)}**")
    lines.append(f"- Extractor jobs run: **{len(job_results)}**")
    n_success = sum(1 for j in job_results if j.status == "success")
    n_failed = sum(1 for j in job_results if j.status == "failed")
    total_changed = sum(j.records_changed for j in job_results)
    total_extracted = sum(j.records_extracted for j in job_results)
    lines.append(f"- Success: **{n_success}**, Failed: **{n_failed}**, "
                 f"Records changed: **{total_changed:,}** "
                 f"(of {total_extracted:,} extracted)")
    lines.append("")

    if active_calendar_rows:
        lines.append("## Active calendar windows")
        lines.append("| state | adoption deadline | statute |")
        lines.append("| --- | --- | --- |")
        for r in sorted(active_calendar_rows, key=lambda r: r["adoption_deadline"]):
            lines.append(
                f"| {r['state_postal']} | {r['adoption_deadline']} | "
                f"{r['statute_citation'] or ''} |"
            )
        lines.append("")

    if skipped_no_extractor:
        lines.append("## Active states with NO registered extractor")
        lines.append(", ".join(sorted(skipped_no_extractor)))
        lines.append("")
        lines.append("> Add an entry in `runner/registry.py` when an extractor "
                     "for a state is built.")
        lines.append("")

    if job_results:
        lines.append("## Per-extractor results")
        lines.append("| state | kind | module | FY | status | extracted | changed | error |")
        lines.append("| --- | --- | --- | --- | --- | ---: | ---: | --- |")
        for j in job_results:
            err = (j.error or "").replace("|", "\\|")[:80]
            status_marker = "✅" if j.status == "success" else "❌"
            lines.append(
                f"| {j.state} | {j.kind} | `{j.module}` | {j.fiscal_year} "
                f"| {status_marker} {j.status} | {j.records_extracted:,} "
                f"| {j.records_changed:,} | {err} |"
            )
        lines.append("")

    SUMMARY_PATH.write_text("\n".join(lines) + "\n")
    print(f"\nSummary written: {SUMMARY_PATH}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fiscal-year", type=int, default=DEFAULT_FY,
                   help="Calendar fiscal year (used to query state_calendars)")
    p.add_argument("--triggered-by", default="cron",
                   choices=["cron", "manual", "backfill"])
    p.add_argument("--include-actuals", action="store_true",
                   help="Also run kind=actuals extractors (default: budget only)")
    p.add_argument("--states", nargs="*",
                   help="Only run extractors for these state postals (filter)")
    p.add_argument("--all-states", action="store_true",
                   help="Skip calendar gating; run for every state in the registry")
    p.add_argument("--today", default=None,
                   help="ISO date to use as 'today' (for backfill / testing)")
    args = p.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    target_fy = args.fiscal_year
    print(f"Daily runner: today={today.isoformat()} "
          f"target_fy={target_fy} triggered_by={args.triggered_by}")

    if args.all_states:
        active_states = sorted({s.state_postal for s in REGISTRY})
        active_calendar_rows: list[dict[str, Any]] = []
        print(f"  --all-states: skipping calendar gating; states={active_states}")
    else:
        active_calendar_rows = fetch_active_states(target_fy, today)
        active_states = [r["state_postal"] for r in active_calendar_rows]
        print(f"  active states for FY{target_fy} on {today}: "
              f"{active_states or '<none>'}")

    if args.states:
        keep = set(args.states)
        active_states = [s for s in active_states if s in keep]
        active_calendar_rows = [r for r in active_calendar_rows if r["state_postal"] in keep]
        print(f"  --states filter applied: {sorted(keep)} → {active_states}")

    # Find which (state, kind) extractors apply
    kinds_to_run = {"budget"}
    if args.include_actuals:
        kinds_to_run.add("actuals")

    skipped_no_extractor: list[str] = []
    jobs: list[ExtractorSpec] = []
    for state in active_states:
        applicable = [s for s in REGISTRY if s.state_postal == state and s.kind in kinds_to_run]
        if not applicable:
            skipped_no_extractor.append(state)
            continue
        jobs.extend(applicable)

    print(f"  jobs to run: {len(jobs)}; states with no registered extractor: "
          f"{skipped_no_extractor or '<none>'}")

    results: list[JobResult] = []
    for spec in jobs:
        print(f"\n=== running {spec.module} ({spec.state_postal}/{spec.kind}) ===")
        job = run_extractor(spec, target_fy, args.triggered_by)
        results.append(job)
        marker = "OK" if job.status == "success" else "FAILED"
        print(f"  → {marker}: extracted={job.records_extracted} "
              f"changed={job.records_changed}"
              + (f"  error={job.error}" if job.error else ""))

    write_summary(
        today=today,
        target_fy=target_fy,
        triggered_by=args.triggered_by,
        active_calendar_rows=active_calendar_rows,
        skipped_no_extractor=skipped_no_extractor,
        job_results=results,
    )

    # Exit code reflects whether any job failed (CI signal)
    return 1 if any(j.status == "failed" for j in results) else 0


if __name__ == "__main__":
    sys.exit(main())
