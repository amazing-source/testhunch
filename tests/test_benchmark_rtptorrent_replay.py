"""Replaying RTPTorrent through testhunch and scoring the rankings (docs/adr/0010)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from benchmarks import heldout
from benchmarks.replay import Job, add_points, apfd, concurrent_groups, failing_tests, replay
from benchmarks.rtptorrent.__main__ import main, markdown, run_project
from benchmarks.rtptorrent.data import STRATEGIES, load_jobs
from benchmarks.rtptorrent.schedules import read_schedules
from benchmarks.rtptorrent.summary import summary
from testhunch.models import CaseResult, Status
from testhunch.shadow import BUDGETS, evaluate
from testhunch.store import SqlStore, open_store

EXTRACT = Path(__file__).parent / "fixtures" / "rtptorrent" / "adamfisk@LittleProxy"


@pytest.fixture
def store(tmp_path: Path) -> SqlStore:
    opened = open_store(f"sqlite:///{tmp_path.as_posix()}/history.db")
    opened.migrate()
    return opened


def result(key: str, status: Status = Status.PASSED) -> CaseResult:
    return CaseResult(key, key, None, None, status, 10, None)


def job(job_id: int, commits: str, *results: CaseResult, changed: tuple[str, ...] = ()) -> Job:
    return Job(job_id, frozenset(commits.split()), changed, results)


@pytest.mark.parametrize(
    ("order", "failing", "expected"),
    [
        ("abcde", "a", 0.9),  # 1 - 1/5 + 1/10
        ("abcde", "e", 0.1),  # 1 - 5/5 + 1/10
        ("abcd", "ab", 0.75),  # 1 - 3/8 + 1/8
        ("abcd", "bba", 0.75),  # a class failing twice is one fault
    ],
)
def test_apfd_follows_the_papers_formula(order: str, failing: str, expected: float) -> None:
    assert apfd(list(order), failing) == pytest.approx(expected)


def test_apfd_is_undefined_without_a_fault() -> None:
    assert apfd(["a", "b"], []) is None


def test_consecutive_jobs_building_the_same_commits_are_one_group() -> None:
    jobs = [job(1, "a"), job(2, "a"), job(3, "a b"), job(4, "b a"), job(5, "a"), job(6, "")]

    assert [[j.job_id for j in g] for g in concurrent_groups(jobs)] == [[1, 2], [3, 4], [5], [6]]


def test_no_job_is_ranked_with_results_of_its_own_group(store: SqlStore) -> None:
    jobs = [
        job(1, "a", result("A"), result("B", Status.FAILED)),
        job(2, "a", result("A"), result("B"), result("C", Status.FAILED)),
        job(3, "b", result("A"), result("B"), result("C")),
    ]

    first, second, third = replay(jobs, store, "repo")

    assert (first.cold, second.cold, third.cold) == (True, True, False)
    assert first.run.positions == second.run.positions == {}
    # Job 3 comes after the group: it knows both jobs' classes, including C, first seen in job 2.
    assert set(third.run.positions) == {"A", "B", "C"}


def test_classes_the_ranking_does_not_know_run_first(store: SqlStore) -> None:
    jobs = [
        job(1, "a", result("A"), result("B", Status.FAILED)),
        job(2, "b", result("A"), result("New"), result("B"), result("Other")),
    ]

    ranked = list(replay(jobs, store, "repo"))[1]

    assert ranked.order == ("New", "Other", "B", "A")
    assert failing_tests(ranked.run.results) == set()


def test_a_changed_test_file_pulls_up_its_class(store: SqlStore) -> None:
    classes = (result("org.example.CartTest"), result("org.example.UserTest"))
    jobs = [
        job(1, "a", *classes),
        job(2, "b", *classes, changed=("src/test/java/org/example/UserTest.java",)),
        job(3, "c", *classes, changed=("src/test/java/org/example/CartTest.java",)),
    ]

    ranked = list(replay(jobs, store, "repo"))

    assert ranked[1].order == ("org.example.UserTest", "org.example.CartTest")
    assert ranked[2].order == ("org.example.CartTest", "org.example.UserTest")


def test_every_job_of_a_group_is_one_build(store: SqlStore) -> None:
    jobs = [
        job(1, "a", result("A"), result("B", Status.FAILED)),
        job(2, "a", result("A", Status.FAILED), result("B", Status.FAILED)),
        job(3, "", result("A")),
        job(4, "", result("A")),
        job(5, "a", result("A")),  # the same commits later: a build of its own
    ]

    list(replay(jobs, store, "repo"))

    history = store.history("repo")
    assert history.builds == 3
    assert [(c.key, c.builds, c.failures) for c in history.cases] == [("A", 3, 1), ("B", 1, 1)]


def test_scoring_jobs_one_at_a_time_adds_up_to_scoring_them_together(store: SqlStore) -> None:
    runs = [r.run for r in replay(load_jobs(EXTRACT), store, "adamfisk@LittleProxy") if not r.cold]

    one_at_a_time = evaluate([], BUDGETS)
    for run in runs:
        pairs = zip(one_at_a_time, evaluate([run], BUDGETS), strict=True)
        one_at_a_time = [add_points(a, b) for a, b in pairs]

    assert one_at_a_time == evaluate(runs, BUDGETS)
    assert one_at_a_time[0].failing_runs > 0


def test_points_of_different_budgets_do_not_add_up() -> None:
    ten, quarter, _ = evaluate([], BUDGETS)
    with pytest.raises(ValueError, match="budgets differ"):
        add_points(ten, quarter)


def test_a_schedule_keeps_each_class_once_at_its_first_position(tmp_path: Path) -> None:
    path = tmp_path / "schedule.csv"
    path.write_text(
        "travisBuildNumber,travisBuildId,travisJobId,testName,index,duration,count,failures,errors,skipped\n"
        "1,10,100,B,2,0.1,1,0,0,0\n"
        "1,10,100,A,1,0.1,1,0,0,0\n"
        "1,10,100,B,3,0.1,1,1,0,0\n"
        "1,10,101,C,1,0.1,1,0,1,0\n",
        encoding="utf-8",
    )

    assert read_schedules(path) == {100: (["A", "B"], {"B"}), 101: (["C"], {"C"})}


def test_the_authors_schedules_order_the_same_classes_as_the_replay(store: SqlStore) -> None:
    by_id = {r.job.job_id: r for r in replay(load_jobs(EXTRACT), store, "adamfisk@LittleProxy")}

    for strategy in STRATEGIES:
        schedules = read_schedules(EXTRACT / "baseline" / f"{strategy}.csv")
        assert schedules
        for job_id, (order, failing) in schedules.items():
            assert sorted(order) == sorted(by_id[job_id].order)
            assert failing == failing_tests(by_id[job_id].run.results)


def test_the_report_accounts_for_every_job() -> None:
    report = run_project(EXTRACT)

    jobs = report["jobs"]
    assert (jobs["total"], jobs["without_commit"]) == (80, 17)
    assert jobs["evaluated"] + jobs["ranked_from_empty_history"] == 80
    assert [point["fraction"] for point in report["shadow"]] == [0.1, 0.25, 0.5]
    assert all(point["runs"] == jobs["evaluated"] for point in report["shadow"])
    assert report["apfd"]["jobs"] > 0
    assert set(report["apfd"]["mean"]) == {"testhunch", *STRATEGIES}


def test_a_project_without_schedules_compares_no_apfd(tmp_path: Path) -> None:
    project = tmp_path / "adamfisk@LittleProxy"
    shutil.copytree(EXTRACT, project, ignore=shutil.ignore_patterns("baseline"))

    report = run_project(project)

    assert report["apfd"] == {"jobs": 0, "mean": {}}
    assert "no schedule" in markdown(report)


def test_the_benchmark_writes_json_and_markdown_per_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    shutil.copytree(EXTRACT, cache / "adamfisk@LittleProxy")
    (cache / "adamfisk@LittleProxy" / "source.json").write_text('{"url": "test"}', encoding="utf-8")

    # The extract comes from a held-out project (docs/adr/0013); it tests reading, not ranking.
    # The freeze check and the ledger are the subject of test_benchmark_heldout: here they only
    # have to stay out of the way, and out of the repository's own ledger (docs/adr/0016).
    ledger = tmp_path / "held-out-log.md"
    monkeypatch.setattr(heldout, "frozen_commit", lambda ledger=None: "0" * 40)
    monkeypatch.setattr(heldout, "LEDGER", ledger)
    arguments = [
        "adamfisk@LittleProxy",
        "--held-out",
        "--cache",
        str(cache),
        "--out",
        str(tmp_path),
    ]
    assert main(arguments) == 0
    assert "adamfisk@LittleProxy" in ledger.read_text(encoding="utf-8")

    report = json.loads((tmp_path / "adamfisk@LittleProxy.json").read_text(encoding="utf-8"))
    assert report["dataset"] == {"url": "test"}
    markdown = (tmp_path / "adamfisk@LittleProxy.md").read_text(encoding="utf-8")
    assert markdown.startswith("### adamfisk@LittleProxy")
    assert "| adamfisk@LittleProxy | 79 | 16 |" in (tmp_path / "README.md").read_text(
        encoding="utf-8"
    )


def test_the_summary_totals_projects_and_marks_missing_schedules() -> None:
    with_schedules = run_project(EXTRACT)
    without = {**with_schedules, "project": "example@no-schedules", "apfd": {"jobs": 0, "mean": {}}}

    page = summary([without, with_schedules])

    rows = [line for line in page.splitlines() if line.startswith("| ")]
    assert rows[0].split(" | ")[3:6] == [
        "Failing jobs caught at 10% / 25% / 50%",
        "Failing classes caught at 10% / 25% / 50%",
        "Test time run at 10% / 25% / 50% |",
    ]
    # The same project twice: the totals have the same shares as the project, per job and per class.
    assert rows[3].split(" | ")[:3] == ["| **All projects**", "158", "32"]
    assert rows[3].split(" | ")[3:] == rows[1].split(" | ")[3:]
    # The APFD table lists only the project that has schedules, and its jobs make the total.
    assert [row.split(" | ")[0] for row in rows[4:]] == [
        "| Project",
        "| adamfisk@LittleProxy",
        "| **All jobs**",
    ]
    assert "on 1 of 1 projects" in page
    assert page.rstrip().endswith("Without any schedule to compare with: example@no-schedules.")
