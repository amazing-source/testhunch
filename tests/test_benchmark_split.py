"""The development and held-out projects of the benchmarks (docs/adr/0013)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.harness.__main__ import main as harness_main
from benchmarks.harness.collect import PROJECTS
from benchmarks.rtptorrent.__main__ import main
from benchmarks.split import (
    HARNESS_DEVELOPMENT,
    HARNESS_HELD_OUT,
    RTPTORRENT_DEVELOPMENT,
    RTPTORRENT_FAILING_JOBS,
    RTPTORRENT_HELD_OUT,
    split,
)


def test_the_rtptorrent_split_is_the_one_the_adr_lists() -> None:
    assert RTPTORRENT_DEVELOPMENT == (
        "brettwooldridge@HikariCP",
        "deeplearning4j@deeplearning4j",
        "doanduyhai@Achilles",
        "dynjs@dynjs",
        "eclipse@jetty.project",
        "facebook@buck",
        "Graylog2@graylog2-server",
        "jOOQ@jOOQ",
        "square@okhttp",
        "thinkaurelius@titan",
    )
    assert RTPTORRENT_HELD_OUT == (
        "adamfisk@LittleProxy",
        "apache@sling",
        "CloudifySource@cloudify",
        "DSpace@DSpace",
        "jcabi@jcabi-github",
        "jsprit@jsprit",
        "julianhyde@optiq",
        "l0rdn1kk0n@wicket-bootstrap",
        "neuland@jade4j",
        "SonarSource@sonarqube",
    )
    assert len(RTPTORRENT_FAILING_JOBS) == 20


def test_each_pair_of_neighbours_in_size_holds_one_project_out() -> None:
    development, held_out = split(RTPTORRENT_FAILING_JOBS)

    ordered = sorted(RTPTORRENT_FAILING_JOBS, key=RTPTORRENT_FAILING_JOBS.__getitem__)
    for index in range(0, len(ordered), 2):
        pair = set(ordered[index : index + 2])
        assert len(pair & set(held_out)) == len(pair & set(development)) == 1


def test_a_project_without_a_pair_is_a_development_project() -> None:
    development, held_out = split({"a@small": 1, "b@medium": 2, "c@large": 3})

    assert "c@large" in development
    assert len(held_out) == 1


def test_every_harness_project_is_either_development_or_held_out() -> None:
    assert not set(HARNESS_DEVELOPMENT) & set(HARNESS_HELD_OUT)
    assert set(HARNESS_DEVELOPMENT) | set(HARNESS_HELD_OUT) == set(PROJECTS)


def test_the_harness_refuses_to_evaluate_held_out_projects_unless_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["evaluate", "pallets/click", "ollama/ollama", "--cache", str(tmp_path)]
    with pytest.raises(SystemExit) as refused:
        harness_main(arguments)

    assert refused.value.code == 2
    assert "ollama/ollama" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())  # refused before cloning anything


def test_the_benchmark_refuses_held_out_projects_unless_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        main(["dynjs@dynjs", "adamfisk@LittleProxy", "--out", str(tmp_path / "out")])

    assert refused.value.code == 2
    assert "adamfisk@LittleProxy" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
