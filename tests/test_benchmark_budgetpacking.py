"""Comparing the three budget packing rules on the same rankings (docs/adr/0029)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.budgetpacking import main, markdown, rate, run_project
from benchmarks.replay import Job
from testhunch.models import CaseResult, Status
from testhunch.shadow import PACKINGS

EXTRACT = Path(__file__).parent / "fixtures" / "rtptorrent" / "adamfisk@LittleProxy"


def result(key: str, status: Status = Status.PASSED, duration_ms: int = 10) -> CaseResult:
    return CaseResult(key, key, None, None, status, duration_ms, None)


def job(job_id: int, commit: str, *results: CaseResult) -> Job:
    return Job(job_id, frozenset({commit}), (), results)


def test_rate_says_nothing_rather_than_dividing_by_zero() -> None:
    assert rate({"caught_runs": 0, "failing_runs": 0}, "caught_runs", "failing_runs") is None
    assert rate({"caught_runs": 1, "failing_runs": 2}, "caught_runs", "failing_runs") == 0.5


def test_every_rule_is_measured_on_the_same_project(tmp_path: Path) -> None:
    result_of = run_project(EXTRACT) if EXTRACT.exists() else None
    if result_of is None:
        pytest.skip("the RTPTorrent extract fixture is not present")

    assert set(result_of["packing"]) == set(PACKINGS)
    counts = {packing: len(points) for packing, points in result_of["packing"].items()}
    assert len(set(counts.values())) == 1, counts


def test_the_page_reports_every_rule_at_every_budget() -> None:
    one = {
        "project": "acme/shop",
        "evaluated": 3,
        "packing": {
            packing: [
                {
                    "fraction": fraction,
                    "failing_runs": 2,
                    "caught_runs": 1,
                    "failures": 4,
                    "caught_failures": 2,
                    "time_run_ms": 10,
                    "time_total_ms": 100,
                }
                for fraction in (0.1, 0.25, 0.5)
            ]
            for packing in PACKINGS
        },
    }

    page = markdown([one])

    for packing in PACKINGS:
        assert f"| {packing} |" in page
    assert "1 projects, 3 jobs" in page
    assert "50.0%" in page  # caught_runs over failing_runs


def test_a_measured_project_is_left_alone_when_resuming(tmp_path: Path, capsys: object) -> None:
    stored = tmp_path / "acme@shop.json"
    stored.write_text(
        json.dumps(
            {
                "project": "acme@shop",
                "evaluated": 1,
                "packing": {
                    packing: [
                        {
                            "fraction": 0.1,
                            "failing_runs": 1,
                            "caught_runs": 1,
                            "failures": 1,
                            "caught_failures": 1,
                            "time_run_ms": 1,
                            "time_total_ms": 10,
                        }
                    ]
                    for packing in PACKINGS
                },
            }
        ),
        encoding="utf-8",
    )

    # The project is not one of RTPTorrent's, so any attempt to replay it would fail loudly.
    assert main(["acme@shop", "--out", str(tmp_path), "--resume"]) == 0
    assert (tmp_path / "README.md").exists()
