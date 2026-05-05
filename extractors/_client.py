"""Supabase client factory + tiny env loader (no extra deps)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from supabase import Client, create_client

ENV_FILE = Path(__file__).parent.parent / ".env.local"


def load_env_file() -> None:
    """Read .env.local and merge into os.environ (existing values win)."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_client() -> Client:
    load_env_file()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        sys.exit(
            "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY. "
            "Populate .env.local — see .env.example."
        )
    return create_client(url, key)
