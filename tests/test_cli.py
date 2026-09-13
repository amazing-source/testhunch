"""End to end through the command line, against a real git repository and SQLite."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from testhunch.cli import main, markdown_code, parse_budget, parse_share
from testhunch.store import open_store

FIXTURES = Path(__file__).parent / "fixtures" / "junit"

Git = Callable[..., str]


@pytest.fixture
def workdir(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(git_repo)
    for variable in (
        "GITHUB_REPOSITORY",
        "GITHUB_HEAD_REF",
        "GITHUB_REF_NAME",
        "TESTHUNCH_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    shutil.copy(FIXTURES / "pytest.xml", git_repo / "junit.xml")
    return git_repo


def next_commit(workdir: Path, git: Git) -> None:
    """A new commit to test, after one whose results are already recorded."""
    (workdir / "kept.py").write_text("x = 5\n")
    git(workdir, "commit", "--quiet", "-am", "next")


def test_ingest_then_report_then_prioritize(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--db", sqlite_url, "--repo", "acme/shop"]

    assert main(["ingest", "junit.xml", *common]) == 0
    assert "ingested 9 results from 1 report(s)" in capsys.readouterr().out

    assert main(["ingest", "junit.xml", *common]) == 0
    assert "already ingested" in capsys.readouterr().out

    assert main(["report", "--format", "json", *common]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {row["key"] for row in report["failing"]} == {
        "tests.test_sample::test_fails",
        "tests.test_sample::test_parametrized[2]",
        "tests.test_sample::test_errors_in_setup",
        "tests.test_sample::test_errors_in_teardown",
    }

    assert main(["prioritize", "--format", "json", "--changed", "src/sample.py", *common]) == 0
    ranked = json.loads(capsys.readouterr().out)
    assert len(ranked) == 8  # the skipped test never ran, so it has no history yet
    assert ranked[0]["reasons"][0] == "matches changed file sample"


def test_ingest_records_changes_against_a_base(
    workdir: Path, sqlite_url: str, git: Git, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "kept.py").write_text("x = 99\n")
    git(workdir, "commit", "--quiet", "-am", "edit")

    assert main(["ingest", "junit.xml", "--base", "base", "--db", sqlite_url]) == 0
    assert "ingested" in capsys.readouterr().out

    (change,) = open_store(sqlite_url).run_changes(1)
    assert (change.path, change.change_type) == ("kept.py", "M")


def test_repo_defaults_to_the_directory_name_without_a_remote(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ingest", "junit.xml", "--db", sqlite_url]) == 0
    assert open_store(sqlite_url).run_count(workdir.name) == 1


def test_prioritize_without_history_explains_what_to_do(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["prioritize", "--db", sqlite_url, "--repo", "empty/repo"]) == 0
    assert "run `testhunch ingest`" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("output_format", "expected_out"),
    [
        ("json", "[]\n"),  # still valid JSON for whatever reads it
        ("keys", ""),
        ("markdown", "### testhunch ranking for empty/repo\n\nNo history yet"),
    ],
)
def test_prioritize_without_history_still_writes_well_formed_output(
    workdir: Path,
    sqlite_url: str,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    expected_out: str,
) -> None:
    args = ["prioritize", "--format", output_format, "--db", sqlite_url, "--repo", "empty/repo"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert out.startswith(expected_out) if expected_out else out == ""


def test_markdown_formats_for_job_summaries(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "junit.xml", *common]) == 0
    capsys.readouterr()

    assert main(["report", "--format", "markdown", *common]) == 0
    report = capsys.readouterr().out
    assert report.startswith("### testhunch report for acme/shop (1 runs recorded)\n")
    assert "**Flaky (passed and failed on the same commit)**\n\nNone.\n" in report
    assert "| Failures | Test |\n|---:|---|\n| 1 / 1 | `tests.test_sample::" in report

    changed = ["--changed", "src/sample.py", "--limit", "2"]
    assert main(["prioritize", "--format", "markdown", *changed, *common]) == 0
    ranking = capsys.readouterr().out
    assert ranking.startswith(
        "### testhunch ranking for acme/shop\n\n"
        "Top 2 of 8 tests for 1 changed file(s).\n\n"
        "| # | Score | Test | Why |\n|---:|---:|---|---|\n"
        "| 1 | 4.000 | `tests.test_sample::test_errors_in_setup` | matches changed file sample; "
        "failed in the latest run; failed 1 of 1 runs |\n"
    )
    assert ranking.count("\n| ") == 3  # header and two rows


def test_shadow_mode_from_recorded_ranking_to_report(
    workdir: Path, sqlite_url: str, git: Git, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "junit.xml", *common]) == 0

    # The next commit: rank before its tests run, then record its results.
    next_commit(workdir, git)
    capsys.readouterr()
    assert main(["prioritize", "--record", "--format", "keys", *common]) == 0
    recorded = capsys.readouterr()
    assert len(recorded.out.splitlines()) == 8  # stdout stays the ranking alone
    assert "recorded the ranking of 8 tests" in recorded.err
    assert main(["ingest", "junit.xml", *common]) == 0
    capsys.readouterr()

    assert main(["shadow", "--format", "json", *common]) == 0
    report = json.loads(capsys.readouterr().out)
    # The 4 failures of the first run rank first and fail again. Of the 8 ranked tests, the
    # top 10% is 1 test, 25% is 2 and 50% is 4.
    assert (report["runs"], report["failing_runs"]) == (1, 1)
    budgets = {p["fraction"]: (p["caught_runs"], p["caught_failures"]) for p in report["budgets"]}
    assert budgets == {0.1: (1, 1), 0.25: (1, 2), 0.5: (1, 4)}

    assert main(["shadow", *common]) == 0
    text = capsys.readouterr().out
    assert "1 run with a recorded ranking, 1 with failures" in text
    assert "top 25% of ranked tests: caught 1 of 1 failing runs, 2 of 4 failures;" in text
    # The sample report has no retries, so no failure is confirmed (docs/adr/0008).
    assert "4 of 4 failures ran only once" in text

    assert main(["shadow", "--format", "markdown", *common]) == 0
    markdown = capsys.readouterr().out
    assert "| 25% | 1 of 1 | 2 of 4 | 0 of 0 | 2 of 8 (25%) |" in markdown
    assert "4 of 4 failures ran only once" in markdown


def test_select_leaves_out_the_known_tests_below_the_budget(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "junit.xml", *common]) == 0
    capsys.readouterr()

    args = ["select", "--budget", "50%", "--runner", "pytest", "--changed", "src/other.py"]
    assert main([*args, "--learning-runs", "0%", *common]) == 0
    out = capsys.readouterr()
    # 8 known tests: the 4 that failed rank first and run; the 4 that passed are left out.
    assert sorted(out.out.splitlines()) == [
        "tests.test_sample.TestGrouped::test_in_class",
        "tests.test_sample::test_parametrized[1]",
        "tests.test_sample::test_parametrized[3]",
        "tests.test_sample::test_passes",
    ]
    assert "leaving out 4 of 8 known tests" in out.err


def test_a_build_that_leaves_tests_out_records_no_ranking(
    workdir: Path, sqlite_url: str, git: Git, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "junit.xml", *common]) == 0
    next_commit(workdir, git)
    select = ["select", "--budget", "50%", "--runner", "pytest", "--learning-runs", "0%"]
    assert main([*select, *common]) == 0
    assert "recorded" not in capsys.readouterr().err
    assert main(["ingest", "junit.xml", *common]) == 0

    assert open_store(sqlite_url).shadow_runs("acme/shop") == []


def test_a_learning_run_leaves_nothing_out_and_records_the_ranking(
    workdir: Path, sqlite_url: str, git: Git, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "junit.xml", *common]) == 0
    next_commit(workdir, git)
    capsys.readouterr()
    select = ["select", "--budget", "10%", "--runner", "pytest", "--learning-runs", "100%"]
    assert main([*select, *common]) == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert "learning run" in out.err
    assert "recorded the ranking of 8 tests" in out.err
    assert main(["ingest", "junit.xml", *common]) == 0

    # The next results are measured against the ranking, as in shadow mode.
    (shadow,) = open_store(sqlite_url).shadow_runs("acme/shop")
    assert len(shadow.positions) == 8


def test_select_for_go_prints_one_skip_pattern_without_a_line_ending(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "go.xml").write_bytes((FIXTURES / "gotestsum.xml").read_bytes())
    (workdir / "list.txt").write_text(
        "TestTotalSumsPrices\nTestTotalFailsOnPurpose\nTestSkipped\nTestQuantities\n"
        "ok  \texample.com/shop/cart\t0.006s\n"
        "TestDiscount\nTestFlakyFirstAttempt\nok  \texample.com/shop/pricing\t0.007s\n"
    )
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "go.xml", *common]) == 0
    capsys.readouterr()

    select = ["select", "--budget", "50%", "--runner", "go", "--go-test-list", "list.txt"]
    assert main([*select, "--learning-runs", "0%", *common]) == 0
    out = capsys.readouterr()
    # A trailing \r\n from Windows would stick to the last alternative after "$(...)".
    assert out.out and not out.out.endswith(("\n", "\r"))
    assert out.out.startswith("^")
    assert "leaving out" in out.err


def test_select_for_surefire_prints_exclusions_without_a_line_ending(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    for report in (FIXTURES / "surefire").glob("TEST-*.xml"):
        (workdir / report.name).write_bytes(report.read_bytes())
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "TEST-*.xml", *common]) == 0
    capsys.readouterr()

    select = ["select", "--budget", "50%", "--runner", "surefire", "--learning-runs", "0%"]
    assert main([*select, *common]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("!com.example.shop.")
    assert not out.out.endswith(("\n", "\r"))
    assert "leaving out" in out.err


def test_select_for_nextest_uses_the_recorded_binary_ids(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "nextest.xml").write_bytes((FIXTURES / "nextest.xml").read_bytes())
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "nextest.xml", *common]) == 0
    capsys.readouterr()

    # 10% of the 6 known tests keeps only the failing one, so checkout_total is left out.
    select = ["select", "--budget", "10%", "--runner", "nextest", "--learning-runs", "0%"]
    assert main([*select, *common]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("not ((binary_id(=")
    assert not out.out.endswith(("\n", "\r"))
    # shop::checkout::checkout_total is in binary "shop::checkout", not "shop".
    assert "(binary_id(=shop::checkout) & test(=checkout_total))" in out.out
    assert "test(=tests::fails_on_purpose)" not in out.out


def test_select_for_go_needs_the_test_list(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--db", sqlite_url, "--repo", "acme/shop"]
    assert main(["ingest", "junit.xml", *common]) == 0
    args = ["select", "--budget", "50%", "--runner", "go", "--learning-runs", "0%", *common]
    assert main(args) == 2
    assert "--go-test-list" in capsys.readouterr().err


def test_select_without_history_leaves_nothing_out(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["select", "--budget", "10%", "--runner", "pytest", "--db", sqlite_url, "--repo", "x/y"]
    assert main(args) == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert "nothing is left out" in out.err


@pytest.mark.parametrize(("share", "fraction"), [("0%", 0.0), ("25%", 0.25), ("1", 1.0)])
def test_learning_run_shares_may_be_zero(share: str, fraction: float) -> None:
    assert parse_share(share) == fraction


@pytest.mark.parametrize("share", ["-1%", "101%", "nan", "often"])
def test_learning_run_shares_outside_zero_to_one_hundred_percent_are_refused(share: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_share(share)


@pytest.mark.parametrize(("budget", "fraction"), [("25%", 0.25), ("0.25", 0.25), ("100%", 1.0)])
def test_budgets_are_shares_of_the_known_tests(budget: str, fraction: float) -> None:
    assert parse_budget(budget) == fraction


@pytest.mark.parametrize("budget", ["0", "0%", "150%", "1.5", "-10%", "nan", "a quarter"])
def test_budgets_outside_zero_to_one_hundred_percent_are_refused(budget: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_budget(budget)


def test_shadow_report_without_rankings_says_there_is_nothing_to_measure(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["shadow", "--db", sqlite_url, "--repo", "acme/shop"]) == 0
    assert "no run with a recorded ranking yet" in capsys.readouterr().out


def test_prioritize_records_nothing_without_history(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["prioritize", "--record", "--db", sqlite_url, "--repo", "empty/repo"]) == 0
    assert "recorded" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "cell"),
    [
        ("tests::plain", "`tests::plain`"),
        ("a | b", "`a \\| b`"),  # a bare pipe would end the table cell
        ("uses `code`", "`` uses `code` ``"),
        ("two``ticks", "``` two``ticks ```"),
        ("line\nbreak", "`line break`"),
    ],
)
def test_markdown_code_cells_survive_pipes_backticks_and_newlines(text: str, cell: str) -> None:
    assert markdown_code(text) == cell


def test_report_on_a_fresh_database_works(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--db", sqlite_url, "--repo", "acme/shop"]) == 0
    assert "(0 runs recorded)" in capsys.readouterr().out


def test_bad_report_exits_2_with_a_message(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (workdir / "broken.xml").write_text("<html>")
    assert main(["ingest", "broken.xml", "--db", sqlite_url]) == 2
    assert "testhunch: error: not well-formed XML" in capsys.readouterr().err


def test_glob_that_matches_nothing_is_an_error(
    workdir: Path, sqlite_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ingest", "reports/*.xml", "--db", sqlite_url]) == 2
    assert "no files match" in capsys.readouterr().err


def test_unsupported_database_url_does_not_echo_credentials(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--db", "mysql://root:hunter2@db/prod", "--repo", "x"]) == 2
    err = capsys.readouterr().err
    assert "unsupported database URL scheme 'mysql'" in err
    assert "hunter2" not in err
