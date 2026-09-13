"""The harness of real projects run commit by commit (docs/adr/0011)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from benchmarks.harness.collect import CommitRun, Project, docker, read_run, run_commit, window
from benchmarks.harness.evaluate import commit_results, run_project
from testhunch.models import Status

PROJECT = Project("example/project", end="HEAD", image="unused", setup="true", test="true")


def git(repository: Path, *args: str) -> str:
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    ).stdout.strip()


def commit(repository: Path, path: str, content: str, message: str) -> str:
    (repository / path).parent.mkdir(parents=True, exist_ok=True)
    (repository / path).write_text(content, encoding="utf-8")
    git(repository, "add", path)
    git(repository, "commit", "--quiet", "-m", message)
    return git(repository, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    path = tmp_path / "repository"
    path.mkdir()
    git(path, "init", "--quiet", "--initial-branch=main")
    return path


def report(*cases: tuple[str, str, str]) -> bytes:
    """A pytest-style report of (test name, outcome, seconds)."""
    body = []
    for name, outcome, seconds in cases:
        inner = {"passed": "", "failed": '<failure message="boom"/>'}[outcome]
        body.append(
            f'<testcase classname="tests.test_cart" name="{name}" time="{seconds}">{inner}'
            "</testcase>"
        )
    return f"<testsuites><testsuite name='pytest'>{''.join(body)}</testsuite></testsuites>".encode()


def outputs(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(f"./{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def test_the_window_follows_first_parents_oldest_first(repository: Path) -> None:
    first = commit(repository, "src/cart.py", "1", "first")
    git(repository, "switch", "--quiet", "-c", "feature")
    commit(repository, "src/user.py", "1", "on the feature branch")
    git(repository, "switch", "--quiet", "main")
    second = commit(repository, "src/cart.py", "2", "second")
    git(repository, "merge", "--quiet", "--no-ff", "-m", "merge", "feature")
    merge = git(repository, "rev-parse", "HEAD")

    assert window(repository, merge, 10) == [first, second, merge]
    assert window(repository, merge, 2) == [second, merge]


class FakeDocker:
    def __init__(self, answer: bytes) -> None:
        self.answer = answer
        self.calls: list[tuple[list[str], bytes]] = []

    def __call__(self, args: Sequence[str], stdin: bytes) -> bytes:
        self.calls.append((list(args), stdin))
        return self.answer


def test_a_commit_runs_from_its_archive_and_is_not_run_twice(
    repository: Path, tmp_path: Path
) -> None:
    sha = commit(repository, "src/cart.py", "print('cart')", "first")
    fake = FakeDocker(
        outputs(
            {
                "setup-exit": b"0\n",
                "test-exit": b"1\n",
                "retry-exit": b"0\n",
                "report.xml": report(("test_total", "failed", "0.5")),
                "retry.xml": report(("test_total", "passed", "0.4")),
            }
        )
    )

    run = run_commit(PROJECT, repository, sha, tmp_path / "runs", "sha256:image", fake)

    ((args, stdin),) = fake.calls
    assert f"SETUP={PROJECT.setup}" in args and "sha256:image" in args
    with tarfile.open(fileobj=io.BytesIO(stdin)) as archive:
        assert archive.extractfile("src/cart.py").read() == b"print('cart')"  # type: ignore[union-attr]
    assert (run.built, run.setup_exit, run.test_exit) == (True, 0, 1)
    assert run.retry is not None
    record = json.loads((tmp_path / "runs" / sha / "run.json").read_text(encoding="utf-8"))
    assert record["retry_exit"] == 0

    assert run_commit(PROJECT, repository, sha, tmp_path / "runs", "sha256:image", fake) == run
    assert len(fake.calls) == 1


def test_a_commit_whose_setup_fails_is_recorded_as_not_built(
    repository: Path, tmp_path: Path
) -> None:
    sha = commit(repository, "src/cart.py", "1", "first")
    fake = FakeDocker(outputs({"setup-exit": b"1\n", "setup.log": b"no lockfile"}))

    run = run_commit(PROJECT, repository, sha, tmp_path / "runs", "sha256:image", fake)

    assert (run.built, run.setup_exit, run.test_exit, run.report) == (False, 1, None, None)
    assert read_run(tmp_path / "runs" / sha) == run


def write_run(
    directory: Path, sha: str, first: bytes | None, retry: bytes | None = None
) -> CommitRun:
    directory.mkdir(parents=True)
    for name, content in (("report.xml", first), ("retry.xml", retry)):
        if content is not None:
            (directory / name).write_bytes(content)
    record = {"sha": sha, "image_id": "sha256:image", "setup_exit": 0 if first else 1,
              "test_exit": None, "retry_exit": None, "seconds": 1.0}  # fmt: skip
    (directory / "run.json").write_text(json.dumps(record), encoding="utf-8")
    return read_run(directory)


def test_a_retry_tells_flaky_failures_from_confirmed_ones(tmp_path: Path) -> None:
    run = write_run(
        tmp_path / "run",
        "abc",
        report(("test_flaky", "failed", "1.0"), ("test_broken", "failed", "2.0")),
        report(("test_flaky", "passed", "3.0"), ("test_broken", "failed", "4.0")),
    )

    results = {result.name: result for result in commit_results(run)}

    assert results["test_flaky"].flaky and results["test_flaky"].status is Status.FAILED
    assert results["test_broken"].confirmed_failure
    # The retry repeats the suite: durations stay those of the first run.
    assert (results["test_flaky"].duration_ms, results["test_broken"].duration_ms) == (1000, 2000)


def test_evaluation_ranks_each_built_commit_from_the_commits_before_it(
    repository: Path, tmp_path: Path
) -> None:
    runs = []
    shas = [
        commit(repository, "src/cart.py", "1", "first"),
        commit(repository, "src/user.py", "1", "not built"),
        commit(repository, "src/cart.py", "2", "breaks the cart"),
        commit(repository, "src/cart.py", "3", "breaks it again"),
    ]
    reports = [
        report(("test_total", "passed", "1.0"), ("test_other", "passed", "1.0")),
        None,
        report(("test_total", "failed", "1.0"), ("test_other", "passed", "1.0")),
        report(("test_total", "failed", "1.0"), ("test_other", "passed", "1.0")),
    ]
    for sha, content in zip(shas, reports, strict=True):
        runs.append(write_run(tmp_path / "runs" / sha, sha, content, content))

    result = run_project(PROJECT, repository, runs)

    assert result["commits"] == {
        "collected": 4,
        "built": 3,
        "not_built": [shas[1]],
        "ranked_from_empty_history": 1,
        "evaluated": 2,
        "evaluated_failing": 2,
    }
    ten_percent = result["shadow"][0]
    # The third commit knows test_total only as a pass; the fourth has seen it fail just before.
    assert (ten_percent["failing_runs"], ten_percent["caught_runs"]) == (2, 1)


@pytest.mark.skipif(
    not os.environ.get("TESTHUNCH_TEST_DOCKER"), reason="set TESTHUNCH_TEST_DOCKER=1 to run Docker"
)
def test_the_container_script_runs_setup_tests_and_the_retry_in_docker(
    repository: Path, tmp_path: Path
) -> None:
    sha = commit(repository, "fails-once.sh", "exit 0", "first")
    project = Project(
        "example/project",
        end=sha,
        image="unused",
        setup="echo installed",
        # Fails the first time it runs in this container, passes the second.
        test='if [ -e ../ran ]; then printf "<testsuite/>" > "$REPORT"; exit 0; fi; '
        'touch ../ran; printf "<testsuite/>" > "$REPORT"; exit 1',
    )
    image = "busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0"

    run = run_commit(project, repository, sha, tmp_path / "runs", image, docker)

    assert (run.setup_exit, run.test_exit, run.built, run.retry is not None) == (0, 1, True, True)
    assert (tmp_path / "runs" / sha / "setup.log").read_text(encoding="utf-8") == "installed\n"
    assert json.loads((tmp_path / "runs" / sha / "run.json").read_text())["retry_exit"] == 0
