"""Shared helpers for DB-aware extractors (Phase 3 architecture).

Per PLAN.md §7, every extractor should:
  1. Download the source document
  2. Compute SHA-256 hash
  3. Insert/upsert a `source_documents` row (deduped on hash)
  4. Insert a `budget_events` row referencing it
  5. Set `is_superseded=true` on any prior event for the same
     (district, fiscal_year, status)
And log an `extraction_runs` record on start/finish.

This module exposes a `Run` context manager + helpers used by per-state
extractors. State-specific download/parse logic lives in each extractor.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from supabase import Client

from extractors._client import get_client
from extractors._exceptions import SourceNotYetPublished


@dataclass
class Run:
    """One extractor execution. Logs to extraction_runs on enter/exit."""

    extractor_name: str
    triggered_by: str = "manual"
    client: Client = field(default_factory=get_client)
    run_id: str = ""
    records_extracted: int = 0
    records_changed: int = 0
    error_summary: str | None = None
    _git_sha: str | None = None

    def __post_init__(self) -> None:
        try:
            self._git_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).parent.parent,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            self._git_sha = None

    def __enter__(self) -> "Run":
        resp = (
            self.client.table("extraction_runs")
            .insert(
                {
                    "extractor_name": self.extractor_name,
                    "triggered_by": self.triggered_by,
                    "git_commit_sha": self._git_sha,
                    "status": "success",  # provisional
                }
            )
            .execute()
        )
        self.run_id = resp.data[0]["id"]
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        status = "success"
        if exc is not None:
            if isinstance(exc, SourceNotYetPublished):
                # Expected pre-publication state — surface as `partial`
                # so check_failures doesn't keep paging on it. Just the
                # message, no traceback.
                status = "partial"
                self.error_summary = f"SourceNotYetPublished: {exc}"
            else:
                status = "failed"
                self.error_summary = (
                    "".join(traceback.format_exception(exc_type, exc, tb))[-2000:]
                )
        self.client.table("extraction_runs").update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "records_extracted": self.records_extracted,
                "records_changed": self.records_changed,
                "error_summary": self.error_summary,
            }
        ).eq("id", self.run_id).execute()
        return False  # don't suppress


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_all(query, page_size: int = 1000) -> list[dict]:
    """Page through a PostgREST query — supabase-py caps a single .execute()
    at ~1,000 rows. Pass a query builder primed with .select()/.eq()/etc.
    Calling .range(start, end) yields each page; concatenate."""
    out: list[dict] = []
    start = 0
    while True:
        page = query.range(start, start + page_size - 1).execute()
        rows = page.data or []
        out.extend(rows)
        if len(rows) < page_size:
            return out
        start += page_size


def upload_source_document(
    *,
    client: Client,
    bucket: str,
    storage_path: str,
    content: bytes,
    mime_type: str,
    overwrite: bool = False,
) -> str:
    """Upload to Supabase Storage. Returns the bucket-relative path."""
    file_options: dict[str, str | bool] = {"content-type": mime_type}
    if overwrite:
        file_options["upsert"] = "true"
    client.storage.from_(bucket).upload(
        storage_path, content, file_options=file_options
    )
    return f"{bucket}/{storage_path}"


def upsert_source_document_row(
    *,
    client: Client,
    content_hash: str,
    source_url: str,
    storage_path: str,
    mime_type: str,
    publisher: str,
    document_type: str,
    page_number: int | None = None,
    line_or_cell_reference: str | None = None,
    notes: str | None = None,
) -> str:
    """Return source_documents.id, creating the row if (hash) is new."""
    existing = (
        client.table("source_documents")
        .select("id")
        .eq("content_hash_sha256", content_hash)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    inserted = (
        client.table("source_documents")
        .insert(
            {
                "source_url": source_url,
                "storage_path": storage_path,
                "content_hash_sha256": content_hash,
                "mime_type": mime_type,
                "publisher": publisher,
                "document_type": document_type,
                "page_number": page_number,
                "line_or_cell_reference": line_or_cell_reference,
                "notes": notes,
            }
        )
        .execute()
    )
    return inserted.data[0]["id"]


@dataclass
class BudgetEventInput:
    leaid: str
    fiscal_year: int
    status: str
    topline_amount: float
    topline_definition: str
    source_document_id: str
    extraction_run_id: str
    yoy_change_pct: float | None = None
    yoy_change_dollars: float | None = None
    prior_year_baseline: float | None = None
    event_date: str | None = None


def upsert_budget_event_with_supersession(
    *,
    client: Client,
    event: BudgetEventInput,
) -> tuple[str, bool]:
    """Insert event, superseding any prior non-superseded event with the same
    (leaid, fiscal_year, status). No-op if existing row is identical
    (same source_document_id and topline_amount).

    Returns (event_id, changed) where changed=False means no DB write.
    """
    prior = (
        client.table("budget_events")
        .select("id, source_document_id, topline_amount")
        .eq("leaid", event.leaid)
        .eq("fiscal_year", event.fiscal_year)
        .eq("status", event.status)
        .eq("is_superseded", False)
        .execute()
    )
    if prior.data:
        existing = prior.data[0]
        if (
            existing["source_document_id"] == event.source_document_id
            and float(existing["topline_amount"]) == float(event.topline_amount)
        ):
            return existing["id"], False
        client.table("budget_events").update({"is_superseded": True}).eq(
            "id", existing["id"]
        ).execute()

    inserted = (
        client.table("budget_events")
        .insert(
            {
                "leaid": event.leaid,
                "fiscal_year": event.fiscal_year,
                "status": event.status,
                "topline_amount": event.topline_amount,
                "topline_definition": event.topline_definition,
                "yoy_change_pct": event.yoy_change_pct,
                "yoy_change_dollars": event.yoy_change_dollars,
                "prior_year_baseline": event.prior_year_baseline,
                "event_date": event.event_date,
                "source_document_id": event.source_document_id,
                "extraction_run_id": event.extraction_run_id,
            }
        )
        .execute()
    )
    return inserted.data[0]["id"], True


def get_prior_year_baseline(
    client: Client, leaid: str, fiscal_year: int
) -> float | None:
    """Return the latest non-superseded `actual` topline for the prior year."""
    prior = (
        client.table("budget_events")
        .select("topline_amount")
        .eq("leaid", leaid)
        .eq("fiscal_year", fiscal_year - 1)
        .eq("status", "actual")
        .eq("is_superseded", False)
        .execute()
    )
    if prior.data:
        return float(prior.data[0]["topline_amount"])
    return None


# ──────────────────────────────────────────────────────────────────────
# Phase 7.4: budget_event_components helpers
# ──────────────────────────────────────────────────────────────────────


# The 14 canonical categories from the expenditure_category enum
# (migration 0010). Source of truth is the DB enum; this constant gives
# extractors compile-time safety against typos.
CANONICAL_CATEGORIES: frozenset[str] = frozenset({
    "instruction",
    "support_services_student",
    "support_services_instruction",
    "administration",
    "operations_maintenance",
    "transportation",
    "food_service",
    "employee_benefits",
    "capital_outlay",
    "debt_service",
    "revenue_federal",
    "revenue_state",
    "revenue_local",
    "other",
})


@dataclass
class ComponentInput:
    """One line-item breakdown row for a budget_event.

    Components describe a subset (or related-but-disjoint dataset) of
    the parent topline. They don't have to sum to the topline — they're
    just labeled sub-aggregates pulled from the same source. Extractors
    decide what's emit-worthy based on the source's level of detail.
    """
    category: str           # must be one of CANONICAL_CATEGORIES
    amount: float
    definition: str | None = None
    line_or_cell_reference: str | None = None

    def __post_init__(self) -> None:
        if self.category not in CANONICAL_CATEGORIES:
            raise ValueError(
                f"Unknown category '{self.category}'. "
                f"Must be one of {sorted(CANONICAL_CATEGORIES)}."
            )


def upsert_components(
    *,
    client: Client,
    budget_event_id: str,
    components: list[ComponentInput],
) -> tuple[int, int, int]:
    """Idempotently sync `budget_event_components` rows for a budget_event.

    Returns (n_inserted, n_updated, n_unchanged). Component rows are
    keyed on (budget_event_id, category) — re-running with identical
    data is a no-op.

    The component table doesn't supersede on update; we just overwrite
    in place. Audit trail of changes lives in extraction_runs +
    supabase_audit (if enabled later) — components are derived data.

    A component for a category we previously emitted but no longer
    have (i.e. the new run dropped it) is NOT auto-deleted. Cleaning up
    stale categories is an explicit operation; in practice extractors
    emit the same set of categories run-over-run so this matters rarely.
    """
    if not components:
        return (0, 0, 0)

    existing_rows = (
        client.table("budget_event_components")
        .select("category, amount, definition, line_or_cell_reference")
        .eq("budget_event_id", budget_event_id)
        .execute()
    ).data or []
    existing: dict[str, dict] = {r["category"]: r for r in existing_rows}

    to_insert: list[dict] = []
    to_update: list[tuple[str, dict]] = []
    n_unchanged = 0

    for c in components:
        payload = {
            "amount": float(c.amount),
            "definition": c.definition,
            "line_or_cell_reference": c.line_or_cell_reference,
        }
        prior = existing.get(c.category)
        if prior is None:
            to_insert.append(
                {
                    "budget_event_id": budget_event_id,
                    "category": c.category,
                    **payload,
                }
            )
        else:
            if (
                float(prior["amount"]) == payload["amount"]
                and prior.get("definition") == payload["definition"]
                and prior.get("line_or_cell_reference") == payload["line_or_cell_reference"]
            ):
                n_unchanged += 1
            else:
                to_update.append((c.category, payload))

    if to_insert:
        client.table("budget_event_components").insert(to_insert).execute()
    for category, payload in to_update:
        (
            client.table("budget_event_components")
            .update(payload)
            .eq("budget_event_id", budget_event_id)
            .eq("category", category)
            .execute()
        )

    return (len(to_insert), len(to_update), n_unchanged)
