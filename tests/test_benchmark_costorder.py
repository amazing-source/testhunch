"""Where the cost decides the order, and the variants of docs/adr/0036."""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any

import pytest

from benchmarks.costorder import (
    FIRST_GAIN,
    HASH,
    NARROWER,
    PRIMARY_LOSS,
    RISK_ONLY,
    SCORED,
    SHIPPED,
    VARIANTS,
    Diagnosed,
    characterize,
    contributions,
    criteria,
    duration_pairs,
    state_of,
    verdict,
)
from benchmarks.replay import Job
from benchmarks.study.engine import PRIMARY, study
from benchmarks.study.history import BuildHistory
from benchmarks.study.metrics import Trial
from benchmarks.study.projects import STEP_3_KEPT
from benchmarks.study.rankings import Candidate, Context, tie
from testhunch.models import CaseResult, Status

SLOW, QUICK = "tests/test_slow.py::slow", "tests/test_quick.py::quick"


def result(
    key: str, status: Status = Status.PASSED, duration: int | None = 10, file: str | None = None
) -> CaseResult:
    return CaseResult(key, key, None, file, status, duration, None)


def variant(name: str) -> Candidate:
    return next(candidate for candidate in VARIANTS if candidate.name == name)


def two_silent_tests() -> BuildHistory:
    """A slow and a quick test, both run twice, neither ever failed."""
    builds = BuildHistory()
    for _ in range(2):
        builds.record([[result(SLOW, duration=900), result(QUICK, duration=9)]])
    return builds


def job_where_the_hash_puts(first: str, second: str) -> int:
    """The first job id whose tie-break hash orders `first` before `second`."""
    return next(j for j in itertools.count(1) if tie(j, first) < tie(j, second))


def test_a_slow_test_that_never_failed_is_not_placed_last_for_its_cost_alone() -> None:
    """The case docs/adr/0036 exists for: both tests score zero, and only the cost separates them.

    The shipped ranking runs the quick one first on every job. Each narrower variant lets the hash
    decide, so on a job where the hash favours the slow test, it goes first.
    """
    builds = two_silent_tests()
    context = Context(builds, list)
    job = job_where_the_hash_puts(SLOW, QUICK)
    trial = Trial(job, (QUICK, SLOW), frozenset({SLOW}), {SLOW: 900, QUICK: 9}, ())

    assert STEP_3_KEPT.order(trial, context)[0] == [QUICK, SLOW]
    for name in (HASH, *NARROWER):
        assert variant(name).order(trial, context)[0] == [SLOW, QUICK], name


def test_the_hash_decides_and_not_a_reversed_cost() -> None:
    """On a job where the hash favours the quick test, the variants run it first: no rule of
    theirs prefers slow tests, they only stop preferring quick ones."""
    builds = two_silent_tests()
    context = Context(builds, list)
    job = job_where_the_hash_puts(QUICK, SLOW)
    trial = Trial(job, (SLOW, QUICK), frozenset({SLOW}), {SLOW: 900, QUICK: 9}, ())

    for name in (HASH, *NARROWER):
        assert variant(name).order(trial, context)[0] == [QUICK, SLOW], name


def test_the_cost_still_orders_tests_whose_history_estimates_a_risk() -> None:
    """Two tests that failed in the same build have the same priority: the cost must still put the
    quick one first, under every variant, or the correction has removed the cost everywhere."""
    builds = BuildHistory()
    builds.record([[result(SLOW, Status.FAILED, 900), result(QUICK, Status.FAILED, 9)]])
    builds.record([[result(SLOW, duration=900), result(QUICK, duration=9)]])
    context = Context(builds, list)
    job = job_where_the_hash_puts(SLOW, QUICK)
    trial = Trial(job, (SLOW, QUICK), frozenset({SLOW}), {SLOW: 900, QUICK: 9}, ())

    for candidate in (STEP_3_KEPT, *VARIANTS):
        assert candidate.order(trial, context)[0] == [QUICK, SLOW], candidate.name


def test_only_the_last_variant_drops_the_cost_of_a_test_whose_file_changed() -> None:
    """Both tests never failed and both files changed. Their score is the signal, which the shipped
    ranking and `cost-if-scored` divide by the cost; `cost-if-risk` does not, since no failure
    risk is estimated, and leaves them to the hash."""
    builds = BuildHistory()
    files = {SLOW: "tests/test_slow.py", QUICK: "tests/test_quick.py"}
    for _ in range(2):
        builds.record(
            [
                [
                    result(SLOW, duration=900, file=files[SLOW]),
                    result(QUICK, duration=9, file=files[QUICK]),
                ]
            ]
        )
    context = Context(builds, list)
    job = job_where_the_hash_puts(SLOW, QUICK)
    trial = Trial(
        job, (SLOW, QUICK), frozenset({SLOW}), {SLOW: 900, QUICK: 9}, tuple(files.values())
    )

    assert STEP_3_KEPT.order(trial, context)[0] == [QUICK, SLOW]
    assert variant(SCORED).order(trial, context)[0] == [QUICK, SLOW]
    assert variant(RISK_ONLY).order(trial, context)[0] == [SLOW, QUICK]


def test_the_duration_decides_only_pairs_of_equal_score_and_unequal_cost() -> None:
    keys = [
        (-0.0, 5.0, 1, 0.0, b"a"),
        (-0.0, 5.0, 1, 0.0, b"b"),  # same score, same cost: the duration decides nothing
        (-0.0, 9.0, 1, 0.0, b"c"),
        (-0.3, 1.0, 1, 0.0, b"d"),  # alone at its score
    ]

    # Of the three zero-score tests, the pairs (a, c) and (b, c).
    assert duration_pairs(keys) == 2
    assert duration_pairs([(key[0], 0.0, *key[2:]) for key in keys]) == 0


def test_every_known_test_is_in_one_of_four_states() -> None:
    risky, changed, silent = "tests/test_r.py::r", "tests/test_c.py::c", "tests/test_s.py::s"
    faded = "tests/test_f.py::f"
    builds = BuildHistory()
    builds.record([[result(faded, Status.FAILED), result(changed), result(silent)]])
    for _ in range(463):
        builds.record([[result(faded), result(changed), result(silent)]])
    builds.record([[result(risky, Status.FAILED)]])
    context = Context(builds, list)

    assert state_of(risky, context, score=0.1) == "risk"
    assert state_of(changed, context, score=0.05) == "signal"
    # It did fail, 464 builds ago: the priority underflowed to exactly zero (docs/adr/0018).
    assert builds.records[faded].priority_at(builds.builds) == 0.0
    assert state_of(faded, context, score=0.0) == "faded"
    assert state_of(silent, context, score=0.0) == "silent"


def test_the_failing_test_is_placed_among_the_zero_score_tests_in_tests_and_in_time() -> None:
    """Three silent tests of 10, 20 and 70 ms; the 20 ms one fails. It is the middle one counted
    in tests, and a quarter of the way through counted in time: 10 of 100 ms before it, half of
    its own 20 counted."""
    tests = ("a", "b", "c")
    builds = BuildHistory()
    builds.record([[result("a", duration=9), result("b", duration=19), result("c", duration=69)]])
    context = Context(builds, list)
    trial = Trial(7, tests, frozenset({"b"}), {"a": 9, "b": 19, "c": 69}, ())
    unknown, keys = STEP_3_KEPT.keys(trial, context)
    order = unknown + sorted(keys, key=keys.__getitem__)

    found = characterize(trial, context, order, list(keys), keys)

    assert found["first"] == "silent"
    assert found["states"] == {"risk": 0, "signal": 0, "faded": 0, "silent": 3}
    assert found["first_percentile"] == 0.5
    assert found["first_time_share"] == pytest.approx((10 + 20 / 2) / 100)
    assert found["pairs"] == {"silent": 3, "failed": 0}


def test_a_nearly_spent_priority_sorts_with_the_zero_scores_once_divided() -> None:
    """A test that failed 459 builds ago still has a priority above zero, about 1e-321, but divided
    by its thousand milliseconds the score underflows to exactly zero. It is a risk test that sorts
    with the tests that never failed, and the zero-score group must be read from the score: counted
    by state, its pairs were once reported as ties between scores above zero."""
    old, never = "tests/test_old.py::old", "tests/test_never.py::never"
    builds = BuildHistory()
    builds.record([[result(old, Status.FAILED, 999), result(never, duration=9)]])
    for _ in range(459):
        builds.record([[result(old, duration=999), result(never, duration=9)]])
    context = Context(builds, list)
    trial = Trial(1, (old, never), frozenset({old}), {old: 999, never: 9}, ())
    unknown, keys = STEP_3_KEPT.keys(trial, context)
    order = unknown + sorted(keys, key=keys.__getitem__)

    found = characterize(trial, context, order, list(keys), keys)

    assert builds.records[old].priority_at(builds.builds) > 0
    assert keys[old][0] == 0
    assert found["states"]["risk"] == 1 and found["first"] == "risk"
    assert found["first_scored_zero"]
    assert found["pairs"] == {"silent": 0, "failed": 1}


def _jobs() -> list[Job]:
    """A small history in which a slow test fails for the first time on the last job."""
    slow = [result("fast", duration=1), result("mid", duration=50), result("slow", duration=400)]
    failing = [
        result("fast", duration=1),
        result("mid", duration=50),
        result("slow", Status.FAILED, duration=400),
    ]
    earlier = [
        result("fast", Status.FAILED, duration=1),
        result("mid", duration=50),
        result("slow", duration=400),
    ]
    runs = [earlier, slow, slow, earlier, failing]
    return [
        Job(job_id, frozenset({f"c{job_id}"}), None, tuple(results))
        for job_id, results in enumerate(runs)
    ]


def _replay() -> dict[str, Any]:
    reference = Diagnosed(STEP_3_KEPT)
    measured = [reference, *(Diagnosed(candidate, reference) for candidate in VARIANTS)]
    result = study(_jobs(), measured)
    result["diagnostics"] = {ranking.name: ranking.rows for ranking in measured}
    return {"project": "a@b", **result}


def test_a_replay_records_what_decided_each_order() -> None:
    replayed = _replay()
    rows = replayed["diagnostics"]

    assert set(rows) == {SHIPPED, *(candidate.name for candidate in VARIANTS)}
    assert all(len(found) == len(replayed["trials"]["job_ids"]) for found in rows.values())
    # The reference classifies; the variants say how far they moved from it.
    assert "first" in rows[SHIPPED][0] and "displaced" not in rows[SHIPPED][0]
    assert all("displaced" in row for row in rows[HASH])


def test_the_contributions_add_up_to_the_difference() -> None:
    replayed = _replay()
    shares = contributions([replayed], SHIPPED, HASH, PRIMARY)
    per_trial = replayed["rankings"]
    shipped = [v for v in per_trial[SHIPPED]["per_trial"][PRIMARY] if v is not None]
    hashed = [v for v in per_trial[HASH]["per_trial"][PRIMARY] if v is not None]

    total = sum(shipped) / len(shipped) - sum(hashed) / len(hashed)
    assert sum(shares.values()) == pytest.approx(total)


def _fake(first: float, primary: float, before_position: float = 0.1) -> dict[str, Any]:
    """Results in which the shipped ranking scores `before_position` on a job that had failed
    before, 0.8 on one that had not, and a variant moves them by `first` and `primary`."""
    trials = {"first_failure": [False, True]}

    def ranking(position: float, fresh: float, apfdc: float) -> dict[str, Any]:
        return {"per_trial": {"position": [position, fresh], PRIMARY: [apfdc, apfdc]}}

    rankings = {SHIPPED: ranking(before_position, 0.8, 0.9)}
    for name in (HASH, *NARROWER):
        rankings[name] = ranking(before_position, 0.8 + first, 0.9 + primary)
    return {"trials": trials, "rankings": rankings, "diagnostics": {}}


def test_a_narrower_variant_must_gain_enough_and_cost_little_enough() -> None:
    enough = _fake(first=-(FIRST_GAIN + 0.001), primary=-(PRIMARY_LOSS - 0.001))
    short = _fake(first=-(FIRST_GAIN - 0.001), primary=0.0)
    dear = _fake(first=-0.2, primary=-(PRIMARY_LOSS + 0.001))

    assert criteria([enough], SCORED)["passes"]
    assert verdict([enough]) in NARROWER
    assert not criteria([short], SCORED)["gains"]
    assert not criteria([dear], SCORED)["affordable"]
    assert verdict([short]) is None and verdict([dear]) is None


def test_a_variant_that_harms_the_jobs_that_had_failed_before_does_not_pass() -> None:
    shipped = _fake(first=-0.2, primary=0.0)
    worse = _with_position(shipped, SCORED, before=0.1 + 0.005)

    assert not criteria([worse], SCORED)["harmless"]


def _with_position(results: dict[str, Any], name: str, before: float) -> dict[str, Any]:
    changed = {**results, "rankings": dict(results["rankings"])}
    positions = list(changed["rankings"][name]["per_trial"]["position"])
    positions[0] = before
    changed["rankings"][name] = {
        "per_trial": {**changed["rankings"][name]["per_trial"], "position": positions}
    }
    return changed


def test_the_closed_set_is_the_shipped_ranking_with_one_rule_changed_each() -> None:
    assert [candidate.name for candidate in VARIANTS] == [HASH, SCORED, RISK_ONLY]
    for candidate in VARIANTS:
        # The same score everywhere a failure risk is estimated: only the weights of the shipped
        # ranking, and its divisor.
        assert candidate.weights == STEP_3_KEPT.weights
        assert candidate.time_exponent == STEP_3_KEPT.time_exponent
        assert replace(candidate, name=SHIPPED, tie_break="cost", cold_time_exponent=None) == (
            STEP_3_KEPT
        )
