"""What a recorded ranking would have missed (docs/adr/0006). No database needed."""

from __future__ import annotations

from testhunch.models import ShadowResult, ShadowRun, Status
from testhunch.shadow import evaluate


def result(
    key: str, status: Status = Status.PASSED, duration_ms: int | None = 10, flaky: bool = False
) -> ShadowResult:
    return ShadowResult(key, status, flaky, duration_ms)


def ranked(ranking: str, *results: ShadowResult, run_id: int = 1) -> ShadowRun:
    """`ranked("abcd", ...)`: tests a, b, c, d in that order."""
    return ShadowRun(run_id, {key: pos for pos, key in enumerate(ranking, start=1)}, results)


def passing(keys: str) -> list[ShadowResult]:
    return [result(key) for key in keys]


def test_a_failure_inside_the_budget_is_caught() -> None:
    run = ranked("abcd", result("a", Status.FAILED), *passing("bcd"))
    (point,) = evaluate([run], fractions=(0.25,))
    assert (point.failing_runs, point.caught_runs) == (1, 1)
    assert (point.failures, point.caught_failures) == (1, 1)


def test_a_failure_outside_the_budget_is_missed() -> None:
    run = ranked("abcd", result("d", Status.ERROR), *passing("abc"))
    (point,) = evaluate([run], fractions=(0.25,))
    assert (point.failing_runs, point.caught_runs) == (1, 0)
    assert (point.failures, point.caught_failures) == (1, 0)


def test_one_selected_failure_catches_the_run_but_not_every_failure() -> None:
    run = ranked("abcd", result("a", Status.FAILED), result("d", Status.FAILED), *passing("bc"))
    (point,) = evaluate([run], fractions=(0.25,))
    assert (point.caught_runs, point.caught_failures, point.failures) == (1, 1, 2)


def test_the_budget_rounds_up_so_at_least_one_ranked_test_runs() -> None:
    run = ranked("abc", result("a", Status.FAILED), *passing("bc"))
    (point,) = evaluate([run], fractions=(0.1,))  # 10% of 3 tests
    assert (point.caught_runs, point.tests_run) == (1, 1)


def test_tests_the_ranking_did_not_know_always_run() -> None:
    run = ranked("ab", result("new", Status.FAILED), *passing("ab"))
    (point,) = evaluate([run], fractions=(0.5,))
    assert (point.caught_runs, point.caught_failures) == (1, 1)
    assert (point.tests_run, point.tests_total) == (2, 3)  # "a" and the unknown "new"


def test_flaky_and_skipped_results_are_not_failures_to_catch() -> None:
    run = ranked(
        "abcd",
        result("d", Status.FAILED, flaky=True),
        result("c", Status.SKIPPED),
        *passing("ab"),
    )
    (point,) = evaluate([run], fractions=(0.25,))
    assert (point.failing_runs, point.failures) == (0, 0)
    assert point.tests_total == 3  # the skipped test did not run


def test_share_of_tests_and_of_known_test_time() -> None:
    run = ranked(
        "abcd",
        result("a", duration_ms=10),
        result("b", duration_ms=None),
        result("c", duration_ms=30),
        result("d", duration_ms=60),
    )
    (point,) = evaluate([run], fractions=(0.5,))
    assert (point.tests_run, point.tests_total) == (2, 4)
    # b's duration is unknown, so it counts in neither total: 10 of 100 known milliseconds.
    assert (point.time_run_ms, point.time_total_ms) == (10, 100)


def test_counts_add_up_across_runs_and_follow_the_fractions() -> None:
    caught = ranked("ab", result("a", Status.FAILED), *passing("b"), run_id=1)
    missed = ranked("ab", result("b", Status.FAILED), *passing("a"), run_id=2)
    clean = ranked("ab", *passing("ab"), run_id=3)

    small, everything = evaluate([caught, missed, clean], fractions=(0.5, 1.0))

    assert (small.fraction, small.runs, small.failing_runs, small.caught_runs) == (0.5, 3, 2, 1)
    assert (everything.fraction, everything.caught_runs, everything.tests_run) == (1.0, 2, 6)


def test_no_runs_means_nothing_measured() -> None:
    (point,) = evaluate([], fractions=(0.1,))
    assert (point.runs, point.failing_runs, point.tests_total, point.time_total_ms) == (0, 0, 0, 0)
