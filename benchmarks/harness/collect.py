"""Run the test suite of each commit of a project's window in its pinned image (docs/adr/0011).

After the commit's own suite, the same container runs it once per mutant of the lines the commit
changed (docs/adr/0012).
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tarfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmarks.harness.mutate import GO, MUTANTS_PER_COMMIT, PYTHON, Language, Mutant, mutants

IMAGES = Path(__file__).parent / "images"
# Candidates sent per commit, in their drawn order: the container tries them until
# MUTANTS_PER_COMMIT have compiled, since only a build can tell that a Go `+` joins strings.
MUTANT_CANDIDATES = 10
TIMEOUT_S = 1800  # per step, far above the suites' under a minute: a hang, not a slow test
SETUP_RETRY_DELAY_S = 30
# This many commits in a row not built says more about the machine (a network outage, Docker)
# than about the project: collection stops so that someone looks before they are recorded.
NOT_BUILT_IN_A_ROW = 3

# Runs in the container: the commit's files (src/) and its mutants (mutants/) arrive as a tar on
# stdin, the outputs leave as a tar on stdout, so nothing depends on bind mounts or host user ids.
CONTAINER_SCRIPT = """
set -eu
out="$PWD/out"
mutants="$PWD/mutants"
mkdir "$out"
tar -x
cd src
set +e
timeout "$TIMEOUT_S" sh -c "$SETUP" > "$out/setup.log" 2>&1
setup=$?
if [ "$setup" != 0 ]; then
    # Tried again before the commit counts as not built: a download fails when the network drops.
    sleep "$SETUP_RETRY_DELAY_S"
    timeout "$TIMEOUT_S" sh -c "$SETUP" > "$out/setup-retry.log" 2>&1
    setup=$?
fi
echo "$setup" > "$out/setup-exit"
if [ "$(cat "$out/setup-exit")" = 0 ]; then
    REPORT="$out/report.xml" timeout "$TIMEOUT_S" sh -c "$TEST" > "$out/test.log" 2>&1
    echo "$?" > "$out/test-exit"
    # A failing suite runs once more, so that failures can be told from flaky ones (ADR 0008).
    if [ "$(cat "$out/test-exit")" != 0 ] && [ -s "$out/report.xml" ]; then
        REPORT="$out/retry.xml" timeout "$TIMEOUT_S" sh -c "$TEST" > "$out/retry.log" 2>&1
        echo "$?" > "$out/retry-exit"
    fi
fi
# Candidates in their drawn order, until $MUTANTS of them compiled and ran (ADR 0012).
index=0
tested=0
while [ -s "$out/report.xml" ] && [ -d "$mutants/$index" ] && [ "$tested" -lt "$MUTANTS" ]; do
    mutant="$mutants/$index"
    result="$out/mutants/$index"
    index=$((index + 1))
    mkdir -p "$result"
    path="$(cat "$mutant/path")"
    cp "$path" "$mutant/original"
    cp "$mutant/file" "$path"
    checked=0
    if [ -n "$CHECK" ]; then
        timeout "$TIMEOUT_S" sh -c "$CHECK" > "$result/check.log" 2>&1
        checked=$?
        echo "$checked" > "$result/check-exit"
    fi
    if [ "$checked" = 0 ]; then
        REPORT="$result/report.xml" timeout "$TIMEOUT_S" sh -c "$TEST" > "$result/test.log" 2>&1
        echo "$?" > "$result/test-exit"
        tested=$((tested + 1))
    fi
    cp "$mutant/original" "$path"
done
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
    sources: str = ""  # a regular expression of the paths mutants may change; empty: no mutants
    language: str = "python"
    check: str = ""  # shell run in the checkout before a mutant's tests: non-zero, not compiled

    @property
    def slug(self) -> str:
        return self.name.replace("/", "@")

    @property
    def url(self) -> str:
        return f"https://github.com/{self.name}.git"

    def is_source(self, path: str) -> bool:
        return bool(self.sources) and re.fullmatch(self.sources, path) is not None


LANGUAGES: dict[str, Language] = {"python": PYTHON, "go": GO}

PROJECTS = {
    project.name: project
    for project in (
        Project(
            "pallets/click",
            end="6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1",
            image="click",
            setup="uv sync --locked --group tests",
            test='uv run --no-sync pytest -p no:cacheprovider --junitxml="$REPORT"',
            sources=r"src/click/.*\.py",
        ),
        Project(
            "spf13/cobra",
            end="adbc8813901bba65827259daa8e22ff94ec1f30e",
            image="cobra",
            setup="go mod download",
            # -count=1: a result from Go's test cache would not be a run of the commit's tests.
            test='gotestsum --junitfile "$REPORT" -- -count=1 ./...',
            sources=r"(?!.*_test\.go$).*\.go",
            language="go",
            check="go build ./...",
        ),
        # Held out (docs/adr/0013): evaluated only for versions frozen before the replay.
        Project(
            "fastapi/fastapi",
            end="50113da16fec53b66b80d75e80a89296de4fa5a5",
            image="fastapi",
            setup="uv sync --locked --no-dev --group tests --extra all",
            # The commit's own script: it sets PYTHONPATH for docs_src and runs pytest-xdist.
            test='uv run --no-sync bash scripts/test.sh -p no:cacheprovider --junitxml="$REPORT"',
            sources=r"fastapi/.*\.py",
        ),
        Project(
            "ollama/ollama",
            end="53fed26112817f7c55f664efb9e3f65f06cab7db",
            image="ollama",
            setup="go mod download",
            test='gotestsum --junitfile "$REPORT" -- -count=1 ./...',
            sources=r"(?!.*_test\.go$).*\.go",
            language="go",
            check="go build ./...",
        ),
    )
}


@dataclass(frozen=True, slots=True)
class MutantRun:
    index: int
    path: str
    line: int
    column: int
    original: str
    replacement: str
    check_exit: int | None  # None when the project has no check
    test_exit: int | None  # None when the check failed and the tests never ran
    report: Path | None

    @property
    def compiled(self) -> bool:
        return self.check_exit in (None, 0)


@dataclass(frozen=True, slots=True)
class CommitRun:
    sha: str
    image_id: str
    setup_exit: int
    test_exit: int | None  # None when setup failed and the tests never ran
    seconds: float
    report: Path | None  # None when no report was written: the commit was not built
    retry: Path | None = None  # the second run's report, when the first run failed
    mutants: tuple[MutantRun, ...] = ()

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


def container_input(repository: Path, sha: str, commit_mutants: Sequence[Mutant]) -> bytes:
    """A tar of the commit's files under src/ and of each mutant under mutants/<index>/."""
    # Files as committed, as a Linux CI checkout has them: Git for Windows sets core.autocrlf, and
    # git archive would then write CRLF line endings.
    as_committed = ("-c", "core.autocrlf=false", "-c", "core.eol=lf")
    archive = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            *as_committed,
            "archive",
            "--format=tar",
            "--prefix=src/",
            sha,
        ],
        capture_output=True,
        check=True,
    ).stdout
    buffer = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(archive)) as commit,
        tarfile.open(fileobj=buffer, mode="w") as combined,
    ):
        for member in commit:
            combined.addfile(member, commit.extractfile(member) if member.isfile() else None)
        for index, mutant in enumerate(commit_mutants):
            for name, text in (("path", mutant.path), ("file", mutant.content)):
                data = text.encode("utf-8")
                info = tarfile.TarInfo(f"mutants/{index}/{name}")
                info.size = len(data)
                combined.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def run_commit(
    project: Project,
    repository: Path,
    sha: str,
    runs: Path,
    image_id: str,
    run: Docker = docker,
    setup_retry_delay_s: int = SETUP_RETRY_DELAY_S,
) -> CommitRun:
    """Run one commit's suite and its mutants', unless their outputs are already in `runs/<sha>`."""
    target = runs / sha
    if (target / "run.json").exists():
        return read_run(target)
    commit_mutants = (
        mutants(
            repository,
            project.name,
            sha,
            project.is_source,
            LANGUAGES[project.language],
            count=MUTANT_CANDIDATES,
        )
        if project.sources
        else []
    )
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
            f"CHECK={project.check}",
            "--env",
            f"MUTANTS={MUTANTS_PER_COMMIT}",
            "--env",
            f"TIMEOUT_S={TIMEOUT_S}",
            "--env",
            f"SETUP_RETRY_DELAY_S={setup_retry_delay_s}",
            "--volume",
            f"testhunch-harness-{project.image}-cache:/home/runner/.cache",
            image_id,
            "sh",
            "-c",
            CONTAINER_SCRIPT,
        ],
        container_input(repository, sha, commit_mutants),
    )
    seconds = time.monotonic() - started

    partial = runs / f"{sha}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(output)) as outputs:
        outputs.extractall(partial, filter="data")
    # The candidates the container tried, a prefix of the drawn order; the rest were not needed.
    tried = [m for i, m in enumerate(commit_mutants) if (partial / "mutants" / str(i)).is_dir()]
    for index, mutant in enumerate(tried):
        described = {key: value for key, value in asdict(mutant).items() if key != "content"}
        path = partial / "mutants" / str(index) / "mutant.json"
        path.write_text(json.dumps(described) + "\n", encoding="utf-8")
    record = {
        "sha": sha,
        "image_id": image_id,
        "setup_exit": int((partial / "setup-exit").read_text()),
        "test_exit": _exit_code(partial / "test-exit"),
        "retry_exit": _exit_code(partial / "retry-exit"),
        "mutants": len(tried),
        "seconds": round(seconds, 1),
    }
    (partial / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
    return read_run(target)


class NotBuiltInARow(RuntimeError):
    """Several consecutive commits were not built: the environment may be at fault."""


def collect(
    project: Project,
    repository: Path,
    shas: Sequence[str],
    runs: Path,
    image_id: str,
    limit: int | None = None,
    allow_not_built: bool = False,
    run: Docker = docker,
    report: Callable[[str], None] = print,
) -> None:
    """Run the commits in window order, at most `limit` new ones, stopping on a run not built."""
    new = not_built = 0
    for number, sha in enumerate(shas, start=1):
        if limit is not None and new >= limit:
            return
        new += not (runs / sha / "run.json").exists()
        commit = run_commit(project, repository, sha, runs, image_id, run)
        status = "built" if commit.built else f"not built (setup exit {commit.setup_exit})"
        report(f"{project.name} {number}/{len(shas)} {sha[:12]} {status}, {commit.seconds:.0f}s")
        not_built = 0 if commit.built else not_built + 1
        if not_built >= NOT_BUILT_IN_A_ROW and not allow_not_built:
            raise NotBuiltInARow(
                f"{project.name}: {not_built} commits in a row were not built, up to {sha}. "
                f"Read their setup logs in {runs}: if the machine was at fault (network, Docker), "
                "delete those runs and collect again; if the project was, pass --allow-not-built."
            )


def read_run(directory: Path) -> CommitRun:
    record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    runs = []
    for index in range(record.get("mutants", 0)):
        mutant = directory / "mutants" / str(index)
        described = json.loads((mutant / "mutant.json").read_text(encoding="utf-8"))
        runs.append(
            MutantRun(
                index=index,
                check_exit=_exit_code(mutant / "check-exit"),
                test_exit=_exit_code(mutant / "test-exit"),
                report=_report(mutant / "report.xml"),
                **described,
            )
        )
    return CommitRun(
        sha=record["sha"],
        image_id=record["image_id"],
        setup_exit=record["setup_exit"],
        test_exit=record["test_exit"],
        seconds=record["seconds"],
        report=_report(directory / "report.xml"),
        retry=_report(directory / "retry.xml"),
        mutants=tuple(runs),
    )


def _exit_code(path: Path) -> int | None:
    return int(path.read_text()) if path.exists() else None


def _report(path: Path) -> Path | None:
    return path if path.exists() and path.stat().st_size else None
