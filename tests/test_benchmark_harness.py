"""The harness of real projects run commit by commit, and its mutants (docs/adr/0011, 0012)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from benchmarks.harness.collect import (
    CommitRun,
    MutantRun,
    Project,
    docker,
    read_run,
    run_commit,
    window,
)
from benchmarks.harness.evaluate import commit_results, mutant_outcome, run_project
from benchmarks.harness.mutate import (
    PYTHON,
    Language,
    Site,
    added_lines,
    apply,
    go_sites,
    mutants,
    python_sites,
)
from testhunch.models import ShadowResult, ShadowRun, Status

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
    (repository / path).write_bytes(content.encode("utf-8"))
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
        assert archive.extractfile("src/src/cart.py").read() == b"print('cart')"  # type: ignore[union-attr]
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


DIFF = """\
diff --git a/src/cart.py b/src/cart.py
index 1..2 100644
--- a/src/cart.py
+++ b/src/cart.py
@@ -3,0 +4,2 @@ def total():
+    a = 1
+    b = 2
@@ -10 +12 @@ def other():
-    old
+    new
@@ -20,2 +21,0 @@
-    gone
-    gone
diff --git a/src/removed.py b/src/removed.py
deleted file mode 100644
--- a/src/removed.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
"""


def test_added_lines_are_read_from_hunk_headers() -> None:
    assert added_lines(DIFF) == {"src/cart.py": {4, 5, 12}}


def sites(found: object) -> list[tuple[int, str, str]]:
    return [(site.line, site.original, site.replacement) for site in found]  # type: ignore[attr-defined]


def test_python_sites_leave_strings_and_comments_alone() -> None:
    source = (
        "def f(a, b=True):\n"
        '    """a == b"""\n'
        '    x = f"{a + 1} and"  # a < b\n'
        "    return a != b or -1 > 2\n"
    )

    assert sites(python_sites(source)) == [
        (1, "True", "False"),
        (3, "+", "-"),
        (3, "1", "2"),
        (4, "!=", "=="),
        (4, "or", "and"),
        (4, "-", "+"),
        (4, "1", "2"),
        (4, ">", "<="),
        (4, "2", "3"),
    ]


def test_go_sites_leave_strings_runes_comments_and_other_operators_alone() -> None:
    source = (
        "package x\n"
        "// a == b\n"
        "func f(a, b int) bool {\n"
        '\ts := "x == y" + `raw ||`\n'
        "\tr := '<'\n"
        "\tc <- 1\n"
        "\ta++\n"
        "\ta += 2\n"
        "\treturn a <= b && true || 0x10 > 3\n"
        "}\n"
    )

    assert sites(go_sites(source)) == [
        (4, "+", "-"),
        (6, "1", "2"),
        (8, "2", "3"),
        (9, "<=", ">"),
        (9, "&&", "||"),
        (9, "true", "false"),
        (9, "||", "&&"),
        (9, ">", "<="),
        (9, "3", "4"),
    ]


def test_a_site_is_applied_at_its_column_only() -> None:
    source = "a = 1 == 1\r\nb = 1\r\n"
    assert apply(source, Site(1, 6, "==", "!=")) == "a = 1 != 1\r\nb = 1\r\n"
    with pytest.raises(ValueError, match="has no"):
        apply(source, Site(2, 0, "==", "!="))


def is_source(path: str) -> bool:
    return path.startswith("src/")


def test_mutants_change_one_token_of_the_lines_the_commit_added(repository: Path) -> None:
    commit(repository, "src/cart.py", "def total(a, b):\n    return a == b\n", "first")
    commit(repository, "tests/test_cart.py", "assert 1 == 1\n", "a test")
    sha = commit(
        repository,
        "src/cart.py",
        "def total(a, b):\n    return a == b\n\n\ndef discount(a):\n    return a > 10 and True\n",
        "adds discount",
    )

    drawn = mutants(repository, "example/project", sha, is_source, PYTHON)

    assert len(drawn) == 3
    assert {mutant.path for mutant in drawn} == {"src/cart.py"}
    assert all(mutant.line == 6 for mutant in drawn)  # never the unchanged line 2, nor the test
    original = git(repository, "show", f"{sha}:src/cart.py") + "\n"
    for mutant in drawn:
        site = Site(mutant.line, mutant.column, mutant.original, mutant.replacement)
        assert mutant.content == apply(original, site)
    # The same project and commit always draw the same mutants.
    assert mutants(repository, "example/project", sha, is_source, PYTHON) == drawn


def test_mutants_that_do_not_compile_are_replaced_by_other_candidates(repository: Path) -> None:
    commit(repository, "src/cart.py", "x = 0\n", "first")
    sha = commit(repository, "src/cart.py", "x = 1 != 2 and 3 < 4\n", "second")
    refuses_equality = Language(python_sites, lambda source: "==" not in source)

    drawn = mutants(repository, "example/project", sha, is_source, refuses_equality, count=10)

    assert drawn
    assert "!=" not in {mutant.original for mutant in drawn}


def shadow_run(*results: tuple[str, Status, bool]) -> ShadowRun:
    return ShadowRun(
        1,
        {key: position for position, (key, _, _) in enumerate(results, start=1)},
        tuple(ShadowResult(key, status, flaky, 10, 2) for key, status, flaky in results),
    )


def test_only_tests_that_passed_on_the_commit_detect_a_mutant(tmp_path: Path) -> None:
    base = shadow_run(
        ("tests.test_cart::test_total", Status.PASSED, False),
        ("tests.test_cart::test_broken", Status.FAILED, False),
        ("tests.test_cart::test_flaky", Status.FAILED, True),
    )
    mutant_report = tmp_path / "mutant.xml"
    mutant_report.write_bytes(
        report(
            ("test_total", "failed", "1.0"),
            ("test_broken", "failed", "1.0"),
            ("test_flaky", "failed", "1.0"),
        )
    )

    def outcome(report: Path | None, check_exit: int | None = None) -> object:
        described = MutantRun(0, "src/cart.py", 1, 0, "==", "!=", check_exit, None, report)
        return mutant_outcome(described, base)

    detected = outcome(mutant_report)
    assert isinstance(detected, ShadowRun)
    assert detected.positions == base.positions
    statuses = {result.key: result.status for result in detected.results}
    assert statuses == {
        "tests.test_cart::test_total": Status.FAILED,
        "tests.test_cart::test_broken": Status.PASSED,
        "tests.test_cart::test_flaky": Status.PASSED,
    }
    passing = tmp_path / "passing.xml"
    passing.write_bytes(report(("test_total", "passed", "1.0"), ("test_broken", "failed", "1.0")))
    assert outcome(passing) == "survived"
    assert outcome(None) == "no_report"
    assert outcome(mutant_report, check_exit=2) == "not_compiled"


def write_mutant(run_directory: Path, index: int, content: bytes | None, check: int | None) -> None:
    directory = run_directory / "mutants" / str(index)
    directory.mkdir(parents=True)
    described = {
        "path": "src/cart.py",
        "line": 1,
        "column": 0,
        "original": "==",
        "replacement": "!=",
    }
    (directory / "mutant.json").write_text(json.dumps(described), encoding="utf-8")
    if check is not None:
        (directory / "check-exit").write_text(str(check), encoding="utf-8")
    if content is not None:
        (directory / "report.xml").write_bytes(content)


def test_detected_mutants_are_scored_against_their_commit_ranking(
    repository: Path, tmp_path: Path
) -> None:
    passing = report(("test_total", "passed", "1.0"), ("test_other", "passed", "1.0"))
    shas = [
        commit(repository, "src/cart.py", "1", "first"),
        commit(repository, "src/cart.py", "2", "second"),
    ]
    runs = []
    for sha in shas:
        directory = tmp_path / "runs" / sha
        write_run(directory, sha, passing)
        record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        record["mutants"] = 3
        (directory / "run.json").write_text(json.dumps(record), encoding="utf-8")
        broken = report(("test_total", "failed", "1.0"), ("test_other", "passed", "1.0"))
        write_mutant(directory, 0, broken, None)
        write_mutant(directory, 1, passing, None)
        write_mutant(directory, 2, None, 1)
        runs.append(read_run(directory))

    project = Project("example/project", end=shas[-1], image="unused", setup="", test="")
    result = run_project(project, repository, runs)

    assert result["mutants"] == {
        "tried": 6,
        "ranked_from_empty_history": 3,
        "not_compiled": 1,
        "no_report": 0,
        "survived": 1,
        "detected": 1,
    }
    half = result["mutant_shadow"][2]
    assert (half["runs"], half["failing_runs"], half["failures"]) == (1, 1, 1)
    # Both classes match src/cart.py by name; test_other sorts first, so 50% of 2 runs it only.
    assert half["caught_runs"] == 0


@pytest.mark.skipif(
    not os.environ.get("TESTHUNCH_TEST_DOCKER"), reason="set TESTHUNCH_TEST_DOCKER=1 to run Docker"
)
def test_the_container_tries_candidates_until_three_compile(
    repository: Path, tmp_path: Path
) -> None:
    # Git for Windows converts line endings on archive unless told not to: the grep below would
    # then see a carriage return. A repository setting that asks for it must not change the files.
    git(repository, "config", "core.autocrlf", "true")
    commit(repository, "value.py", "ok = 0\n", "first")
    sha = commit(repository, "value.py", "ok = 1 == 1 == 1\n", "second")
    case = '<testcase classname="value" name="t">'
    passes = f"<testsuite>{case}</testcase></testsuite>"
    fails = f'<testsuite>{case}<failure message="x"/></testcase></testsuite>'
    project = Project(
        "example/project",
        end=sha,
        image="unused",
        setup="true",
        test=f"if grep -qx 'ok = 1 == 1 == 1' value.py; then printf '{passes}' > \"$REPORT\"; "
        f"else printf '{fails}' > \"$REPORT\"; exit 1; fi",
        sources=r"value\.py",
        check="! grep -q 'ok = 2' value.py",
    )
    image = "busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0"

    run = run_commit(project, repository, sha, tmp_path / "runs", image, docker)

    # The commit passes. Its line has five candidates, 1 == 1 == 1; the first 1 made into 2 fails
    # the check and is replaced by the next candidate, until three have compiled and ran.
    assert (run.test_exit, run.retry) == (0, None)
    compiled = [mutant for mutant in run.mutants if mutant.compiled]
    assert len(compiled) == 3
    assert len(run.mutants) in (3, 4)
    for mutant in run.mutants:
        if (mutant.column, mutant.replacement) == (5, "2"):
            assert (mutant.compiled, mutant.report) == (False, None)
    for mutant in compiled:
        assert mutant.test_exit == 1
        assert b"<failure" in mutant.report.read_bytes()  # type: ignore[union-attr]
