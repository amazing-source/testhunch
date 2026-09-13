from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import psycopg
from psycopg import IsolationLevel
from psycopg.conninfo import conninfo_to_dict

from testhunch.store.base import Params, Row, Session, SqlStore, StoreError

# Arbitrary but fixed: every testhunch process contends for the same advisory lock.
_MIGRATION_LOCK = 7_265_110_421

# Without connect_timeout psycopg waits 130 s per address before giving up, which stalls the CLI
# and /readyz. Applied only when neither the URL nor PGCONNECT_TIMEOUT sets one.
CONNECT_TIMEOUT_S = 10


def _pg(sql: str) -> str:
    return sql.replace("?", "%s")


class _PostgresSession:
    def __init__(self, conn: psycopg.Connection[Row]) -> None:
        self._conn = conn

    def one(self, sql: str, params: Params = ()) -> Row | None:
        return self._conn.execute(_pg(sql), params or None).fetchone()

    def all(self, sql: str, params: Params = ()) -> list[Row]:
        return self._conn.execute(_pg(sql), params or None).fetchall()

    def run(self, sql: str, params: Params = ()) -> None:
        self._conn.execute(_pg(sql), params or None)

    def many(self, sql: str, rows: Sequence[Params]) -> None:
        if not rows:
            return
        with self._conn.cursor() as cursor:
            cursor.executemany(_pg(sql), rows)

    def script(self, sql: str) -> None:
        # Without parameters psycopg sends a simple query, which may hold several statements.
        self._conn.execute(sql)


class PostgresStore(SqlStore):
    dialect = "postgres"

    def __init__(self, url: str) -> None:
        self.url = url

    @property
    def _migrations_table_ddl(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )

    def _lock_for_migration(self, session: Session) -> None:
        session.one("SELECT pg_advisory_xact_lock(?)", (_MIGRATION_LOCK,))

    @contextmanager
    def session(self, write: bool = True) -> Iterator[Session]:
        try:
            explicit = conninfo_to_dict(self.url).get("connect_timeout") or os.environ.get(
                "PGCONNECT_TIMEOUT"
            )
            conn = psycopg.connect(self.url, connect_timeout=explicit or CONNECT_TIMEOUT_S)
        except psycopg.OperationalError as exc:
            raise StoreError(f"could not connect to Postgres: {exc}") from exc
        try:
            with conn:
                if not write:
                    # One snapshot for the whole read, like SQLite's read transactions.
                    conn.isolation_level = IsolationLevel.REPEATABLE_READ
                    conn.read_only = True
                with conn.transaction():
                    yield _PostgresSession(conn)
        except psycopg.Error as exc:
            raise StoreError(f"Postgres error: {exc}") from exc
