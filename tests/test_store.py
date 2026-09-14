"""The storage contract. Every test here runs against SQLite and against Postgres."""

from __future__ import annotations

import random
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from benchmarks.study.history import BuildHistory
from testhunch.models import (
    CaseResult,
    FileChange,
    History,
    RankedTest,
    RunInput,
    ShadowResult,
    Status,
)
from testhunch.prioritize import ALPHA
from testhunch.store import SqlStore, StoreError, base
from testhunch.store.base import BUILD_HISTORY_VERSION, bundled_migrations

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
        return store.history(REPO).cases[0].file

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

    history = store.history(REPO).cases
    assert len(history) == count
    assert {h.key for h in history if h.failures} == expected_failing
    assert {(h.failures, h.builds) for h in history} == {(0, 2), (2, 2)}


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
    assert [h.key for h in unmigrated_store.history(REPO).cases] == ["a"]
    assert unmigrated_store.flaky_tests(REPO) == []


def test_results_recorded_before_attempts_were_stored_have_unknown_attempts(
    unmigrated_store: SqlStore,
) -> None:
    before_attempts = [m for m in bundled_migrations(unmigrated_store.dialect) if m[0] < 4]
    unmigrated_store.migrate(before_attempts)
    with unmigrated_store.session() as s:
        s.run(
            "INSERT INTO runs (repo, commit_sha, report_digest) VALUES (?, ?, ?)",
            (REPO, "c1", "d1"),
        )
        s.run("INSERT INTO tests (repo, test_key, name) VALUES (?, ?, ?)", (REPO, "a", "a"))
        s.run(
            "INSERT INTO results (run_id, test_id, status) "
            "SELECT runs.id, tests.id, 'failed' FROM runs, tests"
        )

    assert 4 in unmigrated_store.migrate()
    with unmigrated_store.session(write=False) as s:
        assert s.all("SELECT attempts FROM results") == [(None,)]  # unknown, not guessed as 1


def ranking(*keys: str) -> list[RankedTest]:
    return [RankedTest(key, float(len(keys) - i), ()) for i, key in enumerate(keys)]


def test_latest_run_id(store: SqlStore) -> None:
    assert store.latest_run_id(REPO) is None
    store.ingest(run("c1", "d1", case("a", Status.PASSED)))
    newest = store.ingest(run("c2", "d2", case("a", Status.PASSED)))
    store.ingest(run("c9", "d9", case("a", Status.PASSED), repo="other/repo"))
    assert store.latest_run_id(REPO) == newest.run_id


def test_a_recorded_ranking_is_compared_with_the_later_run_of_its_commit(store: SqlStore) -> None:
    history = store.ingest(run("c0", "d0", case("a", Status.PASSED), case("b", Status.FAILED)))
    store.record_prediction(REPO, "c1", ranking("b", "a"), last_run_id=history.run_id)
    retried = CaseResult("a", "a", None, None, Status.FAILED, 7, None, flaky=True, attempts=2)
    later = store.ingest(run("c1", "d1", retried, case("b", Status.PASSED, None)))

    (shadow,) = store.shadow_runs(REPO)
    assert shadow.run_id == later.run_id
    assert shadow.positions == {"b": 1, "a": 2}
    assert sorted(shadow.results, key=lambda r: r.key) == [
        ShadowResult("a", Status.FAILED, True, 7, 2),
        ShadowResult("b", Status.PASSED, False, None, 1),
    ]
    assert store.shadow_runs("other/repo") == []


def test_a_ranking_that_had_already_seen_the_run_is_never_used(store: SqlStore) -> None:
    tested = store.ingest(run("c1", "d1", case("a", Status.FAILED)))
    # Recorded after the results were in: it "predicts" a failure it has already seen.
    store.record_prediction(REPO, "c1", ranking("a"), last_run_id=tested.run_id)
    assert store.shadow_runs(REPO) == []


def test_each_run_uses_the_latest_usable_ranking_of_its_commit(store: SqlStore) -> None:
    history = store.ingest(run("c0", "d0", case("a", Status.PASSED), case("b", Status.PASSED)))
    store.record_prediction(REPO, "c1", ranking("a", "b"), last_run_id=history.run_id)
    store.record_prediction(REPO, "c1", ranking("b", "a"), last_run_id=history.run_id)
    store.record_prediction(REPO, "c2", ranking("a"), last_run_id=history.run_id)
    first = store.ingest(run("c1", "d1", case("a", Status.PASSED)))
    second = store.ingest(run("c1", "d2", case("a", Status.FAILED)))  # e.g. another matrix job

    shadow = store.shadow_runs(REPO)
    assert [s.run_id for s in shadow] == [second.run_id, first.run_id]  # newest first
    assert all(s.positions == {"b": 1, "a": 2} for s in shadow)


def test_a_ranking_of_tests_with_no_recorded_result_is_refused(store: SqlStore) -> None:
    history = store.ingest(run("c0", "d0", case("a", Status.PASSED)))
    with pytest.raises(ValueError, match="no recorded result"):
        store.record_prediction(REPO, "c1", ranking("a", "ghost"), last_run_id=history.run_id)
    assert store.shadow_runs(REPO) == []


def test_shadow_runs_are_limited_to_the_most_recent(store: SqlStore) -> None:
    history = store.ingest(run("c0", "d0", case("a", Status.PASSED)))
    for n in range(1, 4):
        store.record_prediction(REPO, f"c{n}", ranking("a"), last_run_id=history.run_id)
        store.ingest(run(f"c{n}", f"d{n}", case("a", Status.PASSED)))

    assert len(store.shadow_runs(REPO, last_runs=2)) == 2


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


def test_history_counts_in_builds_from_the_first(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("a", Status.FAILED), case("b", Status.PASSED)))
    store.ingest(run("c2", "d2", case("a", Status.PASSED), case("b", Status.ERROR)))
    store.ingest(run("c3", "d3", case("a", Status.PASSED), case("b", Status.PASSED)))

    history = store.history(REPO)
    a, b = history.cases
    assert history.builds == 3
    assert (a.key, a.builds, a.failures, a.last_failure, a.priority) == ("a", 3, 1, 0, ALPHA)
    assert (b.key, b.builds, b.failures, b.last_failure) == ("b", 3, 1, 1)


def test_every_run_of_a_commit_is_one_build(store: SqlStore) -> None:
    store.ingest(run("c1", "job-1", case("a", Status.PASSED, 10), case("b", Status.FAILED)))
    store.ingest(run("c1", "job-2", case("a", Status.FAILED, 11), case("b", Status.FAILED)))
    store.ingest(run("c2", "job-1", case("a", Status.PASSED, 20), case("b", Status.PASSED, None)))

    history = store.history(REPO)
    a, b = history.cases
    assert history.builds == 2
    # a failed in one of c1's two runs: one failure in one build, not one in two runs.
    assert (a.builds, a.failures, a.last_failure, a.priority) == (2, 1, 0, ALPHA)
    # c1's mean of 10 and 11 ms is 10.5, rounded half to even: 10, and SQL's ROUND would give 11.
    assert a.mean_duration_ms == (10 + 20) / 2
    # A build with no known duration is left out of the mean.
    assert (b.builds, b.failures, b.mean_duration_ms) == (2, 1, 10.0)


def test_a_late_run_of_an_earlier_commit_joins_its_build(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("late", Status.PASSED), case("early", Status.PASSED)))
    store.ingest(run("c2", "d2", case("late", Status.PASSED), case("early", Status.FAILED)))
    store.ingest(run("c3", "d3", case("late", Status.FAILED), case("early", Status.PASSED)))
    # Another job of c1 arrives last, and fails both tests.
    store.ingest(run("c1", "d4", case("late", Status.FAILED), case("early", Status.FAILED)))

    history = store.history(REPO)
    early, late = history.cases
    assert history.builds == 3
    assert (late.builds, late.failures, late.last_failure) == (3, 2, 2)
    assert (early.builds, early.failures, early.last_failure) == (3, 2, 1)
    # RTPTorrent's priority as of the last failure, over builds 0 and 2, and 0 and 1.
    assert late.priority == pytest.approx(ALPHA + ALPHA * (1 - ALPHA) ** 2)
    assert early.priority == pytest.approx(ALPHA + ALPHA * (1 - ALPHA))


def test_skipped_results_are_left_out_of_the_history_but_their_build_counts(
    store: SqlStore,
) -> None:
    store.ingest(run("c1", "d1", case("a", Status.PASSED), case("s", Status.SKIPPED, 5000)))
    store.ingest(run("c2", "d2", case("a", Status.SKIPPED)))

    history = store.history(REPO)
    assert history.builds == 2
    assert [(c.key, c.builds) for c in history.cases] == [("a", 1)]


def test_history_of_unknown_repo_is_empty(store: SqlStore) -> None:
    store.ingest(run("c1", "d1", case("a", Status.FAILED)))

    assert store.history("nobody/nothing") == History(builds=0, cases=())


def _random_jobs(seed: int) -> list[tuple[str, tuple[CaseResult, ...]]]:
    """Jobs of consecutive commits, each commit with one to three jobs, in the order they ran."""
    rng = random.Random(seed)
    jobs = []
    for commit in range(40):
        for _ in range(rng.choice([1, 1, 2, 3])):
            results = tuple(
                case(
                    f"t{index}",
                    rng.choice([Status.PASSED, Status.PASSED, Status.FAILED, Status.SKIPPED]),
                    rng.choice([None, *range(0, 30)]),
                )
                for index in range(12)
                if rng.random() < 0.8
            )
            jobs.append((f"c{commit}", results))
    return jobs


def test_the_build_history_is_the_study_engines_exactly(store: SqlStore) -> None:
    jobs = _random_jobs(3)
    engine = BuildHistory()
    group: list[tuple[CaseResult, ...]] = []
    for number, (commit, results) in enumerate(jobs):
        store.ingest(run(commit, str(number), *results))
        group.append(results)
        if number + 1 == len(jobs) or jobs[number + 1][0] != commit:
            engine.record(group)
            group = []

    history = store.history(REPO)

    assert history.builds == engine.builds
    assert {c.key for c in history.cases} == set(engine.records)
    for known in history.cases:
        record = engine.records[known.key]
        assert known.builds == record.runs
        assert known.failures == record.failures
        assert known.last_failure == (None if record.last_failure < 0 else record.last_failure)
        # Equal, not approximately: the product replay must give the study's numbers.
        assert known.priority == record.priority
        assert known.mean_duration_ms == record.mean_duration_ms()


def test_concurrent_ingests_of_a_repository_number_their_builds_one_after_another(
    store: SqlStore,
) -> None:
    # Two shards per commit, each with tests of its own, so that no two ingests share a test row.
    shards = [(f"c{index // 2}", f"shard-{index}") for index in range(8)]
    barrier = threading.Barrier(len(shards))

    def ingest(shard: tuple[str, str]) -> None:
        commit, name = shard
        barrier.wait()
        store.ingest(
            run(commit, name, case(f"{name}-a", Status.FAILED), case(f"{name}-b", Status.PASSED))
        )

    with ThreadPoolExecutor(len(shards)) as pool:
        list(pool.map(ingest, shards))

    history = store.history(REPO)
    assert history.builds == 4
    assert len(history.cases) == 16
    assert {(c.builds, c.last_failure is None) for c in history.cases} == {(1, True), (1, False)}
    with store.session(write=False) as s:
        assert s.all("SELECT number FROM builds ORDER BY number") == [(0,), (1,), (2,), (3,)]


def test_the_migration_rebuilds_the_history_kept_at_ingest(store: SqlStore) -> None:
    jobs = _random_jobs(8)
    rng = random.Random(8)
    rng.shuffle(jobs)  # late runs too
    for number, (commit, results) in enumerate(jobs):
        store.ingest(run(commit, str(number), *results))
    kept = store.history(REPO)
    with store.session() as s:
        s.script("DROP TABLE test_history; DROP TABLE build_tests; DROP TABLE builds;")
        s.run("DELETE FROM schema_migrations WHERE version = ?", (BUILD_HISTORY_VERSION,))

    assert store.migrate() == [BUILD_HISTORY_VERSION]
    assert store.history(REPO) == kept
    assert kept.builds == 40


def test_ping(store: SqlStore) -> None:
    store.ping()


def test_both_databases_have_the_same_migrations() -> None:
    sqlite_versions = [version for version, _ in bundled_migrations("sqlite")]
    postgres_versions = [version for version, _ in bundled_migrations("postgres")]
    assert sqlite_versions == postgres_versions != []
