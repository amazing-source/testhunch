"""Failing jobs split by whether their tests had ever failed before (benchmarks/firstfailures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks import firstfailures, heldout
from benchmarks.firstfailures import FIRST, REPEATED, main, markdown, measure, position, red_at
from benchmarks.study.metrics import Trial
from benchmarks.study.rankings import LatestFailure

EXTRACT = Path(__file__).parent / "fixtures" / "rtptorrent" / "adamfisk@LittleProxy"


def trial(tests: str, failing: str, durations: dict[str, int | None] | None = None) -> Trial:
    known = durations if durations is not None else dict.fromkeys(tests, 10)
    return Trial(1, tuple(tests), frozenset(failing), known, ())


def test_position_is_where_the_first_failure_sits_normalised() -> None:
    assert position("abcd", frozenset("c")) == 0.75
    assert position("abcd", frozenset("a")) == 0.25
    assert position("abcd", frozenset("bd")) == 0.5  # the first of them, not the last


def test_an_order_without_a_failing_test_is_refused() -> None:
    with pytest.raises(ValueError, match="no failing test"):
        position("ab", frozenset("z"))


def test_red_at_is_the_share_of_time_spent_when_the_build_turns_red() -> None:
    # Costs with the 1 ms epsilon: a 10, b 20, c 30; b ends at 30 of 60.
    job = trial("abc", "b", {"a": 9, "b": 19, "c": 29})

    assert red_at("abc", job) == pytest.approx(30 / 60)


def test_red_at_is_unknown_when_a_duration_is() -> None:
    assert red_at("ab", trial("ab", "b", {"a": None, "b": 5})) is None


def test_a_job_is_a_first_failure_only_while_no_known_failing_test_has_failed_before() -> None:
    rankings = {"latest-failure": LatestFailure()}

    totals = measure("adamfisk@LittleProxy", rankings)

    # The extract holds both kinds, and every job counted lands in exactly one slice.
    assert totals[FIRST]["jobs"] and totals[REPEATED]["jobs"]
    for values in totals.values():
        assert len(values["latest-failure:position"]) == len(values["jobs"])


def test_the_random_baseline_is_seeded_so_the_page_can_be_reproduced() -> None:
    rankings = {"latest-failure": LatestFailure()}

    first = measure("adamfisk@LittleProxy", rankings)
    again = measure("adamfisk@LittleProxy", rankings)

    assert first[FIRST]["random:position"] == again[FIRST]["random:position"]


def test_the_page_reports_both_slices_and_says_to_read_the_columns_together() -> None:
    totals = {
        REPEATED: {"jobs": [1.0, 1.0], "testhunch:position": [0.1, 0.3], "testhunch:red_at": [0.2]},
        FIRST: {"jobs": [1.0], "testhunch:position": [0.9], "testhunch:red_at": [0.5]},
    }

    page = markdown(totals, ["testhunch"])

    assert "failing tests had failed before (2 jobs)" in page
    assert "failing tests had never failed before (1 job)" in page  # singular, not "1 jobs"
    assert "| testhunch | 0.200 | - | 0.200 |" in page
    assert "no predictive power can still beat random on `red_at`" in page


def test_held_out_projects_are_refused_without_the_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        main(["SonarSource@sonarqube", "--out", str(tmp_path / "page.md")])

    assert refused.value.code == 2
    assert "SonarSource@sonarqube" in capsys.readouterr().err
    assert not (tmp_path / "page.md").exists()


def test_a_held_out_run_records_its_look_before_replaying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def loose(ledger: Path | None = None) -> str:
        raise heldout.NotFrozen("the working tree has uncommitted changes")

    monkeypatch.setattr(heldout, "frozen_commit", loose)
    monkeypatch.setattr(heldout, "LEDGER", tmp_path / "log.md")

    with pytest.raises(SystemExit) as refused:
        main(["SonarSource@sonarqube", "--held-out", "--out", str(tmp_path / "page.md")])

    assert refused.value.code == 2
    assert "uncommitted changes" in capsys.readouterr().err
    assert not (tmp_path / "log.md").exists() and not (tmp_path / "page.md").exists()


def test_the_published_page_holds_the_measurement_of_the_development_projects() -> None:
    page = firstfailures.DEFAULT_OUT.read_text(encoding="utf-8")

    assert page.startswith("# Testhunch on a test's first failure")
    assert REPEATED in page and FIRST in page
