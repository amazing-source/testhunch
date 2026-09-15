"""Every look at a held-out project leaves a row, and none starts from a loose checkout (ADR 0016).

The rows themselves are what ADR 0016 is for: the flags of ADR 0013 stop an accidental look, these
tests stop a hidden one.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from benchmarks import heldout
from benchmarks.harness.__main__ import main as harness_main
from benchmarks.heldout import LEDGER, NotFrozen, frozen_commit, record_peek
from benchmarks.rtptorrent.__main__ import main as rtptorrent_main
from benchmarks.split import (
    RTPTORRENT_DEVELOPMENT,
    RTPTORRENT_HELD_OUT,
    RTPTORRENT_TRAINING,
    RTPTORRENT_VALIDATION,
)
from benchmarks.study.__main__ import main as study_main


def rows(ledger: Path) -> list[str]:
    return [line for line in ledger.read_text(encoding="utf-8").splitlines() if line[:4] == "| 20"]


def test_the_ledger_is_created_with_its_header_and_one_row_per_look(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(heldout, "frozen_commit", lambda ledger=None: "0" * 40)
    ledger = tmp_path / "log.md"

    record_peek("benchmarks.study held-out", ["a@b"], "candidate-x", "9.9.9", ledger)
    record_peek("benchmarks.study held-out", ["a@b", "c@d"], "candidate-y", "9.9.9", ledger)

    text = ledger.read_text(encoding="utf-8")
    assert text.startswith("# Looks at the held-out projects")
    assert len(rows(ledger)) == 2
    assert "`000000000000` | 9.9.9 | `benchmarks.study held-out` | candidate-y | a@b, c@d |" in text


def test_a_dirty_working_tree_refuses_to_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heldout, "_git", lambda *a: " M src/testhunch/prioritize.py")

    with pytest.raises(NotFrozen, match="uncommitted changes"):
        frozen_commit()


def test_what_a_run_writes_itself_does_not_block_the_next_look(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A campaign is often two commands: the first writes its results and its ledger row, and the
    # second must still run. Those are its output, not the code it replayed (docs/adr/0016).
    answers = {
        ("status", "--porcelain"): (
            " M benchmarks/results/held-out-log.md\n"
            " M benchmarks/results/rtptorrent/apache@sling.json\n"
            "?? benchmarks/results/harness/ollama@ollama.md"
        ),
        ("rev-parse", "HEAD"): "c" * 40,
        ("branch", "--remotes", "--contains", "c" * 40): "  origin/main",
    }
    monkeypatch.setattr(heldout, "_git", lambda *a: answers.get(a, ""))

    assert frozen_commit() == "c" * 40


def test_changed_code_beside_the_results_still_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {
        ("status", "--porcelain"): (
            " M benchmarks/results/held-out-log.md\n M src/testhunch/prioritize.py"
        ),
    }
    monkeypatch.setattr(heldout, "_git", lambda *a: answers.get(a, ""))

    with pytest.raises(NotFrozen, match=r"prioritize\.py"):
        frozen_commit()


def test_a_changed_benchmark_script_is_code_not_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # benchmarks/ holds the replay itself; only benchmarks/results/ is output.
    monkeypatch.setattr(heldout, "_git", lambda *a: " M benchmarks/replay.py")

    with pytest.raises(NotFrozen, match=r"replay\.py"):
        frozen_commit()


def test_a_commit_on_no_remote_branch_refuses_to_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {("status", "--porcelain"): "", ("rev-parse", "HEAD"): "a" * 40}
    monkeypatch.setattr(heldout, "_git", lambda *a: answers.get(a, ""))

    with pytest.raises(NotFrozen, match="on no remote branch"):
        frozen_commit()


def test_a_frozen_pushed_commit_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {
        ("status", "--porcelain"): "",
        ("rev-parse", "HEAD"): "b" * 40,
        ("branch", "--remotes", "--contains", "b" * 40): "  origin/main",
    }
    monkeypatch.setattr(heldout, "_git", lambda *a: answers.get(a, ""))

    assert frozen_commit() == "b" * 40


def test_missing_git_refuses_rather_than_replaying_untraceably(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", no_git)

    with pytest.raises(NotFrozen, match="git is not installed"):
        frozen_commit()


@pytest.mark.parametrize(
    ("command", "arguments", "caches"),
    [
        (study_main, ["held-out", "--held-out"], False),
        (rtptorrent_main, ["SonarSource@sonarqube", "--held-out"], True),
        (harness_main, ["evaluate", "ollama/ollama", "--held-out"], True),
    ],
    ids=["study", "rtptorrent", "harness"],
)
def test_a_loose_checkout_stops_every_held_out_command(
    command: Callable[[Sequence[str]], int],
    arguments: list[str],
    caches: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def loose(ledger: Path | None = None) -> str:
        raise NotFrozen("the working tree has uncommitted changes")

    monkeypatch.setattr(heldout, "frozen_commit", loose)
    monkeypatch.setattr(heldout, "LEDGER", tmp_path / "log.md")
    cache = ["--cache", str(tmp_path / "cache")] if caches else []

    with pytest.raises(SystemExit) as refused:
        command([*arguments, *cache, "--out", str(tmp_path / "out")])

    assert refused.value.code == 2
    assert "uncommitted changes" in capsys.readouterr().err
    # Refused before replaying, cloning or writing anything at all.
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "log.md").exists()


def test_no_row_is_ever_removed_from_the_ledger_in_the_repository() -> None:
    text = LEDGER.read_text(encoding="utf-8")

    # The ledger only grows. These three runs read held-out projects before it existed
    # (docs/adr/0016); a look that disappears from it is the one thing that breaks the guarantee.
    assert "bc417f1d84d6" in text and "ed36f46629c1" in text and "3ed027a61a5c" in text
    assert len(rows(LEDGER)) >= 3
    # Every row carries its six columns, so counting them means something.
    assert all(row.count("|") == 7 for row in rows(LEDGER))


def test_phase_six_chooses_its_model_away_from_the_held_out_projects() -> None:
    assert set(RTPTORRENT_TRAINING) | set(RTPTORRENT_VALIDATION) == set(RTPTORRENT_DEVELOPMENT)
    assert not set(RTPTORRENT_TRAINING) & set(RTPTORRENT_VALIDATION)
    assert not set(RTPTORRENT_VALIDATION) & set(RTPTORRENT_HELD_OUT)
    assert RTPTORRENT_VALIDATION == (
        "doanduyhai@Achilles",
        "facebook@buck",
        "Graylog2@graylog2-server",
        "square@okhttp",
        "thinkaurelius@titan",
    )
