"""The ranking study's engine, rankings and measures (docs/adr/0014)."""

from __future__ import annotations

import itertools
import json
import random
from collections.abc import Mapping
from pathlib import Path

import pytest

from benchmarks.replay import Job, concurrent_groups, replay
from benchmarks.rtptorrent.data import load_jobs
from benchmarks.study.__main__ import main as study_main
from benchmarks.study.engine import PRIMARY, compare, job_trial, study
from benchmarks.study.history import ALPHA, BuildHistory, RunWindow
from benchmarks.study.metrics import Trial, best_red_at, scores, time_to_catch
from benchmarks.study.projects import STEPS
from benchmarks.study.rankings import (
    HISTORY_SIGNALS,
    PROXIMITY_SIGNALS,
    Candidate,
    Context,
    LatestFailure,
    ProductRanking,
    _signal,
    location,
    product_order,
    tie,
)
from benchmarks.study.release_020 import HISTORY_RUNS
from testhunch.junit import collapse
from testhunch.models import CaseResult, Status
from testhunch.store import SqlStore, open_store

EXTRACT = Path(__file__).parent / "fixtures" / "rtptorrent" / "adamfisk@LittleProxy"


@pytest.fixture
def store(tmp_path: Path) -> SqlStore:
    opened = open_store(f"sqlite:///{tmp_path.as_posix()}/history.db")
    opened.migrate()
    return opened


def result(
    key: str, status: Status = Status.PASSED, duration: int | None = 10, file: str | None = None
) -> CaseResult:
    return CaseResult(key, key, None, file, status, duration, None)


def trial(tests: str, failing: str, durations: Mapping[str, int | None], job_id: int = 1) -> Trial:
    return Trial(job_id, tuple(tests), frozenset(failing), durations, ())


def test_apfdc_with_one_fault_is_how_soon_the_first_failure_ends() -> None:
    # Costs with the 1 ms epsilon: a 10, b 20, c 30 ms; b starts at 10 and takes 20 of 60.
    job = trial("abc", "b", {"a": 9, "b": 19, "c": 29})

    measured = scores(job, ["a", "b", "c"], known=3)

    assert measured[PRIMARY] == pytest.approx(1 - (10 + 20 / 2) / 60)
    assert measured["apfdc"] == pytest.approx(measured[PRIMARY])
    assert (measured["time_0.25"], measured["time_0.5"]) == (0.0, 1.0)  # b ends at 30 of 60


def test_apfdc_per_failure_follows_luo_et_al_equation_3() -> None:
    job = trial("abc", "bc", {"a": 9, "b": 19, "c": 29})

    measured = scores(job, ["a", "b", "c"], known=3)

    assert measured["apfdc"] == pytest.approx(((60 - 10 - 10) + (60 - 30 - 15)) / (60 * 2))
    assert measured[PRIMARY] == pytest.approx(1 - (10 + 10) / 60)


def test_a_single_failure_placed_at_random_scores_one_half_on_average() -> None:
    durations = {"a": 0, "b": 4, "c": 99, "d": 12}
    values = [
        scores(trial("abcd", "c", durations), list(order), known=4)[PRIMARY]
        for order in itertools.permutations("abcd")
    ]

    assert sum(v for v in values if v is not None) / len(values) == pytest.approx(0.5)


def test_an_unknown_duration_leaves_time_measures_out_but_not_apfd() -> None:
    measured = scores(trial("ab", "b", {"a": None, "b": 5}), ["a", "b"], known=2)

    assert measured[PRIMARY] is None and measured["time_0.5"] is None
    assert measured["apfd"] == pytest.approx(1 - 2 / 2 + 1 / 4)


def test_unknown_tests_run_before_the_known_budget_is_cut() -> None:
    # "u" is unknown; of the 10 known tests, a 10% budget runs 1.
    tests = "u" + "abcdefghij"
    durations = {test: 1 for test in tests}

    assert scores(trial(tests, "a", durations), list(tests), known=10)["tests_0.1"] == 1.0
    assert scores(trial(tests, "b", durations), list(tests), known=10)["tests_0.1"] == 0.0


def test_an_order_missing_a_test_is_refused() -> None:
    with pytest.raises(ValueError, match="does not hold"):
        scores(trial("ab", "b", {"a": 1, "b": 1}), ["b"], known=1)


def test_the_priority_follows_rtptorrents_recurrence_build_by_build() -> None:
    rng = random.Random(7)
    tests = [f"T{index}" for index in range(8)]
    builds = BuildHistory()
    naive = dict.fromkeys(tests, 0.0)
    for _ in range(15):
        failed = {test: rng.random() < 0.3 for test in tests}
        ran = {test for test in tests if rng.random() < 0.8}
        builds.record([[result(t, Status.FAILED if failed[t] else Status.PASSED) for t in ran]])
        # P(n) = alpha F(n) + (1 - alpha) P(n - 1), where a test that did not run did not fail.
        naive = {t: ALPHA * (t in ran and failed[t]) + (1 - ALPHA) * naive[t] for t in tests}
        for test, record in builds.records.items():
            assert record.priority_at(builds.builds) == pytest.approx(naive[test], abs=1e-12)


def test_latest_failure_orders_as_the_priority_does() -> None:
    rng = random.Random(3)
    tests = [f"T{index}" for index in range(12)]
    builds = BuildHistory()
    for _ in range(20):
        builds.record(
            [[result(t, Status.FAILED if rng.random() < 0.2 else Status.PASSED) for t in tests]]
        )
    job = Trial(99, (*tests, "New"), frozenset({"T0"}), {}, ())

    order, known = LatestFailure().order(job, Context(builds, list))

    by_priority = sorted(
        tests, key=lambda t: (-builds.records[t].priority_at(builds.builds), tie(99, t))
    )
    assert order == ["New", *by_priority]
    assert known == len(tests)


def test_a_build_counts_a_failure_in_any_of_its_jobs_and_its_transitions() -> None:
    builds = BuildHistory()
    builds.record([[result("A")], [result("A", Status.FAILED)]])
    builds.record([[result("A")]])
    builds.record([[result("A", Status.SKIPPED)]])

    record = builds.records["A"]
    assert (record.runs, record.failures, record.last_failure) == (2, 1, 0)
    assert (record.transitions, record.last_transition, record.last_failed) == (1, 1, False)


def _engine_product_orders(jobs: list[Job]) -> list[list[str]]:
    window = RunWindow(HISTORY_RUNS)
    orders = []
    for group in concurrent_groups(jobs):
        collapsed = [collapse(job.results) for job in group]
        history = window.history()
        for job, results in zip(group, collapsed, strict=True):
            tests = [r.key for r in results]
            orders.append(product_order(tests, history, job.changed_files or ())[0])
        for results in collapsed:
            window.record(results)
    return orders


def _engine_final_orders(jobs: list[Job]) -> list[list[str]]:
    """The order the study's final version gives every job, as the engine replays them."""
    final = STEPS["step-4"].current
    builds = BuildHistory()
    orders = []
    for group in concurrent_groups(jobs):
        collapsed = [collapse(job.results) for job in group]
        context = Context(builds, list)
        for job, results in zip(group, collapsed, strict=True):
            orders.append(final.order(job_trial(job, results), context)[0])
        builds.record(collapsed, [path for job in group for path in job.changed_files or ()])
    return orders


def test_the_product_replay_orders_every_extract_job_as_the_final_version(store: SqlStore) -> None:
    jobs = load_jobs(EXTRACT)

    replayed = [list(ranked.order) for ranked in replay(jobs, store, "adamfisk@LittleProxy")]

    assert STEPS["step-4"].current.name == "latest-failure+time^1.0+test_file_changed*0.5"
    assert replayed == _engine_final_orders(jobs)


def test_the_product_replay_orders_a_synthetic_history_as_the_final_version(
    store: SqlStore,
) -> None:
    rng = random.Random(11)
    names = ["cart", "user", "store", "restore", "order"]
    jobs = []
    for index in range(130):
        results = []
        for name in names:
            for n in range(3):
                if rng.random() < 0.3:
                    continue
                status = rng.choice([Status.PASSED, Status.PASSED, Status.FAILED, Status.SKIPPED])
                # A skipped result carries no file: the engine takes a test's file only from the
                # builds it ran in, the store from any result (docs/adr/0015).
                known_file = status is not Status.SKIPPED and rng.random() < 0.8
                results.append(
                    result(
                        f"tests/test_{name}.py::test_{n}",
                        status,
                        rng.choice([None, 0, 1, 2, 3, 10, 11, 250]),
                        file=f"tests/test_{name}.py" if known_file else None,
                    )
                )
        # Consecutive jobs of a commit form one build; some commits come back later.
        commits = frozenset({f"c{index // rng.choice([1, 2, 3])}"})
        changed = (f"src/{rng.choice(names)}.py", f"tests/test_{rng.choice(names)}.py")
        jobs.append(Job(index, commits, changed if rng.random() < 0.8 else None, tuple(results)))

    replayed = [list(ranked.order) for ranked in replay(jobs, store, "repo")]

    assert replayed == _engine_final_orders(jobs)
    assert store.history("repo").builds == len(list(concurrent_groups(jobs)))


def test_the_study_scores_every_ranking_on_the_same_trials_and_skips_the_cold_group() -> None:
    jobs = [
        Job(1, frozenset({"a"}), (), (result("A", Status.FAILED), result("B"))),
        Job(2, frozenset({"b"}), (), (result("A"), result("B", Status.FAILED))),
        Job(3, frozenset({"c"}), (), (result("A", Status.FAILED), result("B"), result("C"))),
    ]

    outcome = study(jobs, [LatestFailure(), ProductRanking()])

    assert outcome["counts"]["jobs_ranked_from_empty_history"] == 1
    assert outcome["counts"]["jobs_evaluated"] == 2
    assert outcome["trials"]["job_ids"] == [2, 3]
    for ranking in outcome["rankings"].values():
        assert len(ranking["per_trial"][PRIMARY]) == 2
    # Job 3: A failed in build 0 and passed in build 1, B failed in build 1, C is new: C, B, A.
    latest = outcome["rankings"]["latest-failure"]["per_trial"]["apfd"][1]
    assert latest == pytest.approx(1 - 3 / 3 + 1 / 6)  # order C, B, A: A is third


def test_rankings_must_have_distinct_names() -> None:
    with pytest.raises(ValueError, match="share a name"):
        study([], [LatestFailure(), LatestFailure()])


def test_a_candidate_beats_another_only_with_an_interval_above_zero_and_six_projects() -> None:
    before = {f"p{index}": 0.5 for index in range(10)}

    clear = compare(before, {p: 0.6 for p in before})
    one_project = compare(before, {**before, "p0": 1.5})
    five_projects = compare(before, {p: 0.6 if int(p[1:]) < 5 else 0.49 for p in before})

    assert clear["beats"] and clear["interval"][0] == pytest.approx(0.1)
    assert not one_project["beats"]  # a mean carried by one project
    assert five_projects["higher_on"] == 5 and not five_projects["beats"]
    assert compare(before, {p: 0.6 for p in before}) == clear  # seeded


def _random_history(seed: int, tests: list[str], builds_count: int) -> BuildHistory:
    rng = random.Random(seed)
    builds = BuildHistory()
    for _ in range(builds_count):
        builds.record(
            [
                [
                    result(
                        t,
                        Status.FAILED if rng.random() < 0.15 else Status.PASSED,
                        rng.randint(0, 50),
                    )
                    for t in tests
                    if rng.random() < 0.9
                ]
            ],
            changed_files=[f"src/{rng.choice(tests).lower()}.py"],
        )
    return builds


def test_a_candidate_without_signals_orders_as_the_latest_failure() -> None:
    tests = [f"T{index}" for index in range(30)]
    builds = _random_history(5, tests, 60)
    job = Trial(7, (*tests, "New"), frozenset({"T1"}), {}, ())
    context = Context(builds, list)

    assert Candidate("plain").order(job, context) == LatestFailure().order(job, context)


def test_file_failures_is_the_share_of_a_files_changes_the_test_failed_after() -> None:
    builds = BuildHistory()
    builds.record([[result("A", Status.FAILED), result("B")]], changed_files=["src/cart.py"])
    builds.record([[result("A"), result("B")]], changed_files=["src/cart.py", "src/user.py"])
    builds.record([[result("A"), result("B", Status.FAILED)]], changed_files=["src/user.py"])
    job = Trial(1, ("A", "B"), frozenset({"A"}), {}, ("src/cart.py",))

    signal = _signal("file_failures", job, Context(builds, list))

    assert (signal("A"), signal("B")) == (0.5, 0.0)  # cart.py changed twice, A failed after one


def test_a_heavy_name_weight_pulls_up_the_test_named_after_the_change() -> None:
    builds = BuildHistory()
    builds.record([[result("CartTest", file="t/cart_test.py"), result("UserTest", Status.FAILED)]])
    job = Trial(1, ("UserTest", "CartTest"), frozenset({"CartTest"}), {}, ("src/cart.py",))
    context = Context(builds, list)

    assert Candidate("plain").order(job, context)[0] == ["UserTest", "CartTest"]
    assert Candidate("name", (("name", 2.0),)).order(job, context)[0] == ["CartTest", "UserTest"]


def test_time_puts_the_quicker_test_first_among_equal_priorities() -> None:
    builds = BuildHistory()
    builds.record([[result("Slow", duration=900), result("Quick", duration=9)]])
    job = Trial(1, ("Slow", "Quick"), frozenset({"Quick"}), {}, ())

    assert Candidate("t", time_exponent=0.0).order(job, Context(builds, list))[0] == [
        "Quick",
        "Slow",
    ]


def test_a_window_treats_tests_that_have_not_run_lately_as_new() -> None:
    builds = BuildHistory()
    builds.record([[result("Old", Status.FAILED), result("Recent")]])
    for _ in range(5):
        builds.record([[result("Recent", Status.FAILED)]])
    job = Trial(1, ("Recent", "Old"), frozenset({"Old"}), {}, ())
    context = Context(builds, list)

    assert Candidate("all").order(job, context) == (["Recent", "Old"], 2)
    assert Candidate("w", window=3).order(job, context) == (["Old", "Recent"], 1)


def test_unknown_signals_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown signals"):
        Candidate("bad", (("coverage", 1.0),))


def test_each_step_one_candidate_adds_one_signal_to_the_latest_failure() -> None:
    step = STEPS["step-1"]
    names = [ranking.name for ranking in step.candidates]

    assert len(names) == len(set(names)) == 3 * (len(HISTORY_SIGNALS) + 2)
    assert all(name.startswith("latest-failure+") and name.count("+") == 1 for name in names)


def test_step_two_adds_the_remaining_signals_to_the_version_step_one_kept() -> None:
    step = STEPS["step-2"]
    names = [ranking.name for ranking in step.candidates]

    assert step.current.name == "latest-failure+time^1.0"
    assert len(names) == len(set(names)) == 3 * (len(HISTORY_SIGNALS) + 1)
    assert not any("time^" in name.removeprefix(step.current.name) for name in names)


def test_a_steady_but_negligible_improvement_does_not_beat() -> None:
    before = {f"p{index}": 0.5 for index in range(10)}

    verdict = compare(before, {p: 0.5002 for p in before})

    assert verdict["interval"][0] > 0 and verdict["higher_on"] == 10
    assert not verdict["beats"]


def test_red_at_is_the_share_of_time_spent_when_the_first_failure_ends() -> None:
    measured = scores(trial("abc", "b", {"a": 9, "b": 19, "c": 29}), ["a", "b", "c"], known=3)

    assert measured["red_at"] == pytest.approx(30 / 60)


def test_the_time_to_catch_a_share_of_failing_jobs_is_a_nearest_rank_quantile() -> None:
    red_at = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    assert time_to_catch(red_at, 0.9) == 0.9
    assert time_to_catch(red_at, 0.95) == 1.0
    assert time_to_catch([0.3], 0.5) == 0.3


def _proximity_values(key: str, file: str | None, changed: tuple[str, ...]) -> dict[str, float]:
    builds = BuildHistory()
    builds.record([[result(key, file=file)]])
    job = Trial(1, (key,), frozenset({key}), {key: 1}, changed)
    context = Context(builds, list)
    return {name: _signal(name, job, context)(key) for name in PROXIMITY_SIGNALS}


def test_a_java_test_class_is_close_to_its_own_file_and_its_subject() -> None:
    own = _proximity_values(
        "org.jooq.impl.ParserTest", None, ("jOOQ/src/test/java/org/jooq/impl/ParserTest.java",)
    )
    subject = _proximity_values(
        "org.jooq.impl.ParserTest", None, ("jOOQ/src/main/java/org/jooq/impl/Parser.java",)
    )
    elsewhere = _proximity_values("org.jooq.impl.ParserTest", None, ("docs/README.md",))

    assert (own["test_file_changed"], own["subject_file_changed"]) == (1.0, 0.0)
    assert (subject["test_file_changed"], subject["subject_file_changed"]) == (0.0, 1.0)
    # org, jooq, impl and parser: 4 of the test path's 5 tokens (test is the fifth).
    assert subject["token_similarity"] == pytest.approx(4 / 5)
    assert elsewhere["test_file_changed"] == elsewhere["subject_file_changed"] == 0.0
    for name in ("path_similarity", "token_similarity", "name_similarity"):
        assert subject[name] > elsewhere[name]


def test_a_pytest_file_is_located_by_its_reported_file() -> None:
    values = _proximity_values(
        "tests/test_options.py::test_flag", "tests/test_options.py", ("src/click/options.py",)
    )

    assert location("tests/test_options.py::test_flag", None) == "tests/test_options.py"
    assert (values["test_file_changed"], values["subject_file_changed"]) == (0.0, 1.0)
    assert values["name_similarity"] == pytest.approx(1 - 5 / 12)  # "test_options" vs "options"


def test_proximity_is_zero_without_known_changed_files() -> None:
    assert set(_proximity_values("org.a.BTest", None, ()).values()) == {0.0}


def test_the_best_order_in_hindsight_runs_unknown_tests_then_the_quickest_failure() -> None:
    job = trial("uabc", "bc", {"u": 9, "a": 9, "b": 29, "c": 19})  # costs 10, 10, 30, 20

    assert best_red_at(job, known={"a", "b", "c"}) == pytest.approx((10 + 20) / 70)
    assert best_red_at(trial("uab", "u", {"u": 9, "a": 9, "b": 9}), known={"a", "b"}) == (
        pytest.approx(10 / 30)
    )


def test_the_extension_step_tries_only_the_proximity_signals() -> None:
    step = STEPS["step-3"]
    names = [ranking.name for ranking in step.candidates]

    assert step.current == STEPS["step-2"].current
    assert len(names) == 3 * len(PROXIMITY_SIGNALS)
    assert all(any(signal in name for signal in PROXIMITY_SIGNALS) for name in names)


def test_step_four_tries_every_unused_signal_on_the_version_step_three_kept() -> None:
    step = STEPS["step-4"]
    names = [ranking.name for ranking in step.candidates]

    assert step.current.name == "latest-failure+time^1.0+test_file_changed*0.5"
    unused = len(HISTORY_SIGNALS) + len(PROXIMITY_SIGNALS) - 1  # all but test_file_changed
    assert len(names) == len(set(names)) == 3 * (unused + 1)  # and three windows
    assert not any("test_file_changed" in name.removeprefix(step.current.name) for name in names)


def test_only_the_held_out_step_replays_held_out_projects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for arguments in (
        ["held-out", "--out", str(tmp_path)],
        ["step-4", "--held-out", "--out", str(tmp_path)],
        ["step-4", "--projects", "apache@sling", "--out", str(tmp_path)],
        ["held-out", "--held-out", "--projects", "dynjs@dynjs", "--out", str(tmp_path)],
    ):
        with pytest.raises(SystemExit) as refused:
            study_main(arguments)
        assert refused.value.code == 2
    assert not any(tmp_path.iterdir())


def test_the_held_out_step_replays_the_reference_and_every_kept_version() -> None:
    step = STEPS["held-out"]

    assert [ranking.name for ranking in step.rankings()] == [
        "latest-failure",
        "latest-failure+time^1.0",
        "latest-failure+time^1.0+test_file_changed*0.5",
        "testhunch-0.2.0",
    ]


def test_the_frozen_copy_orders_the_extract_as_testhunch_0_2_0_did() -> None:
    recorded = json.loads(
        (
            Path(__file__).parent / "fixtures" / "study" / "littleproxy-orders-testhunch-0.2.0.json"
        ).read_text(encoding="utf-8")
    )
    jobs = load_jobs(EXTRACT)

    orders = _engine_product_orders(jobs)

    assert {str(job.job_id): order for job, order in zip(jobs, orders, strict=True)} == recorded
