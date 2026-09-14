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


def is_confirmed_failure(status: Status, flaky: bool, attempts: int | None) -> bool:
    """A failure seen on every attempt, with more than one attempt (docs/adr/0008)."""
    return status.is_failure and not flaky and attempts is not None and attempts > 1


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
    # How many times the test ran in this run, retries included (docs/adr/0008).
    attempts: int = 1

    @property
    def confirmed_failure(self) -> bool:
        """Failed on every one of several attempts: not a flaky failure (ADR 0008)."""
        return is_confirmed_failure(self.status, self.flaky, self.attempts)


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
    """What the prioritizer knows about a test over every earlier build (docs/adr/0015)."""

    key: str
    file: str | None
    builds: int  # builds the test passed or failed in
    failures: int  # builds it failed in
    last_failure: int | None  # the newest build it failed in, numbered from 0; None if never
    priority: float  # RTPTorrent's failure priority as of `last_failure`, 0 if it never failed
    mean_duration_ms: float | None  # over the builds with a known duration; None if none
    # The group before "::" in the key (classname, binary id...), which the key alone cannot give
    # back when the group itself contains "::", as nextest's binary ids do.
    suite: str | None = None


@dataclass(frozen=True, slots=True)
class History:
    """Every known test's history, and how many builds of the repository are recorded."""

    builds: int
    cases: tuple[CaseHistory, ...]


@dataclass(frozen=True, slots=True)
class RankedTest:
    key: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShadowResult:
    key: str
    status: Status
    flaky: bool
    duration_ms: int | None
    attempts: int | None  # None for results recorded before attempts were stored

    @property
    def confirmed_failure(self) -> bool:
        return is_confirmed_failure(self.status, self.flaky, self.attempts)


@dataclass(frozen=True, slots=True)
class ShadowRun:
    """A run, and the ranking recorded for its commit before the run was ingested (ADR 0006)."""

    run_id: int
    positions: dict[str, int]  # test key -> 1-based position in the ranking
    results: tuple[ShadowResult, ...]
