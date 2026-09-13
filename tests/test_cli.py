"""End to end through the command line, against a real git repository and SQLite."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from testhunch.cli import main, markdown_code
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
