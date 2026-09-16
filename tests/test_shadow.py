"""What a recorded ranking would have missed (docs/adr/0006). No database needed."""

from __future__ import annotations

from testhunch.models import ShadowResult, ShadowRun, Status
from testhunch.shadow import (
    FILL,
    OVERSIZED,
    PACKINGS,
    PREFIX,
    budget_ranks,
    evaluate,
    is_learning_run,
)


def result(
    key: str,
    status: Status = Status.PASSED,
    duration_ms: int | None = 10,
    flaky: bool = False,
    attempts: int | None = 1,
) -> ShadowResult:
    return ShadowResult(key, status, flaky, duration_ms, attempts)


def ranked(
    ranking: str,
    *results: ShadowResult,
    run_id: int = 1,
    expected: dict[str, float] | None = None,
) -> ShadowRun:
    """`ranked("abcd", ...)`: tests a, b, c, d in that order.

    Every test is expected to cost the same unless `expected` says otherwise, so a time budget cuts
    where a budget of tests would and each test below says what it means to say.
    """
    positions = {key: pos for pos, key in enumerate(ranking, start=1)}
    return ShadowRun(run_id, positions, results, expected or dict.fromkeys(positions, 10.0))


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


def test_failures_confirmed_by_retries_are_counted_apart() -> None:
    run = ranked(
        "abcd",
        result("a", Status.FAILED, attempts=3),  # failed on all three attempts: confirmed
        result("d", Status.FAILED, attempts=1),  # ran once: may be flaky
        *passing("bc"),
    )
    (point,) = evaluate([run], fractions=(0.25,))
    assert (point.failures, point.caught_failures) == (2, 1)
    assert (point.confirmed_failures, point.caught_confirmed_failures) == (1, 1)
    assert (point.confirmed_failing_runs, point.caught_confirmed_runs) == (1, 1)


def test_a_run_whose_only_confirmed_failure_is_missed_is_a_missed_confirmed_run() -> None:
    run = ranked(
        "abcd",
        result("a", Status.FAILED, attempts=1),
        result("d", Status.ERROR, attempts=2),
        *passing("bc"),
    )
    (point,) = evaluate([run], fractions=(0.25,))
    assert (point.caught_runs, point.confirmed_failing_runs, point.caught_confirmed_runs) == (
        1,
        1,
        0,
    )


def test_unknown_attempts_and_flaky_results_are_never_confirmed() -> None:
    run = ranked(
        "abc",
        result("a", Status.FAILED, attempts=None),  # recorded before attempts were stored
        result("b", Status.FAILED, attempts=2, flaky=True),
        *passing("c"),
    )
    (point,) = evaluate([run], fractions=(1.0,))
    assert (point.failures, point.confirmed_failures, point.confirmed_failing_runs) == (1, 0, 0)


def test_a_budget_is_a_share_of_the_expected_time_not_of_the_tests() -> None:
    # Four tests, 100 ms expected in all: half the time is a, b and c, three of the four tests.
    run = ranked(
        "abcd",
        result("d", Status.FAILED),
        *passing("abc"),
        expected={"a": 10.0, "b": 20.0, "c": 20.0, "d": 50.0},
    )

    (point,) = evaluate([run], fractions=(0.5,))

    assert point.tests_run == 3
    assert (point.failing_runs, point.caught_runs) == (1, 0)  # d costs more than the budget left


def test_the_budget_follows_the_ranking_rather_than_packing_the_time() -> None:
    # After b there are 10 ms left: c would fit, but it is ranked below d, which does not.
    run = ranked(
        "abcd",
        result("c", Status.FAILED),
        *passing("abd"),
        expected={"a": 10.0, "b": 20.0, "d": 50.0, "c": 10.0},
    )

    (point,) = evaluate([run], fractions=(0.4,))

    assert point.tests_run == 2  # a and b, not a, b and c
    assert (point.failing_runs, point.caught_runs) == (1, 0)


def test_a_ranking_recorded_without_expected_times_is_left_out_and_counted() -> None:
    old = ShadowRun(1, {"a": 1, "b": 2}, (result("a", Status.FAILED), result("b")))
    new = ranked("ab", result("a", Status.FAILED), *passing("b"), run_id=2)

    (point,) = evaluate([old, new], fractions=(0.5,))

    # The old run is not guessed at: it is left out of every count, and said so.
    assert point.runs_without_expected_time == 1
    assert (point.runs, point.failing_runs, point.caught_runs) == (1, 1, 1)


def test_the_learning_run_draw_is_the_same_for_every_job_of_a_commit() -> None:
    commit = "3ac647550134d5d2c9b1f0e8a7d6c5b4a3928170"
    draws = {is_learning_run("acme/shop", commit, 0.25) for _ in range(5)}
    assert len(draws) == 1


def test_no_learning_runs_at_zero_and_only_learning_runs_at_one_hundred_percent() -> None:
    commits = [f"{n:040x}" for n in range(200)]
    assert not any(is_learning_run("acme/shop", c, 0.0) for c in commits)
    assert all(is_learning_run("acme/shop", c, 1.0) for c in commits)


def test_about_the_requested_share_of_commits_are_learning_runs() -> None:
    # Deterministic: the same 10 000 commit ids always give the same count.
    commits = [f"{n:040x}" for n in range(10_000)]
    learning = sum(is_learning_run("acme/shop", c, 0.25) for c in commits)
    assert 2300 <= learning <= 2700


def test_the_draw_depends_on_the_repository_too() -> None:
    commits = [f"{n:040x}" for n in range(200)]
    shop = [is_learning_run("acme/shop", c, 0.5) for c in commits]
    blog = [is_learning_run("acme/blog", c, 0.5) for c in commits]
    assert shop != blog


def test_no_runs_means_nothing_measured() -> None:
    (point,) = evaluate([], fractions=(0.1,))
    assert (point.runs, point.failing_runs, point.tests_total, point.time_total_ms) == (0, 0, 0, 0)


# -- the three packing rules (docs/adr/0029) --------------------------------------------------


# Five tests, 100 ms in all, so a budget of 40% allows 40 ms. The third is the one that does not
# fit: 50 ms in OVERSIZED below, which no order could have run, and 30 ms in TOO_LATE, which an
# order that put it first would have run.
OVERSIZE = [10.0, 20.0, 50.0, 10.0, 10.0]
TOO_LATE = [10.0, 20.0, 30.0, 10.0, 30.0]


def test_the_prefix_rule_stops_at_the_first_test_that_does_not_fit() -> None:
    """The fourth would fit in what is left. It is ranked below the third, so it does not run."""
    assert budget_ranks(0.4, OVERSIZE, PREFIX) == {1, 2}


def test_the_oversized_rule_passes_over_what_no_order_could_have_run() -> None:
    """50 ms cannot fit in a 40 ms budget however early it comes, so it ends nothing."""
    assert budget_ranks(0.4, OVERSIZE, OVERSIZED) == {1, 2, 4}


def test_the_oversized_rule_still_stops_at_a_test_that_would_have_fitted() -> None:
    """30 ms would have fitted at the top, so passing over it is a choice the order forbids."""
    assert budget_ranks(0.4, TOO_LATE, OVERSIZED) == {1, 2}


def test_the_fill_rule_keeps_going_past_everything_that_does_not_fit() -> None:
    assert budget_ranks(0.4, TOO_LATE, FILL) == {1, 2, 4}


def test_every_rule_runs_the_first_choice_of_the_ranking_whatever_it_costs() -> None:
    """A budget that runs nothing measures nothing, and the rules must differ only after that."""
    for packing in PACKINGS:
        assert budget_ranks(0.1, [90.0, 5.0, 5.0], packing) == {1}, packing


def test_no_ranked_test_means_no_rank_to_run() -> None:
    for packing in PACKINGS:
        assert budget_ranks(0.5, [], packing) == set(), packing


def test_a_wider_budget_can_run_fewer_tests_than_a_narrower_one() -> None:
    """Filling is first-fit, and first-fit is not monotone in the capacity (docs/adr/0029).

    Measured on the development projects: the wider budget drops a test in about a quarter of jobs.
    This pins the property so that a change to the rule shows up here rather than in a user's CI.
    """
    durations = [1.0, 4.0, 1.0, 1.0]  # 7 in all

    # Half of 7 is 3.5: the second test needs 4 and never fits, so the last two run instead.
    assert budget_ranks(0.5, durations, FILL) == {1, 3, 4}
    # Three quarters is 5.25: the second test fits, takes the room, and pushes both of them out.
    assert budget_ranks(0.75, durations, FILL) == {1, 2}

    # A prefix cannot do this: a longer prefix contains the shorter one.
    assert budget_ranks(0.5, durations, PREFIX) <= budget_ranks(0.75, durations, PREFIX)


def test_the_shipped_budget_passes_over_what_it_could_never_have_afforded() -> None:
    """The rule of ADR 0029, and changing it changes every published budget table."""
    run = ranked(
        "abdc",  # the failing c is ranked last, behind the expensive d
        result("c", Status.FAILED),
        *passing("abd"),
        expected={"a": 10.0, "b": 20.0, "d": 50.0, "c": 10.0},
    )

    # 90 ms in all, so half allows 45 ms: a and b spend 30, d needs 50 and does not fit, and the
    # failing c needs only 10. Whether it runs is the whole question.
    (default,) = evaluate([run], fractions=(0.5,))
    (prefix,) = evaluate([run], fractions=(0.5,), packing=PREFIX)
    (oversized,) = evaluate([run], fractions=(0.5,), packing=OVERSIZED)
    (fill,) = evaluate([run], fractions=(0.5,), packing=FILL)

    assert default == oversized
    # d needs 50 ms of a 45 ms budget: no order could have run it, so c runs and the build is red.
    assert (prefix.caught_runs, oversized.caught_runs, fill.caught_runs) == (0, 1, 1)
