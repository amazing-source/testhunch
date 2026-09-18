"""The calibrated ranking of docs/adr/0037 and its decision rule."""

from __future__ import annotations

from typing import Any

from benchmarks.calibration import BY_RUNS, CALIBRATED, CANDIDATES, criteria, verdict
from benchmarks.costorder import RANDOM, SHIPPED
from benchmarks.study.engine import PRIMARY
from benchmarks.study.history import BuildHistory
from benchmarks.study.metrics import Trial
from benchmarks.study.rankings import Calibrated, Context
from testhunch.models import CaseResult, Status


def result(
    key: str, status: Status = Status.PASSED, duration: int = 10, flaky: bool = False
) -> CaseResult:
    return CaseResult(key, key, None, None, status, duration, None, flaky=flaky)


def test_a_state_is_the_age_of_the_last_failure_or_how_long_a_test_ran_without_one() -> None:
    builds = BuildHistory()
    builds.record([[result("old", Status.FAILED), result("steady")]])
    for _ in range(9):
        builds.record([[result("old"), result("steady")]])
    builds.record([[result("old"), result("steady"), result("fresh", Status.FAILED)]])

    now = builds.builds
    assert builds.records["fresh"].state(now) == "failed 0, streak 1"
    assert builds.records["old"].state(now) == "failed 8-15"
    assert builds.records["steady"].state(now) == "never, ran 4-15"


def test_each_build_counts_its_runs_by_state_before_learning_from_them() -> None:
    """A test's first run is not counted: before it the test was unknown, and ran first anyway.
    A flaky failure is not counted as a failure, since the rankings are not scored on it; it still
    enters the history, as it does for every ranking, so `b` is then a test that failed."""
    builds = BuildHistory()
    builds.record([[result("a"), result("b")]])
    builds.record([[result("a", Status.FAILED), result("b", Status.FAILED, flaky=True)]])
    builds.record([[result("a"), result("b")]])

    assert builds.state_runs == {"never, ran 1-3|unchanged": 2, "failed 0, streak 1|unchanged": 2}
    assert builds.state_failures == {
        "never, ran 1-3|unchanged": 1,
        "failed 0, streak 1|unchanged": 0,
    }


def _history() -> BuildHistory:
    """`old` fails once, 40 builds back, and never again, while tests that never failed fail for
    the first time now and then: an old failure here predicts less than never having failed."""
    builds = BuildHistory()
    builds.record([[result("old", Status.FAILED, 900), result("quick", duration=9)]])
    for build in range(40):
        jobs = [result("old", duration=900), result("quick", duration=9)]
        # Twenty tests that never fail, one of which fails for the first time every other build.
        jobs += [
            result(f"n{i}", Status.FAILED if i == build % 20 and build % 2 else Status.PASSED)
            for i in range(20)
        ]
        builds.record([jobs])
    return builds


def test_an_old_failure_that_predicts_nothing_no_longer_outranks_a_cheap_silent_test() -> None:
    builds = _history()
    context = Context(builds, list)
    trial = Trial(1, ("old", "quick"), frozenset({"quick"}), {"old": 900, "quick": 9}, ())

    # The priority of `old` is tiny but above zero, and `quick` never failed: the shipped form puts
    # `old` first whatever it costs.
    assert builds.records["old"].priority_at(builds.builds) > 0
    assert Calibrated(CALIBRATED).order(trial, context)[0] == ["quick", "old"]


def test_a_failure_in_the_last_build_runs_first_unless_its_cost_outweighs_its_risk() -> None:
    """`broke` failed in each of the last two builds: its state has failed half the time, the
    tests that never failed about 2.4%. At the same cost it runs first. At a hundred times the
    cost it runs after the quick silent test: 9 ms for a 2.4% chance comes before 900 ms for a 50%
    one, which is Smith's rule and the whole point, and also what can place a repeat failure later
    in the order while reaching it no later in time."""
    builds = _history()
    for _ in range(2):
        builds.record([[result("broke", Status.FAILED, 900), result("even", duration=900)]])
    context = Context(builds, list)
    tests = ("even", "broke", "quick")
    trial = Trial(1, tests, frozenset({"broke"}), {"broke": 900, "even": 900, "quick": 9}, ())

    assert Calibrated(CALIBRATED).order(trial, context)[0] == ["quick", "broke", "even"]


def test_a_state_never_seen_starts_at_the_projects_rate() -> None:
    builds = _history()
    rate = Calibrated(CALIBRATED).rates(builds)
    overall = sum(builds.state_failures.values()) / sum(builds.state_runs.values())

    assert rate("failed 256+") == overall


def test_by_runs_tells_a_young_silent_test_from_an_old_one() -> None:
    builds = BuildHistory()
    for build in range(30):
        # Each build brings a new test that fails on its second run; old ones never fail.
        jobs = [result("veteran")]
        jobs += [result(f"t{build}")]
        if build:
            jobs += [result(f"t{build - 1}", Status.FAILED if build % 3 else Status.PASSED)]
        builds.record([jobs])
    rate = Calibrated(BY_RUNS, by_runs=True).rates(builds)

    assert rate("never, ran 1-3") > rate("never, ran 16-63")
    pooled = Calibrated(CALIBRATED).rates(builds)
    assert pooled("never, ran 1-3") == pooled("never, ran 16-63")


def _fake(red_at: float, primary: float, position: float = 0.6, repeat: float = 0.9) -> Any:
    """Two projects: the shipped ranking, random, and both candidates at the given values."""

    def ranking(red: float, apfdc: float, place: float, again: float) -> dict[str, Any]:
        return {
            "per_trial": {"red_at": [0.1, red], PRIMARY: [again, apfdc], "position": [0.1, place]}
        }

    rankings = {
        SHIPPED: ranking(0.5, 0.8, 0.6, 0.9),
        RANDOM: ranking(0.4, 0.6, 0.45, 0.6),
    }
    for name in CANDIDATES:
        rankings[name] = ranking(red_at, primary, position, repeat)
    return [{"trials": {"first_failure": [False, True]}, "rankings": rankings}] * 2


def test_a_candidate_must_close_half_the_time_gap_to_random_at_little_cost() -> None:
    # The shipped ranking turns red at 0.5 on first failures, random at 0.4: half the gap is 0.05.
    # The primary also averages the repeat job, so it moves by half of what the first failure does.
    good = _fake(red_at=0.44, primary=0.8, repeat=0.9)
    slow = _fake(red_at=0.46, primary=0.8)
    dear = _fake(red_at=0.44, primary=0.79)
    later = _fake(red_at=0.44, primary=0.8, position=0.61)

    assert criteria(good, CALIBRATED)["passes"] and verdict(good) in CANDIDATES
    assert not criteria(slow, CALIBRATED)["sooner"]
    assert not criteria(dear, CALIBRATED)["affordable"]
    assert not criteria(later, CALIBRATED)["not_later"]
    assert verdict(slow) is verdict(dear) is verdict(later) is None


def test_a_streak_tells_a_broken_test_from_one_that_failed_once() -> None:
    """Only a failure in the build just before carries a streak. A ranking without `streaks` reads
    the state up to the comma, so the rates of ADR 0037's candidates do not change."""
    builds = BuildHistory()
    builds.record([[result("broken"), result("once")]])
    for build in range(5):
        builds.record(
            [
                [
                    result("broken", Status.FAILED),
                    result("once", Status.FAILED if build == 4 else Status.PASSED),
                ]
            ]
        )
    now = builds.builds

    assert builds.records["broken"].state(now) == "failed 0, streak 4+"
    assert builds.records["once"].state(now) == "failed 0, streak 1"
    plain = Calibrated(CALIBRATED)
    assert plain.coarse("failed 0, streak 4+") == plain.coarse("failed 0, streak 1") == "failed 0"
    split = Calibrated("s", streaks=True)
    assert split.coarse("failed 0, streak 4+") != split.coarse("failed 0, streak 1")


def test_each_step_replays_the_shipped_ranking_its_candidates_and_the_references() -> None:
    from benchmarks.calibration import STEPS, rankings

    for step, (_, chosen) in STEPS.items():
        names = [ranking.name for ranking in rankings(step)]
        assert names[0] == SHIPPED and RANDOM in names, step
        assert [c.name for c in chosen] == names[1 : 1 + len(chosen)], step
    assert [c.name for c in STEPS["adr-0037"][1]] == list(CANDIDATES)


def test_the_diagnosis_groups_states_by_the_age_of_the_last_failure() -> None:
    from benchmarks.repeats import group

    assert group("never, ran 4-15") == "never failed"
    assert group("failed 0, streak 4+") == "failed 0"
    assert group("failed 1") == "failed 1"
    assert group("failed 4-7") == "failed 2-7"
    assert group("failed 32-63") == "failed 8-63"
    assert group("failed 256+") == "failed 64+"
