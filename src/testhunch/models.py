"""Plain data types shared by the parser, the stores, the CLI and the API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"

    @property
    def is_failure(self) -> bool:
        return self in (Status.FAILED, Status.ERROR)


# Higher is worse. Used to collapse several reports of the same test in one run.
SEVERITY: dict[Status, int] = {
    Status.SKIPPED: 0,
    Status.PASSED: 1,
    Status.FAILED: 2,
    Status.ERROR: 3,
}


@dataclass(frozen=True, slots=True)
class CaseResult:
    """One test's outcome in one run, normalized across JUnit dialects."""

    key: str
    name: str
    suite: str | None
    file: str | None
    status: Status
    duration_ms: int | None
    message: str | None
    occurrences: int = 1
    # Failed and passed within this one run, e.g. on a retry (docs/adr/0005).
    flaky: bool = False


@dataclass(frozen=True, slots=True)
class FileChange:
    """One entry of `git diff --name-status`. `change_type` is git's status letter."""

    path: str
    change_type: str
    old_path: str | None = None


@dataclass(frozen=True, slots=True)
class RunInput:
    repo: str
    commit_sha: str
    report_digest: str
    results: tuple[CaseResult, ...]
    branch: str | None = None
    base_sha: str | None = None
    changes: tuple[FileChange, ...] = ()


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    run_id: int
    created: bool
    results: int


@dataclass(frozen=True, slots=True)
class FlakyTest:
    """A test that both passed and failed on the same commit, i.e. with identical code.

    Across runs of the commit, or within one run when a retry passed (docs/adr/0005).
    """

    key: str
    flaky_commits: int


@dataclass(frozen=True, slots=True)
class SlowTest:
    key: str
    avg_ms: float
    samples: int


@dataclass(frozen=True, slots=True)
class FailingTest:
    key: str
    failures: int
    executions: int


@dataclass(frozen=True, slots=True)
class CaseHistory:
    """What the prioritizer knows about a test over the recent window of runs."""

    key: str
    file: str | None
    failures: int
    executions: int
    runs_since_failure: int | None  # 0 = failed in the newest run; None = no failure in window
