"""The features and the learned model of phase 6 (docs/adr/0030)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from benchmarks.replay import Job
from benchmarks.study.features import NAMES, NEVER, WINDOWS, Change, _path_overlap, features
from benchmarks.study.history import LONGEST_WINDOW, BuildHistory
from benchmarks.study.learned import (
    NEGATIVES_PER_POSITIVE,
    Dataset,
    LearnedRanking,
    collect_project,
    fit,
    merge,
)
from benchmarks.study.metrics import Trial
from benchmarks.study.rankings import Context
from testhunch.models import CaseResult, Status


def result(key: str, status: Status = Status.PASSED, file: str | None = None) -> CaseResult:
    return CaseResult(key, key, None, file, status, 10, None)


def job(job_id: int, commit: str, *results: CaseResult, changed: tuple[str, ...] = ()) -> Job:
    return Job(job_id, frozenset({commit}), changed, results)


def trial(*tests: str, failing: str = "", changed: tuple[str, ...] = ()) -> Trial:
    return Trial(
        job_id=1,
        tests=tests,
        failing=frozenset(failing.split()),
        durations=dict.fromkeys(tests, 10),
        changed_files=changed,
    )


def history(builds: int = 3) -> BuildHistory:
    """`a` fails in every build, `b` never does, both in a file of their own."""
    record = BuildHistory()
    for _ in range(builds):
        record.record(
            [
                (
                    result("a", Status.FAILED, file="src/a.py"),
                    result("b", Status.PASSED, file="src/b.py"),
                )
            ],
            ["src/a.py"],
        )
    return record


def named(row: list[float]) -> dict[str, float]:
    return dict(zip(NAMES, row, strict=True))


# -- the features -----------------------------------------------------------------------------


def test_a_row_has_one_value_per_name() -> None:
    builds = history()
    change = Change.of(trial("a", "b"), builds)

    row = features("a", builds.records["a"], builds.builds, change, builds)

    assert len(row) == len(NAMES)
    assert all(isinstance(value, float) for value in row)


def test_a_test_that_never_failed_says_so_rather_than_guessing() -> None:
    builds = history()
    change = Change.of(trial("a", "b"), builds)

    row = named(features("b", builds.records["b"], builds.builds, change, builds))

    assert row["never_failed"] == 1.0
    assert row["builds_since_failure"] == NEVER
    assert row["failures"] == 0.0


def test_windows_count_only_the_builds_they_cover() -> None:
    builds = BuildHistory()
    builds.record([(result("a", Status.FAILED),)])  # build 0: fails
    for _ in range(20):
        builds.record([(result("a", Status.PASSED),)])
    change = Change.of(trial("a"), builds)

    row = named(features("a", builds.records["a"], builds.builds, change, builds))

    assert row["failure_rate_7"] == 0.0, "the only failure is 21 builds back"
    assert row["failure_rate_28"] > 0.0, "and the widest window still sees it"
    assert row["runs_7"] == 7.0


def test_a_window_cannot_reach_further_back_than_the_record_keeps() -> None:
    assert max(WINDOWS) == LONGEST_WINDOW


def test_the_cochange_counts_are_read_from_the_builds_that_changed_the_file() -> None:
    builds = history()
    change = Change.of(trial("a", "b", changed=("src/a.py",)), builds)

    row = named(features("a", builds.records["a"], builds.builds, change, builds))

    # Three builds changed src/a.py, and `a` failed in all three.
    assert row["cochange_failures"] == 3.0
    assert row["cochange_rate"] == 1.0
    assert row["test_file_changed"] == 1.0


def test_a_test_whose_file_never_changed_scores_nothing_for_it() -> None:
    builds = history()
    change = Change.of(trial("a", "b", changed=("src/a.py",)), builds)

    row = named(features("b", builds.records["b"], builds.builds, change, builds))

    assert row["cochange_failures"] == 0.0
    assert row["test_file_changed"] == 0.0


@pytest.mark.parametrize(
    ("file", "changed", "expected"),
    [
        ("src/api/user.py", ("src/api/user.py",), 1.0),
        ("src/api/user.py", ("src/api/other.py",), 1.0),  # same directory
        ("src/api/user.py", ("src/web/page.py",), 0.5),  # src in common, of two levels
        ("src/api/user.py", ("docs/index.md",), 0.0),
        ("user.py", ("src/api/user.py",), 0.0),  # no directory of its own
        (None, ("src/api/user.py",), 0.0),
    ],
)
def test_path_overlap_is_the_shared_prefix_over_its_own_depth(
    file: str | None, changed: tuple[str, ...], expected: float
) -> None:
    assert _path_overlap(file, changed) == expected


# -- the dataset ------------------------------------------------------------------------------


def test_only_builds_that_went_red_produce_rows() -> None:
    green = [job(i, f"c{i}", result("a"), result("b")) for i in range(1, 6)]

    dataset = collect_project(green, "acme/green")

    assert len(dataset.labels) == 0
    assert dataset.rows.shape == (0, len(NAMES))


def test_a_red_build_keeps_every_failure_and_samples_the_passes() -> None:
    passing = [result(f"p{i}") for i in range(100)]
    jobs = [
        job(1, "c1", result("a"), *passing),
        job(2, "c2", result("a", Status.FAILED), *passing),
    ]

    dataset = collect_project(jobs, "acme/shop")

    assert int(dataset.labels.sum()) == 1, "the one failing test"
    assert len(dataset.labels) == 1 + NEGATIVES_PER_POSITIVE
    assert dataset.projects == ["acme/shop"] * len(dataset.labels)


def test_the_first_build_teaches_nothing_because_nothing_preceded_it() -> None:
    """Its tests are unknown, so there is no feature to compute for them."""
    dataset = collect_project([job(1, "c1", result("a", Status.FAILED))], "acme/shop")

    assert len(dataset.labels) == 0


def test_the_sample_of_passes_is_the_same_every_time() -> None:
    jobs = [
        job(1, "c1", result("a"), *[result(f"p{i}") for i in range(100)]),
        job(2, "c2", result("a", Status.FAILED), *[result(f"p{i}") for i in range(100)]),
    ]

    first = collect_project(jobs, "acme/shop")
    second = collect_project(jobs, "acme/shop")

    assert np.array_equal(first.rows, second.rows)


def test_merging_keeps_every_row_and_which_project_it_came_from() -> None:
    one = Dataset(np.ones((2, len(NAMES)), dtype=np.float32), np.array([1, 0]), ["a", "a"])
    two = Dataset(np.zeros((1, len(NAMES)), dtype=np.float32), np.array([0]), ["b"])

    whole = merge([one, two])

    assert whole.rows.shape == (3, len(NAMES))
    assert whole.projects == ["a", "a", "b"]


def test_a_dataset_survives_a_round_trip_through_a_file(tmp_path: Path) -> None:
    original = Dataset(np.ones((2, len(NAMES)), dtype=np.float32), np.array([1, 0]), ["a", "b"])

    original.save(tmp_path / "d.npz")
    back = Dataset.load(tmp_path / "d.npz")

    assert np.array_equal(original.rows, back.rows)
    assert np.array_equal(original.labels, back.labels)
    assert back.projects == ["a", "b"]


# -- the ranking ------------------------------------------------------------------------------


def learned() -> LearnedRanking:
    """A model fitted on a signal so blunt that its ranking is predictable: failures win."""
    rows = np.zeros((200, len(NAMES)), dtype=np.float32)
    labels = np.zeros(200, dtype=np.int8)
    rate = NAMES.index("failure_rate")
    for index in range(0, 200, 2):
        rows[index, rate] = 1.0
        labels[index] = 1
    return LearnedRanking(fit(Dataset(rows, labels, ["x"] * 200), max_iter=20))


def test_the_learned_ranking_puts_unknown_tests_first_like_every_other() -> None:
    builds = history()
    ranking = learned()

    order, known = ranking.order(trial("a", "b", "new"), Context(builds, lambda: []))

    assert order[0] == "new"
    assert known == 2


def test_the_learned_ranking_prefers_the_test_its_model_scores_higher() -> None:
    builds = history()
    ranking = learned()

    order, _ = ranking.order(trial("b", "a"), Context(builds, lambda: []))

    # `a` failed in every build, `b` in none, and the model was fitted to follow exactly that.
    assert order == ["a", "b"]


def test_the_learned_ranking_is_the_same_twice() -> None:
    builds = history()
    ranking = learned()
    one = trial("a", "b")

    assert (
        ranking.order(one, Context(builds, lambda: []))[0]
        == (ranking.order(one, Context(builds, lambda: []))[0])
    )


def test_a_trial_whose_tests_are_all_unknown_is_left_in_the_jobs_order() -> None:
    ranking = learned()

    order, known = ranking.order(trial("x", "y"), Context(BuildHistory(), lambda: []))

    assert (order, known) == (["x", "y"], 0)
