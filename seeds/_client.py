"""Re-export the shared Supabase client factory used by extractors."""

from extractors._client import get_client, load_env_file

__all__ = ["get_client", "load_env_file"]
