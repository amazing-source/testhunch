from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from testhunch.store.base import Params, Row, Session, SqlStore, StoreError


class _SQLiteSession:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def one(self, sql: str, params: Params = ()) -> Row | None:
        row: Row | None = self._conn.execute(sql, params).fetchone()
        return row

    def all(self, sql: str, params: Params = ()) -> list[Row]:
        return self._conn.execute(sql, params).fetchall()

    def run(self, sql: str, params: Params = ()) -> None:
        self._conn.execute(sql, params)

    def many(self, sql: str, rows: Sequence[Params]) -> None:
        self._conn.executemany(sql, rows)

    def script(self, sql: str) -> None:
        # With autocommit=True, executescript() runs inside our open transaction instead of
        # committing it first, so a failing migration still rolls back as a whole.
        self._conn.executescript(sql)


class SQLiteStore(SqlStore):
    dialect = "sqlite"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def _migrations_table_ddl(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
            ") STRICT;"
        )

    def now_expression(self) -> str:
        return "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

    def _lock_for_migration(self, session: Session) -> None:
        pass  # write sessions already hold SQLite's write lock (BEGIN IMMEDIATE)

    def _lock_repo(self, session: Session, repo: str) -> None:
        pass  # the same write lock

    @contextmanager
    def session(self, write: bool = True) -> Iterator[Session]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # autocommit=True: the sqlite3 module never opens or commits transactions on its own;
        # this method does it explicitly.
        try:
            conn = sqlite3.connect(self.path, autocommit=True, timeout=30)
        except sqlite3.Error as exc:
            raise StoreError(f"could not open SQLite database {self.path}: {exc}") from exc
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN DEFERRED")
            try:
                yield _SQLiteSession(conn)
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            raise StoreError(f"SQLite error: {exc}") from exc
        finally:
            conn.close()
