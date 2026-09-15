"""The measurement of testhunch on its own CI (docs/adr/0028)."""

from __future__ import annotations

from pathlib import Path

from benchmarks.selfci import Build, Cut, _cut, builds, markdown, replay
from testhunch.models import RankedTest
from testhunch.store import SqlStore, open_store

REPO = "acme/shop"


def ranked(*durations: float) -> list[RankedTest]:
    return [
        RankedTest(key=f"t{i}", score=1.0 / (i + 1), reasons=(), expected_ms=ms)
        for i, ms in enumerate(durations)
    ]


def test_a_cut_takes_the_prefix_that_fits_and_reports_what_it_left_unspent() -> None:
    # 400 ms in total, so a 25% budget allows 100 ms. The first two fit, the third does not.
    cut = _cut("abc1234", ranked(40, 50, 200, 110))

    assert (cut.kept, cut.spent_ms, cut.allowed_ms) == (2, 90, 100)
    assert cut.used == 0.9


def test_a_cut_blocked_by_an_expensive_test_loses_the_rest_of_its_budget() -> None:
    """The prefix rule stops at the first test too expensive, whatever follows it."""
    cut = _cut("abc1234", ranked(10, 900, 5, 5, 5, 5, 5, 5, 5, 5))

    assert cut.kept == 1
    assert cut.used < 0.06


def test_a_cut_runs_at_least_one_test_even_when_nothing_fits() -> None:
    assert _cut("abc1234", ranked(100.0)).kept == 1


def test_builds_are_read_from_the_folder_names_in_order(tmp_path: Path) -> None:
    for name in (
        "2026-09-13T15-22-10Z_1d10c8a8_34765388378",
        "2026-09-13T14-07-11Z_22353083_34761738522",
        "2026-09-13T16-00-00Z_deadbeef_34765999999",  # no report: skipped
    ):
        (tmp_path / name).mkdir()
    for name in (
        "2026-09-13T15-22-10Z_1d10c8a8_34765388378",
        "2026-09-13T14-07-11Z_22353083_34761738522",
    ):
        (tmp_path / name / "junit.xml").write_bytes(b"<testsuite/>")

    found = builds(tmp_path)

    assert [build.commit for build in found] == ["22353083", "1d10c8a8"]
    assert [build.run_id for build in found] == [34761738522, 34765388378]


def test_the_replay_records_its_ranking_before_the_run_it_will_be_judged_against(
    tmp_path: Path, sqlite_url: str
) -> None:
    """A ranking that could have seen the results would make the shadow report worthless."""
    store = open_store(sqlite_url)
    store.migrate()
    report = tmp_path / "junit.xml"
    report.write_bytes(
        b'<testsuite name="s"><testcase classname="s" name="a" time="0.5"/>'
        b'<testcase classname="s" name="b" time="0.1"/></testsuite>'
    )
    found = [Build(run_id=i, commit=f"{i:08x}", report=report) for i in (1, 2, 3)]

    cuts = replay(store, found, REPO)

    # The first build ranks nothing: there is no history yet, so there is nothing to record.
    assert len(cuts) == 2
    runs = store.shadow_runs(REPO, 10)
    assert runs, "the rankings were recorded"
    for run in runs:
        assert run.positions, "a recorded ranking with no position judges nothing"


def test_the_page_says_so_when_no_build_was_truncated(sqlite_url: str) -> None:
    store: SqlStore = open_store(sqlite_url)
    store.migrate()
    found = [Build(run_id=1, commit="abc1234", report=Path("unused"))]
    full = Cut(commit="abc1234", ranked=10, kept=9, allowed_ms=100, spent_ms=99, total_ms=400)

    page = markdown(store, REPO, found, [full])

    assert "**0 of 1 builds**" in page
    assert "| none | | | |" in page
    assert "**0 of those builds had a failing test.**" in page
