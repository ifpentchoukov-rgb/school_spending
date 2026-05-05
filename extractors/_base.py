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
