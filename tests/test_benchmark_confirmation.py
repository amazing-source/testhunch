"""The candidates and the rule of docs/adr/0038."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benchmarks import confirmation
from benchmarks.confirmation import (
    CANDIDATES,
    LATEST,
    RANDOM,
    SHIPPED,
    TWO_STAGE,
    WITH_FILES,
    criteria,
    difference,
    verdict,
)
from benchmarks.costorder import EVERY
from benchmarks.heldout import NotFrozen
from benchmarks.study.engine import PRIMARY
from benchmarks.study.history import BuildHistory, changed_suffixes, file_changed
from benchmarks.study.metrics import Trial
from benchmarks.study.projects import STEP_3_KEPT
from benchmarks.study.rankings import Calibrated, Context, TwoStage
from testhunch.models import CaseResult, Status


def result(key: str, status: Status = Status.PASSED, duration: int = 10) -> CaseResult:
    return CaseResult(key, key, None, None, status, duration, None)


def test_the_changed_file_signal_is_the_shipped_rankings_own() -> None:
    tails = changed_suffixes(["src/main/java/org/a/Cart.java", "tests/test_user.py"])

    assert file_changed("org.a.Cart", None, tails)
    assert file_changed("t::x", "tests/test_user.py", tails)
    assert not file_changed("org.a.CartTest", None, tails)


def test_a_build_with_unknown_changed_files_counts_in_the_state_and_in_neither_cell() -> None:
    builds = BuildHistory()
    builds.record([[result("x"), result("y")]], ["x.py"])
    builds.record([[result("x", Status.FAILED), result("y")]], [], changed_known=False)
    builds.record([[result("y")]], ["y.py"])

    assert builds.state_runs == {"never, ran 1-3|unknown": 2, "never, ran 1-3|changed": 1}
    rate = Calibrated("f", by_runs=True, files=True).rates(builds)
    # One failure in three runs overall. The state holds all three: (1 + 1/3) / (3 + 1).
    assert rate("never, ran 1-3") == pytest.approx(1 / 3)
    assert rate("never, ran 1-3", "unknown") == rate("never, ran 1-3")
    # The cell holds only the run whose files were known: (0 + 1/3) / (1 + 1).
    assert rate("never, ran 1-3", "changed") == pytest.approx(1 / 6)


def test_a_cell_is_drawn_toward_its_states_rate_by_one_run() -> None:
    builds = BuildHistory()
    builds.record([[result("x"), result("y")]], ["x.py"])
    builds.record([[result("x", Status.FAILED), result("y")]], ["x.py"])
    rate = Calibrated("f", by_runs=True, files=True).rates(builds)
    state = rate("never, ran 1-3")

    assert rate("never, ran 1-3", "changed") == pytest.approx((1 + state) / (1 + 1))
    assert rate("never, ran 1-3", "unchanged") == pytest.approx((0 + state) / (1 + 1))


def _two_stage_history() -> BuildHistory:
    """`recent` failed in the last build and is dear; `stale` failed once, long ago, and many
    tests that never failed fail now and then, so an old failure predicts less than never
    failing."""
    builds = BuildHistory()
    builds.record([[result("stale", Status.FAILED, 9)]])
    for build in range(60):
        jobs = [result("stale", duration=9), result("cheap", duration=1)]
        jobs += [
            result(f"n{i}", Status.FAILED if i == build % 30 and build % 3 == 0 else Status.PASSED)
            for i in range(30)
        ]
        builds.record([jobs])
    builds.record([[result("recent", Status.FAILED, 900), result("cheap", duration=1)]])
    builds.record([[result("recent", Status.FAILED, 900), result("cheap", duration=1)]])
    return builds


def test_two_stages_keep_a_live_risk_first_and_send_a_dead_one_to_the_rest() -> None:
    builds = _two_stage_history()
    context = Context(builds, list)
    tests = ("cheap", "stale", "recent")
    durations = {"cheap": 1, "stale": 9, "recent": 900}
    trial = Trial(1, tests, frozenset({"recent"}), durations, ())
    base = Calibrated(WITH_FILES, by_runs=True, files=True)
    chance = base.probabilities(trial, context, tests)
    line = base.never_rate(builds)

    assert chance["recent"] > line > chance["stale"]
    # The calibrated order alone puts the cheap silent test before the dear recent failure.
    assert base.order(trial, context)[0][0] == "cheap"
    order = TwoStage(TWO_STAGE, STEP_3_KEPT, base).order(trial, context)[0]
    assert order[0] == "recent"
    # The dead old failure is not kept ahead of the cheap silent test any more.
    assert order.index("cheap") < order.index("stale")


def _fake(
    red: float, primary: float, repeat: float, projects: int = 10, shipped_primary: float = 0.8
) -> list[Any]:
    """Projects of two builds each: one job that had failed before, one that had not."""

    def ranking(red_at: float, apfdc: float, again: float) -> dict[str, Any]:
        return {
            "per_trial": {"red_at": [0.1, red_at], PRIMARY: [again, apfdc], "position": [0.1, 0.5]}
        }

    rankings = {
        SHIPPED: ranking(0.5, shipped_primary, 0.9),
        RANDOM: ranking(0.45, 0.6, 0.6),
        LATEST: ranking(0.7, 0.7, 0.85),
    }
    for name in CANDIDATES:
        rankings[name] = ranking(red, primary, repeat)
    trials = {"first_failure": [False, True], "builds": [0, 1]}
    return [{"project": f"p{i}", "trials": trials, "rankings": rankings} for i in range(projects)]


def test_a_candidate_passes_when_all_four_conditions_hold() -> None:
    good = _fake(red=0.3, primary=0.8, repeat=0.9)

    found = criteria(good, TWO_STAGE)
    assert found["sooner_than_random"] and found["above_the_baseline"]
    assert found["not_below_shipped"] is False  # equal on every project is not higher on six
    better = _fake(red=0.3, primary=0.81, repeat=0.9)
    assert criteria(better, TWO_STAGE)["passes"]
    assert verdict(better) in CANDIDATES


def test_first_failures_must_be_reached_sooner_than_random_not_merely_as_soon() -> None:
    level = _fake(red=0.45, primary=0.81, repeat=0.9)

    assert not criteria(level, TWO_STAGE)["sooner_than_random"]
    assert verdict(level) is None


def test_repeat_failures_veto_only_when_clearly_worse() -> None:
    slightly = _fake(red=0.3, primary=0.81, repeat=0.897)
    clearly = _fake(red=0.3, primary=0.85, repeat=0.88)

    assert criteria(slightly, TWO_STAGE)["no_repeat_veto"]
    assert not criteria(clearly, TWO_STAGE)["no_repeat_veto"]


def test_the_bootstrap_resamples_builds_not_jobs() -> None:
    """Two jobs of one build move together: a project whose only build holds both has one
    difference to resample, and its interval collapses onto it."""
    project = {
        "project": "p",
        "trials": {"first_failure": [True, True], "builds": [7, 7]},
        "rankings": {
            "a": {"per_trial": {PRIMARY: [0.9, 0.5]}},
            "b": {"per_trial": {PRIMARY: [0.8, 0.6]}},
        },
    }
    value, low, high = difference([project], "a", "b", PRIMARY, EVERY)

    assert value == pytest.approx(0.0)
    assert low == pytest.approx(0.0) and high == pytest.approx(0.0)


def test_the_held_out_mode_needs_its_flag_and_writes_the_ledger_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit):
        confirmation.main(["held-out"])
    with pytest.raises(SystemExit):
        confirmation.main(["training", "--held-out"])

    written: list[str] = []

    def peek(command: str, projects: Any, replayed: str, version: str) -> str:
        written.append(command)
        raise NotFrozen("the checkout is not frozen")

    monkeypatch.setattr(confirmation, "record_peek", peek)
    monkeypatch.setattr(confirmation, "RESULTS", tmp_path)
    with pytest.raises(SystemExit):
        confirmation.main(["held-out", "--held-out"])
    # The row was attempted before anything ran, and nothing was replayed.
    assert written == ["benchmarks.confirmation held-out"]
    assert not (tmp_path / "held-out").exists()
