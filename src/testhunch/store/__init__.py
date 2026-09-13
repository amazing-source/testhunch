"""Storage: one SQL implementation, two databases (SQLite locally, Postgres when hosted)."""

from __future__ import annotations

from testhunch.store.base import SqlStore, StoreError

DEFAULT_DATABASE_URL = "sqlite:///.testhunch/history.db"

__all__ = ["DEFAULT_DATABASE_URL", "SqlStore", "StoreError", "open_store"]


def open_store(url: str) -> SqlStore:
    """Open a store from a URL: sqlite:///relative/or/absolute.db or postgresql://..."""
    if url.startswith("sqlite:///"):
        from testhunch.store.sqlite import SQLiteStore

        return SQLiteStore(url.removeprefix("sqlite:///"))
    if url.startswith(("postgresql://", "postgres://")):
        try:
            from testhunch.store.postgres import PostgresStore
        except ImportError as exc:
            raise StoreError(
                "Postgres support is not installed: pip install 'testhunch[postgres]'"
            ) from exc
        return PostgresStore(url)
    scheme = url.split(":", 1)[0] if ":" in url else url
    # Only the scheme is echoed back: the rest of a database URL can hold a password.
    raise StoreError(
        f"unsupported database URL scheme {scheme!r}: "
        "use sqlite:///path/to/history.db or postgresql://user@host/db"
    )
