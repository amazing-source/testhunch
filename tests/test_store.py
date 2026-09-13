"""The storage contract. Every test here runs against SQLite and against Postgres."""

from __future__ import annotations

import pytest

from testhunch.models import CaseResult, FileChange, RunInput, Status
from testhunch.store import SqlStore, StoreError, base
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


def test_a_known_file_survives_reports_that_omit_it(store: SqlStore) -> None:
    def ingest_with_file(commit: str, file: str | None) -> str | None:
        result = CaseResult("a", "a", None, file, Status.PASSED, 10, None)
        store.ingest(run(commit, commit, result))
        return store.history(REPO)[0].file

    assert ingest_with_file("c1", "tests/a.py") == "tests/a.py"
    assert ingest_with_file("c2", None) == "tests/a.py"
    assert ingest_with_file("c3", "tests/moved.py") == "tests/moved.py"


def test_ingest_maps_every_result_to_its_own_test_across_lookup_batches(store: SqlStore) -> None:
    count = base._KEYS_PER_QUERY * 2 + 1
    cases = [
        case(f"t{i:05d}", Status.FAILED if i % 100 == 0 else Status.PASSED) for i in range(count)
    ]
    expected_failing = {c.key for c in cases if c.status is Status.FAILED}

    # The first run inserts every test; the second finds them all already recorded.
    for commit in ("c1", "c2"):
        assert store.ingest(run(commit, commit, *cases)).results == count

    history = store.history(REPO)
    assert len(history) == count
    assert {h.key for h in history if h.failures} == expected_failing
    assert {(h.failures, h.executions) for h in history} == {(0, 2), (2, 2)}


def test_flaky_means_passed_and_failed_on_the_same_commit(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("flaky", Status.PASSED), case("broken", Status.FAILED)))
    store.ingest(run("c1", "d2", case("flaky", Status.ERROR), case("broken", Status.FAILED)))
    # Passing on one commit and failing on another is a regression, not flakiness.
    store.ingest(run("c2", "d3", case("regressed", Status.PASSED)))
    store.ingest(run("c3", "d4", case("regressed", Status.FAILED)))

    flaky = store.flaky_tests(REPO)
    assert [(t.key, t.flaky_commits) for t in flaky] == [("flaky", 1)]


def test_a_retry_that_passed_within_one_run_is_flaky(store: SqlStore) -> None:
    retried = CaseResult("retried", "retried", None, None, Status.PASSED, 10, None, flaky=True)
    store.ingest(run("c1", "d1", retried, case("broken", Status.FAILED)))

    flaky = store.flaky_tests(REPO)
    assert [(t.key, t.flaky_commits) for t in flaky] == [("retried", 1)]
    # It passed in the end, so it is not a failure.
    assert [t.key for t in store.failing_tests(REPO)] == ["broken"]


def test_flaky_commits_are_counted_once_whatever_the_evidence(store: SqlStore) -> None:
    retried = CaseResult("t", "t", None, None, Status.PASSED, 10, None, flaky=True)
    # c1: a retry within a run and a failure in another run of the same commit.
    store.ingest(run("c1", "d1", retried))
    store.ingest(run("c1", "d2", case("t", Status.FAILED)))
    # c2: only a retry.
    store.ingest(run("c2", "d3", retried))

    assert [(t.key, t.flaky_commits) for t in store.flaky_tests(REPO)] == [("t", 2)]


def test_migrating_keeps_results_recorded_before_flakiness_was_stored(
    unmigrated_store: SqlStore,
) -> None:
    initial_schema = bundled_migrations(unmigrated_store.dialect)[:1]
    assert unmigrated_store.migrate(initial_schema) == [1]
    with unmigrated_store.session() as s:
        s.run(
            "INSERT INTO runs (repo, commit_sha, report_digest) VALUES (?, ?, ?)",
            (REPO, "c1", "d1"),
        )
        s.run("INSERT INTO tests (repo, test_key, name) VALUES (?, ?, ?)", (REPO, "a", "a"))
        s.run(
            "INSERT INTO results (run_id, test_id, status) "
            "SELECT runs.id, tests.id, 'passed' FROM runs, tests"
        )

    assert 2 in unmigrated_store.migrate()
    assert [h.key for h in unmigrated_store.history(REPO)] == ["a"]
    assert unmigrated_store.flaky_tests(REPO) == []


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
