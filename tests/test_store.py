"""The storage contract. Every test here runs against SQLite and against Postgres."""

from __future__ import annotations

import pytest

from testhunch.models import CaseResult, FileChange, RunInput, Status
from testhunch.store import SqlStore, StoreError
from testhunch.store.base import bundled_migrations

REPO = "acme/shop"


def case(key: str, status: Status, duration_ms: int | None = 10) -> CaseResult:
    return CaseResult(key, key, None, None, status, duration_ms, None)


def run(commit: str, digest: str, *cases: CaseResult, repo: str = REPO) -> RunInput:
    return RunInput(repo=repo, commit_sha=commit, report_digest=digest, results=cases)


def test_migrate_twice_is_a_no_op(store: SqlStore) -> None:
    assert store.migrate() == []


def test_failed_migration_leaves_nothing_behind(store: SqlStore) -> None:
    broken = [(9001, "CREATE TABLE half_done (id INTEGER); THIS IS NOT SQL;")]
    with pytest.raises(StoreError, match="migration 9001 failed"):
        store.migrate(broken)

    # Neither the table nor the version was kept: the same table can be created again.
    assert store.migrate([(9002, "CREATE TABLE half_done (id INTEGER);")]) == [9002]


def test_ingest_same_reports_twice_changes_nothing(store: SqlStore) -> None:
    first = store.ingest(run("c1", "d1", case("a", Status.PASSED)))
    again = store.ingest(run("c1", "d1", case("a", Status.PASSED)))

    assert first.created and first.results == 1
    assert not again.created and again.run_id == first.run_id
    assert store.run_count(REPO) == 1


def test_same_reports_on_another_commit_is_a_new_run(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("a", Status.PASSED)))
    assert store.ingest(run("c2", "d1", case("a", Status.PASSED))).created


def test_duplicate_keys_are_rejected(store: SqlStore) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        store.ingest(run("c1", "d1", case("a", Status.PASSED), case("a", Status.FAILED)))


def test_changes_are_recorded(store: SqlStore) -> None:
    changes = (FileChange("src/new.py", "R", old_path="src/old.py"), FileChange("a.py", "M"))
    outcome = store.ingest(
        RunInput(REPO, "c1", "d1", (case("a", Status.PASSED),), base_sha="b0", changes=changes)
    )
    assert store.run_changes(outcome.run_id) == sorted(changes, key=lambda c: c.path)


def test_flaky_means_passed_and_failed_on_the_same_commit(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("flaky", Status.PASSED), case("broken", Status.FAILED)))
    store.ingest(run("c1", "d2", case("flaky", Status.ERROR), case("broken", Status.FAILED)))
    # Passing on one commit and failing on another is a regression, not flakiness.
    store.ingest(run("c2", "d3", case("regressed", Status.PASSED)))
    store.ingest(run("c3", "d4", case("regressed", Status.FAILED)))

    flaky = store.flaky_tests(REPO)
    assert [(t.key, t.flaky_commits) for t in flaky] == [("flaky", 1)]


def test_repos_do_not_leak_into_each_other(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("a", Status.PASSED)))
    store.ingest(run("c1", "d2", case("a", Status.FAILED)))
    store.ingest(run("c1", "d1", case("a", Status.FAILED), repo="other/repo"))

    assert store.flaky_tests("other/repo") == []
    assert [t.key for t in store.failing_tests("other/repo")] == ["a"]
    assert store.run_count("other/repo") == 1


def test_slowest_ignores_skipped_and_unknown_durations(store: SqlStore) -> None:
    store.ingest(
        run(
            "c1",
            "d1",
            case("slow", Status.PASSED, 900),
            case("fast", Status.FAILED, 10),
            case("skipped", Status.SKIPPED, 5000),
            case("untimed", Status.PASSED, None),
        )
    )
    store.ingest(run("c2", "d2", case("slow", Status.PASSED, 1100)))

    slowest = store.slowest_tests(REPO)
    assert [(t.key, t.avg_ms, t.samples) for t in slowest] == [
        ("slow", 1000.0, 2),
        ("fast", 10.0, 1),
    ]


def test_failing_counts_only_the_recent_window(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("old_failure", Status.FAILED), case("t", Status.FAILED)))
    store.ingest(run("c2", "d2", case("old_failure", Status.PASSED), case("t", Status.FAILED)))
    store.ingest(run("c3", "d3", case("old_failure", Status.PASSED), case("t", Status.PASSED)))

    failing = store.failing_tests(REPO, last_runs=2)
    assert [(t.key, t.failures, t.executions) for t in failing] == [("t", 1, 2)]


def test_history_counts_runs_since_last_failure(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("a", Status.FAILED), case("b", Status.PASSED)))
    store.ingest(run("c2", "d2", case("a", Status.PASSED), case("b", Status.FAILED)))
    store.ingest(run("c3", "d3", case("a", Status.PASSED), case("b", Status.PASSED)))

    history = {h.key: h for h in store.history(REPO)}
    assert history["a"].runs_since_failure == 2
    assert history["b"].runs_since_failure == 1
    assert (history["a"].failures, history["a"].executions) == (1, 3)


def test_history_of_unknown_repo_is_empty(store: SqlStore) -> None:
    assert store.history("nobody/nothing") == []


def test_ping(store: SqlStore) -> None:
    store.ping()


def test_both_databases_have_the_same_migrations() -> None:
    sqlite_versions = [version for version, _ in bundled_migrations("sqlite")]
    postgres_versions = [version for version, _ in bundled_migrations("postgres")]
    assert sqlite_versions == postgres_versions != []
