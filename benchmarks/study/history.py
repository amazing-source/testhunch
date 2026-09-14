"""What the study's rankings know about each test before a build (docs/adr/0014).

`BuildHistory` counts in builds, over every earlier build. `RunWindow` rebuilds, without SQL, the
history testhunch 0.2.0 reads from the store: the most recent runs, one run per job.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from testhunch.models import CaseHistory, CaseResult, Status

# RTPTorrent's weight of the newest build in a test's failure priority (Mattis et al., section 4).
ALPHA = 0.8


@dataclass(slots=True)
class CaseRecord:
    runs: int = 0  # builds where the test passed or failed
    failures: int = 0  # builds where it failed
    last_run: int = -1  # the newest build it passed or failed in
    last_failure: int = -1  # the newest build it failed in; -1 when it never failed
    priority: float = 0.0  # RTPTorrent's priority as of `last_failure`
    last_failed: bool = False  # its outcome in the newest build it ran in
    transitions: int = 0  # builds whose outcome differs from the test's previous one
    last_transition: int = -1
    transition_priority: float = 0.0  # the same recurrence over transitions, as of the last one
    duration_total_ms: int = 0
    duration_samples: int = 0
    file: str | None = None  # the latest file reported for the test

    def priority_at(self, build: int) -> float:
        """RTPTorrent's priority P(build - 1): decayed by 1 - alpha per build since a failure."""
        return _decayed(self.priority, self.last_failure, build)

    def transition_priority_at(self, build: int) -> float:
        return _decayed(self.transition_priority, self.last_transition, build)

    def mean_duration_ms(self) -> float | None:
        return self.duration_total_ms / self.duration_samples if self.duration_samples else None


def _decayed(value: float, since: int, build: int) -> float:
    if since < 0:
        return 0.0
    return float(value * (1 - ALPHA) ** (build - 1 - since))


class BuildHistory:
    """Every test's record over the builds recorded so far, numbered from 0.

    It also counts, for each changed file, the builds that changed it and, per test, the ones of
    those builds the test failed in.
    """

    def __init__(self) -> None:
        self.records: dict[str, CaseRecord] = {}
        self.builds = 0
        self.file_changes: dict[str, int] = {}
        self.file_failures: dict[str, dict[str, int]] = {}

    def record(
        self, jobs: Sequence[Sequence[CaseResult]], changed_files: Iterable[str] = ()
    ) -> None:
        """Record one build: the collapsed results of each of its jobs, and the files it changed.

        A test failed in the build when it failed in any job, and ran when any job passed or failed
        it; its duration is the mean of the known durations of its jobs.
        """
        build = self.builds
        failed: dict[str, bool] = {}
        durations: dict[str, list[int]] = {}
        files: dict[str, str] = {}
        for results in jobs:
            for result in results:
                if result.file is not None:
                    files[result.key] = result.file
                if result.status is Status.SKIPPED:
                    continue
                failed[result.key] = failed.get(result.key, False) or result.status.is_failure
                if result.duration_ms is not None:
                    durations.setdefault(result.key, []).append(result.duration_ms)
        for key, did_fail in failed.items():
            record = self.records.get(key)
            if record is None:
                record = self.records[key] = CaseRecord()
            elif did_fail != record.last_failed:
                record.transition_priority = ALPHA + (1 - ALPHA) * record.transition_priority_at(
                    build
                )
                record.transitions += 1
                record.last_transition = build
            if did_fail:
                record.priority = ALPHA + (1 - ALPHA) * record.priority_at(build)
                record.last_failure = build
                record.failures += 1
            record.runs += 1
            record.last_run = build
            record.last_failed = did_fail
            known = durations.get(key)
            if known:
                record.duration_total_ms += round(sum(known) / len(known))
                record.duration_samples += 1
        for key, file in files.items():
            if key in self.records:
                self.records[key].file = file
        failing = [key for key, did_fail in failed.items() if did_fail]
        for path in set(changed_files):
            self.file_changes[path] = self.file_changes.get(path, 0) + 1
            if failing:
                counts = self.file_failures.setdefault(path, {})
                for key in failing:
                    counts[key] = counts.get(key, 0) + 1
        self.builds += 1


class RunWindow:
    """The store's history for testhunch 0.2.0: failures and executions over the last runs.

    Mirrors `SqlStore.history`: a run per ingested job, skipped results left out, a test known
    while it has a result in the window, its file the latest one ever reported.
    """

    def __init__(self, size: int) -> None:
        self.size = size
        self._runs: deque[list[tuple[str, bool]]] = deque()
        self._newest = -1
        self._counts: dict[str, list[int]] = {}  # key -> [failures, executions]
        self._failed_in: dict[str, deque[int]] = {}  # key -> runs in the window it failed in
        self._files: dict[str, str] = {}
        self._suites: dict[str, str | None] = {}

    def record(self, results: Sequence[CaseResult]) -> None:
        self._newest += 1
        run = [(r.key, r.status.is_failure) for r in results if r.status is not Status.SKIPPED]
        for result in results:
            self._suites.setdefault(result.key, result.suite)
            if result.file is not None:
                self._files[result.key] = result.file
        for key, failed in run:
            counts = self._counts.setdefault(key, [0, 0])
            counts[1] += 1
            if failed:
                counts[0] += 1
                self._failed_in.setdefault(key, deque()).append(self._newest)
        self._runs.append(run)
        if len(self._runs) > self.size:
            self._forget(self._runs.popleft())

    def _forget(self, run: list[tuple[str, bool]]) -> None:
        for key, failed in run:
            counts = self._counts[key]
            counts[1] -= 1
            if failed:
                counts[0] -= 1
                self._failed_in[key].popleft()  # the oldest run in the window is the one leaving
            if not counts[1]:
                del self._counts[key]
                self._failed_in.pop(key, None)

    def history(self) -> list[CaseHistory]:
        return [
            CaseHistory(
                key=key,
                file=self._files.get(key),
                failures=failures,
                executions=executions,
                runs_since_failure=(
                    self._newest - self._failed_in[key][-1] if self._failed_in.get(key) else None
                ),
                suite=self._suites.get(key),
            )
            for key, (failures, executions) in sorted(self._counts.items())
        ]
