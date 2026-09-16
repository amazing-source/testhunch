"""Reading LRTS, against an archive written here in its shape (docs/adr/0033).

The real archive carries no licence of its own, so no extract of it lives in this repository. These
fixtures are written by hand in the layout the distributed zip actually has, which was read before
they were written: `dataset.csv` with one row per suite run, `test_class.csv` inside a zip inside
the zip, and one GitHub comparison per build.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from benchmarks.lrts.data import ROOT, Archive, concurrent, iter_builds
from benchmarks.lrts.engine import replay
from benchmarks.study.rankings import LatestFailure
from testhunch.models import Status

COLUMNS = (
    "project,pr_name,pr_base_branch,build_id,build_duration,build_timestamp,build_result,"
    "build_head_sha,build_date,trunk_sha,trunk_sha_source,stage_id,test_suite_duration_s,"
    "num_pass_class,num_fail_class,num_trans_class"
)


def row(
    project: str,
    pr: str,
    build: str,
    *,
    started: int,
    duration: int,
    head: str = "head1",
    trunk: str = "trunk1",
    stage: str = "single",
) -> str:
    return (
        f"{project},{pr},main,{build},{duration},{started},SUCCESS,{head},2024-01-01,{trunk},"
        f"api,{stage},10,1,0,0"
    )


def archive(
    tmp_path: Path,
    rows: list[str],
    tables: dict[tuple[str, str, str, str], str],
    comparisons: dict[tuple[str, str, str], list[dict[str, object]]] | None = None,
) -> Archive:
    """Write a zip shaped like the distributed one and open it."""
    path = tmp_path / "ML_TCSP.zip"
    with zipfile.ZipFile(path, "w") as outer:
        outer.writestr(f"{ROOT}/dataset.csv", "\n".join([COLUMNS, *rows]) + "\n")
        for (project, pr, build, stage), table in tables.items():
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w") as nested:
                nested.writestr("test_class.csv", table)
            outer.writestr(
                f"{ROOT}/artifact/processed_test_result/{project}/{pr}_build{build}/"
                f"stage_{stage}/test_class.csv.zip",
                inner.getvalue(),
            )
        for (project, pr, build), pages in (comparisons or {}).items():
            for number, page in enumerate(pages, start=1):
                outer.writestr(
                    f"{ROOT}/artifact/shadata/{project}/compare_commits/{pr}_build{build}/"
                    f"trunk1_head1_page{number}.json",
                    json.dumps(page),
                )
    return Archive(path)


def test_a_build_gathers_the_stages_its_rows_describe(tmp_path: Path) -> None:
    """The dataset counts one row per suite run, so a build with two stages has two rows."""
    with archive(
        tmp_path,
        [
            row("karaf", "PR-1", "1", started=100, duration=10, stage="jdk11"),
            row("karaf", "PR-1", "1", started=100, duration=10, stage="jdk17"),
        ],
        {
            ("karaf", "PR-1", "1", "jdk11"): "testclass,duration,outcome,last_outcome\na,1.0,0,0\n",
            ("karaf", "PR-1", "1", "jdk17"): "testclass,duration,outcome,last_outcome\nb,2.0,1,0\n",
        },
    ) as opened:
        (build,) = list(iter_builds(opened, "karaf"))

    assert [stage.stage_id for stage in build.stages] == ["jdk11", "jdk17"]
    assert [result.key for stage in build.stages for result in stage.results] == ["a", "b"]


def test_an_outcome_of_one_is_a_failure_and_a_duration_is_seconds(tmp_path: Path) -> None:
    with archive(
        tmp_path,
        [row("karaf", "PR-1", "1", started=100, duration=10)],
        {
            ("karaf", "PR-1", "1", "single"): (
                "testclass,duration,outcome,last_outcome\n"
                "passing,0.991,0,1\n"  # last_outcome says 1 and is not read
                "failing,12.5,1,0\n"
                "unknown_cost,,0,0\n"
            )
        },
    ) as opened:
        (build,) = list(iter_builds(opened, "karaf"))

    passing, failing, unknown = build.stages[0].results
    assert (passing.status, passing.duration_ms) == (Status.PASSED, 991)
    assert (failing.status, failing.duration_ms) == (Status.FAILED, 12500)
    # An unreadable cost stays unknown: a test with no duration is not a free test.
    assert unknown.duration_ms is None


def test_builds_come_oldest_first_and_ties_are_broken_by_id(tmp_path: Path) -> None:
    """The archive holds 211 groups of tied timestamps, so the order needs a second key."""
    with archive(
        tmp_path,
        [
            row("karaf", "PR-2", "20", started=500, duration=10),
            row("karaf", "PR-1", "10", started=100, duration=10),
            row("karaf", "PR-1", "11", started=100, duration=10),
        ],
        {},
    ) as opened:
        assert [build.build_id for build in iter_builds(opened, "karaf")] == ["10", "11", "20"]


def test_changed_files_gather_the_pages_and_keep_the_old_name_of_a_rename(tmp_path: Path) -> None:
    with archive(
        tmp_path,
        [row("karaf", "PR-1", "1", started=100, duration=10)],
        {},
        {
            ("karaf", "PR-1", "1"): [
                {"files": [{"filename": "src/A.java", "status": "modified"}]},
                {
                    "files": [
                        {
                            "filename": "src/C.java",
                            "status": "renamed",
                            "previous_filename": "src/B.java",
                        }
                    ]
                },
            ]
        },
    ) as opened:
        (build,) = list(iter_builds(opened, "karaf"))

    assert build.changed_files == ("src/A.java", "src/B.java", "src/C.java")


def test_a_missing_comparison_is_unknown_and_not_an_empty_change(tmp_path: Path) -> None:
    with archive(tmp_path, [row("karaf", "PR-1", "1", started=1, duration=1)], {}) as opened:
        (build,) = list(iter_builds(opened, "karaf"))

    assert build.changed_files is None


def test_a_comparison_at_the_cap_is_unknown_because_it_is_a_lower_bound(tmp_path: Path) -> None:
    """GitHub returns at most 300 paths and does not say how many it left out (ADR 0033)."""
    capped = [{"filename": f"src/F{index}.java", "status": "modified"} for index in range(300)]
    with archive(
        tmp_path,
        [row("karaf", "PR-1", "1", started=1, duration=1)],
        {},
        {("karaf", "PR-1", "1"): [{"files": capped}]},
    ) as opened:
        (build,) = list(iter_builds(opened, "karaf"))

    assert build.changed_files is None


def test_a_comparison_with_no_file_is_an_empty_change_not_an_unknown_one(tmp_path: Path) -> None:
    with archive(
        tmp_path,
        [row("karaf", "PR-1", "1", started=1, duration=1)],
        {},
        {("karaf", "PR-1", "1"): [{"files": []}]},
    ) as opened:
        (build,) = list(iter_builds(opened, "karaf"))

    assert build.changed_files == ()


def test_two_builds_on_one_commit_at_the_same_time_are_one_event(tmp_path: Path) -> None:
    with archive(
        tmp_path,
        [
            row("karaf", "PR-1", "1", started=100, duration=50, head="abc"),
            row("karaf", "PR-1", "2", started=120, duration=50, head="abc"),  # overlaps, same sha
            row("karaf", "PR-1", "3", started=200, duration=50, head="abc"),  # after both end
            row("karaf", "PR-2", "4", started=110, duration=50, head="def"),  # overlaps, other sha
        ],
        {},
    ) as opened:
        groups = concurrent(list(iter_builds(opened, "karaf")))

    assert [[build.build_id for build in group] for group in groups] == [
        ["1", "2"],
        ["4"],
        ["3"],
    ]


def test_a_build_knows_only_what_finished_before_it_started(tmp_path: Path) -> None:
    with archive(
        tmp_path,
        [
            row("karaf", "PR-1", "1", started=100, duration=50),
            row("karaf", "PR-1", "2", started=120, duration=10),
        ],
        {},
    ) as opened:
        first, second = list(iter_builds(opened, "karaf"))

    assert first.ended == 150
    assert first.overlaps(second) and second.overlaps(first)
    # The second started before the first had finished, so neither had the other's results.
    assert not (first.ended <= second.started)


def test_an_outcome_this_reader_does_not_know_is_refused(tmp_path: Path) -> None:
    """Better a stopped replay than a silent guess about what a value means."""
    table = "testclass,duration,outcome,last_outcome\na,1.0,2,0\n"
    with (
        archive(
            tmp_path,
            [row("karaf", "PR-1", "1", started=1, duration=1)],
            {
                (
                    "karaf",
                    "PR-1",
                    "1",
                    "single",
                ): table
            },
        ) as opened,
        pytest.raises(ValueError, match="unexpected outcome"),
    ):
        list(iter_builds(opened, "karaf"))


FAILS = "testclass,duration,outcome,last_outcome\nalpha,1.0,1,0\nbeta,1.0,0,0\n"


def test_a_build_still_running_is_not_yet_history(tmp_path: Path) -> None:
    """The rule of ADR 0033, and the reason this dataset cannot be replayed by groups.

    `a` runs from 0 to 100 and `b` starts at 50, so when `b` is ranked nothing has finished: both
    are ranked from an empty history and counted apart. `c` starts at 200 and sees them both.
    """
    rows = [
        row("karaf", "PR-1", "a", started=0, duration=100),
        row("karaf", "PR-1", "b", started=50, duration=10),
        row("karaf", "PR-1", "c", started=200, duration=10),
    ]
    tables = {("karaf", "PR-1", build, "single"): FAILS for build in ("a", "b", "c")}
    with archive(tmp_path, rows, tables) as opened:
        result = replay(opened, "karaf", [LatestFailure()])

    counts = result["counts"]
    assert counts["jobs_ranked_from_empty_history"] == 2  # a and b
    assert counts["jobs_evaluated"] == 1  # only c had a history
    assert counts["builds"] == 2  # a and b became history before c was ranked


def test_a_build_that_finished_first_is_history_even_if_it_started_later(tmp_path: Path) -> None:
    """The sweep is over ends, not starts: a short build that started later can finish sooner."""
    rows = [
        row("karaf", "PR-1", "long", started=0, duration=1000),
        row("karaf", "PR-1", "short", started=10, duration=5),  # ends at 15
        row("karaf", "PR-1", "later", started=20, duration=5),
    ]
    tables = {("karaf", "PR-1", build, "single"): FAILS for build in ("long", "short", "later")}
    with archive(tmp_path, rows, tables) as opened:
        result = replay(opened, "karaf", [LatestFailure()])

    # `later` sees `short`, which ended at 15, and not `long`, which is still running.
    assert result["counts"]["builds"] == 1
    assert result["counts"]["jobs_evaluated"] == 1
    assert result["builds"]["never_recorded"] == 2


def test_every_stage_of_a_build_is_a_job_of_its_own(tmp_path: Path) -> None:
    rows = [
        row("karaf", "PR-1", "1", started=0, duration=10, stage="jdk11"),
        row("karaf", "PR-1", "1", started=0, duration=10, stage="jdk17"),
        row("karaf", "PR-1", "2", started=100, duration=10),
    ]
    tables = {
        ("karaf", "PR-1", "1", "jdk11"): FAILS,
        ("karaf", "PR-1", "1", "jdk17"): FAILS,
        ("karaf", "PR-1", "2", "single"): FAILS,
    }
    with archive(tmp_path, rows, tables) as opened:
        result = replay(opened, "karaf", [LatestFailure()])

    assert result["counts"]["jobs"] == 3
    assert result["builds"] == {"total": 2, "suite_runs": 3, "never_recorded": 1}
