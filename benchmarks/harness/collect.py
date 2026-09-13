"""Run the test suite of each commit of a project's window in its pinned image (docs/adr/0011)."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

IMAGES = Path(__file__).parent / "images"
TIMEOUT_S = 1800  # per step, far above the suites' under a minute: a hang, not a slow test

# Runs in the container: the commit's files arrive as a tar on stdin, the outputs leave as a tar on
# stdout, so nothing depends on bind mounts or on the host's user ids.
CONTAINER_SCRIPT = """
set -eu
out="$PWD/out"
mkdir src "$out"
tar -x -C src
cd src
set +e
timeout "$TIMEOUT_S" sh -c "$SETUP" > "$out/setup.log" 2>&1
echo "$?" > "$out/setup-exit"
if [ "$(cat "$out/setup-exit")" = 0 ]; then
    REPORT="$out/report.xml" timeout "$TIMEOUT_S" sh -c "$TEST" > "$out/test.log" 2>&1
    echo "$?" > "$out/test-exit"
    # A failing suite runs once more, so that failures can be told from flaky ones (ADR 0008).
    if [ "$(cat "$out/test-exit")" != 0 ] && [ -s "$out/report.xml" ]; then
        REPORT="$out/retry.xml" timeout "$TIMEOUT_S" sh -c "$TEST" > "$out/retry.log" 2>&1
        echo "$?" > "$out/retry-exit"
    fi
fi
tar -c -C "$out" .
"""


@dataclass(frozen=True, slots=True)
class Project:
    name: str  # owner/repository on GitHub
    end: str  # the last commit of the window, pinned
    image: str  # a directory of benchmarks/harness/images
    setup: str  # shell run in the checkout: installs the locked dependencies
    test: str  # shell run in the checkout: runs the whole suite, writing JUnit XML to $REPORT
    window: int = 200

    @property
    def slug(self) -> str:
        return self.name.replace("/", "@")

    @property
    def url(self) -> str:
        return f"https://github.com/{self.name}.git"


PROJECTS = {
    project.name: project
    for project in (
        Project(
            "pallets/click",
            end="6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1",
            image="click",
            setup="uv sync --locked --group tests",
            test='uv run --no-sync pytest -p no:cacheprovider --junitxml="$REPORT"',
        ),
        Project(
            "spf13/cobra",
            end="adbc8813901bba65827259daa8e22ff94ec1f30e",
            image="cobra",
            setup="go mod download",
            # -count=1: a result from Go's test cache would not be a run of the commit's tests.
            test='gotestsum --junitfile "$REPORT" -- -count=1 ./...',
        ),
    )
}


@dataclass(frozen=True, slots=True)
class CommitRun:
    sha: str
    image_id: str
    setup_exit: int
    test_exit: int | None  # None when setup failed and the tests never ran
    seconds: float
    report: Path | None  # None when no report was written: the commit was not built
    retry: Path | None = None  # the second run's report, when the first run failed

    @property
    def built(self) -> bool:
        return self.report is not None


Docker = Callable[[Sequence[str], bytes], bytes]


def docker(args: Sequence[str], stdin: bytes = b"") -> bytes:
    completed = subprocess.run(["docker", *args], input=stdin, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"`docker {' '.join(args[:2])}` failed: {detail}")
    return completed.stdout


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def clone(project: Project, cache: Path) -> Path:
    """The project's repository in the cache, holding at least the pinned end commit."""
    repository = cache / project.slug / "repository"
    if not repository.exists():
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", project.url, str(repository)], check=True
        )
    try:
        git(repository, "cat-file", "-e", f"{project.end}^{{commit}}")
    except subprocess.CalledProcessError:
        git(repository, "fetch", "--quiet", "origin", project.end)
    return repository


def window(repository: Path, end: str, size: int) -> list[str]:
    """The `size` most recent first-parent commits up to `end`, oldest first."""
    shas = git(repository, "rev-list", "--first-parent", f"--max-count={size}", end).split()
    return shas[::-1]


def build_image(project: Project, run: Docker = docker) -> str:
    """Build the project's image from its Dockerfile and return the image ID."""
    tag = f"testhunch-harness-{project.image}"
    run(["build", "--quiet", "--tag", tag, str(IMAGES / project.image)], b"")
    return run(["image", "inspect", "--format", "{{.Id}}", tag], b"").decode().strip()


def run_commit(
    project: Project,
    repository: Path,
    sha: str,
    runs: Path,
    image_id: str,
    run: Docker = docker,
) -> CommitRun:
    """Run one commit's suite, unless its outputs are already in `runs/<sha>`."""
    target = runs / sha
    if (target / "run.json").exists():
        return read_run(target)
    archive = subprocess.run(
        ["git", "-C", str(repository), "archive", "--format=tar", sha],
        capture_output=True,
        check=True,
    ).stdout
    started = time.monotonic()
    output = run(
        [
            "run",
            "--rm",
            "--interactive",
            "--env",
            f"SETUP={project.setup}",
            "--env",
            f"TEST={project.test}",
            "--env",
            f"TIMEOUT_S={TIMEOUT_S}",
            "--volume",
            f"testhunch-harness-{project.image}-cache:/home/runner/.cache",
            image_id,
            "sh",
            "-c",
            CONTAINER_SCRIPT,
        ],
        archive,
    )
    seconds = time.monotonic() - started

    partial = runs / f"{sha}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(output)) as outputs:
        outputs.extractall(partial, filter="data")
    setup_exit = int((partial / "setup-exit").read_text())
    record = {
        "sha": sha,
        "image_id": image_id,
        "setup_exit": setup_exit,
        "test_exit": _exit_code(partial / "test-exit"),
        "retry_exit": _exit_code(partial / "retry-exit"),
        "seconds": round(seconds, 1),
    }
    (partial / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
    return read_run(target)


def _exit_code(path: Path) -> int | None:
    return int(path.read_text()) if path.exists() else None


def read_run(directory: Path) -> CommitRun:
    record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    report, retry = directory / "report.xml", directory / "retry.xml"
    return CommitRun(
        sha=record["sha"],
        image_id=record["image_id"],
        setup_exit=record["setup_exit"],
        test_exit=record["test_exit"],
        seconds=record["seconds"],
        report=report if report.exists() and report.stat().st_size else None,
        retry=retry if retry.exists() and retry.stat().st_size else None,
    )
