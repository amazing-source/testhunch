"""The storage contract and its SQL, written once for both SQLite and Postgres.

Queries use `?` placeholders; the Postgres store rewrites them to `%s`. So queries must not
contain a literal `?` or `%`. Anything that genuinely differs between the two databases (types,
defaults, locking) lives in the per-dialect migration files and store classes.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextlib import AbstractContextManager
from importlib import resources
from typing import Any, Protocol

from testhunch.models import (
    CaseHistory,
    FailingTest,
    FileChange,
    FlakyTest,
    IngestOutcome,
    RunInput,
    SlowTest,
)

Row = tuple[Any, ...]
Params = Sequence[Any]
Migration = tuple[int, str]

_MIGRATION_FILE = re.compile(r"(\d{4})_[a-z0-9_]+\.sql")
_FAILED = "('failed', 'error')"

# Test keys per id lookup during ingest, well below the bound-parameter limits of both databases
# (32766 for SQLite, 65535 for Postgres).
_KEYS_PER_QUERY = 500


class StoreError(RuntimeError):
    """The database could not be opened, migrated or written to."""


class Session(Protocol):
    """Queries inside one transaction."""

    def one(self, sql: str, params: Params = ()) -> Row | None: ...
    def all(self, sql: str, params: Params = ()) -> list[Row]: ...
    def run(self, sql: str, params: Params = ()) -> None: ...
    def many(self, sql: str, rows: Sequence[Params]) -> None: ...
    def script(self, sql: str) -> None: ...


def bundled_migrations(dialect: str) -> list[Migration]:
    """Migration scripts shipped in the package, ordered by version."""
    folder = resources.files("testhunch.store").joinpath("migrations", dialect)
    found: dict[int, str] = {}
    for entry in folder.iterdir():
        match = _MIGRATION_FILE.fullmatch(entry.name)
        if not match:
            continue
        version = int(match.group(1))
        if version in found:
            raise StoreError(f"two {dialect} migrations share version {version}")
        found[version] = entry.read_text(encoding="utf-8")
    return sorted(found.items())


class SqlStore(ABC):
    dialect: str

    @abstractmethod
    def session(self, write: bool = True) -> AbstractContextManager[Session]:
        """Open a transaction: committed if the block succeeds, rolled back if it raises."""

    @abstractmethod
    def _lock_for_migration(self, session: Session) -> None:
        """Stop two processes from migrating the same database at the same time."""

    @property
    @abstractmethod
    def _migrations_table_ddl(self) -> str: ...

    # -- schema ---------------------------------------------------------------------------

    def migrate(self, migrations: Sequence[Migration] | None = None) -> list[int]:
        """Apply pending migrations in a single transaction. Returns the versions applied."""
        pending = bundled_migrations(self.dialect) if migrations is None else list(migrations)
        applied: list[int] = []
        with self.session() as s:
            self._lock_for_migration(s)
            s.script(self._migrations_table_ddl)
            done = {int(row[0]) for row in s.all("SELECT version FROM schema_migrations")}
            for version, sql in pending:
                if version in done:
                    continue
                try:
                    s.script(sql)
                except Exception as exc:
                    raise StoreError(f"migration {version:04d} failed: {exc}") from exc
                s.run("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
                applied.append(version)
        return applied

    def ping(self) -> None:
        with self.session(write=False) as s:
            s.one("SELECT 1")

    # -- writes ---------------------------------------------------------------------------

    def ingest(self, run: RunInput) -> IngestOutcome:
        """Record one run. Ingesting the same reports for the same commit twice is a no-op."""
        keys = [case.key for case in run.results]
        if len(keys) != len(set(keys)):
            raise ValueError("run contains duplicate test keys; collapse results first")

        with self.session() as s:
            row = s.one(
                "INSERT INTO runs (repo, commit_sha, branch, base_sha, report_digest) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (repo, commit_sha, report_digest) DO NOTHING RETURNING id",
                (run.repo, run.commit_sha, run.branch, run.base_sha, run.report_digest),
            )
            if row is None:
                existing = s.one(
                    "SELECT id FROM runs WHERE repo = ? AND commit_sha = ? AND report_digest = ?",
                    (run.repo, run.commit_sha, run.report_digest),
                )
                if existing is None:  # pragma: no cover - the conflicting row must exist
                    raise StoreError("run conflicted but could not be found")
                return IngestOutcome(run_id=int(existing[0]), created=False, results=0)

            run_id = int(row[0])
            # One batch of upserts, then the ids looked up in chunks, instead of a round trip
            # per test. A known file is only rewritten when the report names a different one.
            s.many(
                "INSERT INTO tests (repo, test_key, name, suite, file) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (repo, test_key) DO UPDATE SET file = excluded.file "
                "WHERE excluded.file IS NOT NULL "
                "AND (tests.file IS NULL OR tests.file <> excluded.file)",
                [(run.repo, case.key, case.name, case.suite, case.file) for case in run.results],
            )
            test_ids = self._test_ids(s, run.repo, keys)
            s.many(
                "INSERT INTO results "
                "(run_id, test_id, status, duration_ms, occurrences, message, flaky) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        test_ids[case.key],
                        case.status.value,
                        case.duration_ms,
                        case.occurrences,
                        case.message,
                        case.flaky,
                    )
                    for case in run.results
                ],
            )
            s.many(
                "INSERT INTO run_changes (run_id, path, change_type, old_path) VALUES (?, ?, ?, ?)",
                [(run_id, c.path, c.change_type, c.old_path) for c in run.changes],
            )
        return IngestOutcome(run_id=run_id, created=True, results=len(run.results))

    @staticmethod
    def _test_ids(s: Session, repo: str, keys: Sequence[str]) -> dict[str, int]:
        ids: dict[str, int] = {}
        for start in range(0, len(keys), _KEYS_PER_QUERY):
            chunk = keys[start : start + _KEYS_PER_QUERY]
            placeholders = ", ".join("?" * len(chunk))
            for test_id, key in s.all(
                f"SELECT id, test_key FROM tests WHERE repo = ? AND test_key IN ({placeholders})",
                (repo, *chunk),
            ):
                ids[key] = int(test_id)
        if len(ids) != len(keys):  # pragma: no cover - every key was upserted just before
            raise StoreError("some tests were not recorded")
        return ids

    # -- reads ----------------------------------------------------------------------------

    def run_count(self, repo: str) -> int:
        with self.session(write=False) as s:
            row = s.one("SELECT COUNT(*) FROM runs WHERE repo = ?", (repo,))
        return int(row[0]) if row else 0

    def run_changes(self, run_id: int) -> list[FileChange]:
        with self.session(write=False) as s:
            rows = s.all(
                "SELECT path, change_type, old_path FROM run_changes WHERE run_id = ? "
                "ORDER BY path",
                (run_id,),
            )
        return [FileChange(path, change_type, old_path) for path, change_type, old_path in rows]

    def flaky_tests(self, repo: str, limit: int = 10) -> list[FlakyTest]:
        """Tests that passed and failed on the same commit, most often first.

        Either across runs of the commit (ADR 0004) or within one run's retries (ADR 0005).
        """
        with self.session(write=False) as s:
            rows = s.all(
                f"""
                WITH per_commit AS (
                    SELECT res.test_id,
                           r.commit_sha,
                           SUM(CASE WHEN res.status = 'passed' THEN 1 ELSE 0 END) AS passes,
                           SUM(CASE WHEN res.status IN {_FAILED} THEN 1 ELSE 0 END) AS failures,
                           SUM(CASE WHEN res.flaky THEN 1 ELSE 0 END) AS flaky_results
                    FROM results res
                    JOIN runs r ON r.id = res.run_id
                    WHERE r.repo = ?
                    GROUP BY res.test_id, r.commit_sha
                )
                SELECT t.test_key, COUNT(*) AS flaky_commits
                FROM per_commit pc
                JOIN tests t ON t.id = pc.test_id
                WHERE (pc.passes > 0 AND pc.failures > 0) OR pc.flaky_results > 0
                GROUP BY t.test_key
                ORDER BY flaky_commits DESC, t.test_key
                LIMIT ?
                """,
                (repo, limit),
            )
        return [FlakyTest(key, int(commits)) for key, commits in rows]

    def slowest_tests(self, repo: str, last_runs: int = 50, limit: int = 10) -> list[SlowTest]:
        with self.session(write=False) as s:
            rows = s.all(
                """
                WITH recent AS (SELECT id FROM runs WHERE repo = ? ORDER BY id DESC LIMIT ?)
                SELECT t.test_key, AVG(res.duration_ms) AS avg_ms, COUNT(*) AS samples
                FROM results res
                JOIN recent ON recent.id = res.run_id
                JOIN tests t ON t.id = res.test_id
                WHERE res.duration_ms IS NOT NULL AND res.status <> 'skipped'
                GROUP BY t.test_key
                ORDER BY avg_ms DESC, t.test_key
                LIMIT ?
                """,
                (repo, last_runs, limit),
            )
        return [SlowTest(key, float(avg), int(samples)) for key, avg, samples in rows]

    def failing_tests(self, repo: str, last_runs: int = 50, limit: int = 10) -> list[FailingTest]:
        with self.session(write=False) as s:
            rows = s.all(
                f"""
                WITH recent AS (SELECT id FROM runs WHERE repo = ? ORDER BY id DESC LIMIT ?)
                SELECT t.test_key,
                       SUM(CASE WHEN res.status IN {_FAILED} THEN 1 ELSE 0 END) AS failures,
                       COUNT(*) AS executions
                FROM results res
                JOIN recent ON recent.id = res.run_id
                JOIN tests t ON t.id = res.test_id
                WHERE res.status <> 'skipped'
                GROUP BY t.test_key
                HAVING SUM(CASE WHEN res.status IN {_FAILED} THEN 1 ELSE 0 END) > 0
                ORDER BY failures DESC, t.test_key
                LIMIT ?
                """,
                (repo, last_runs, limit),
            )
        return [FailingTest(key, int(f), int(n)) for key, f, n in rows]

    def history(self, repo: str, last_runs: int = 50) -> list[CaseHistory]:
        """Per-test failure history over the most recent runs, for the prioritizer."""
        # Two queries that must agree on which runs are "recent": read sessions are snapshot
        # transactions in both stores, so a run ingested in between cannot appear in only one.
        with self.session(write=False) as s:
            recent = [
                int(row[0])
                for row in s.all(
                    "SELECT id FROM runs WHERE repo = ? ORDER BY id DESC LIMIT ?",
                    (repo, last_runs),
                )
            ]
            if not recent:
                return []
            rows = s.all(
                f"""
                WITH recent AS (SELECT id FROM runs WHERE repo = ? ORDER BY id DESC LIMIT ?)
                SELECT t.test_key,
                       t.file,
                       SUM(CASE WHEN res.status IN {_FAILED} THEN 1 ELSE 0 END) AS failures,
                       COUNT(*) AS executions,
                       MAX(CASE WHEN res.status IN {_FAILED} THEN res.run_id END) AS last_failed
                FROM results res
                JOIN recent ON recent.id = res.run_id
                JOIN tests t ON t.id = res.test_id
                WHERE res.status <> 'skipped'
                GROUP BY t.test_key, t.file
                ORDER BY t.test_key
                """,
                (repo, last_runs),
            )
        position = {run_id: index for index, run_id in enumerate(recent)}
        return [
            CaseHistory(
                key=key,
                file=file,
                failures=int(failures),
                executions=int(executions),
                runs_since_failure=None if last_failed is None else position[int(last_failed)],
            )
            for key, file, failures, executions, last_failed in rows
        ]
