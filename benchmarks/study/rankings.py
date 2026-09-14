"""The candidate rankings of the study (docs/adr/0014).

A ranking orders a trial's tests: the ones its history does not know first, in the job's order,
then the known ones. Ties are broken by a hash of the job and the test, shared by every ranking.
"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from benchmarks.study.history import BuildHistory, CaseRecord
from benchmarks.study.metrics import EPSILON_MS, Trial
from testhunch.models import CaseHistory
from testhunch.prioritize import changed_stems, rank


@dataclass(frozen=True, slots=True)
class Context:
    """What is known when a trial is ranked: the builds before its build."""

    builds: BuildHistory
    window: Callable[[], list[CaseHistory]]  # the 0.2.0 store's history, computed on demand


class Ranking(Protocol):
    @property
    def name(self) -> str: ...

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        """The trial's tests in the order they would run, and how many of them are known."""
        ...


def tie(job_id: int, key: str) -> bytes:
    return hashlib.sha256(f"{job_id}\0{key}".encode()).digest()


def split_known(trial: Trial, builds: BuildHistory) -> tuple[list[str], list[str]]:
    unknown = [test for test in trial.tests if test not in builds.records]
    known = [test for test in trial.tests if test in builds.records]
    return unknown, known


@dataclass(frozen=True, slots=True)
class LatestFailure:
    """The tests that failed most recently first: RTPTorrent's priority, alpha = 0.8.

    With alpha > 0.5 the newest failure outweighs all older ones together, so sorting by the newest
    failure, then by the priority at that build, gives the priority's order without its underflow.
    """

    name: str = "latest-failure"

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        unknown, known = split_known(trial, context.builds)
        records = context.builds.records
        known.sort(key=lambda test: _latest_failure_key(records[test], trial.job_id, test))
        return unknown + known, len(known)


def _latest_failure_key(record: CaseRecord, job_id: int, test: str) -> tuple[int, float, bytes]:
    return (-record.last_failure, -record.priority, tie(job_id, test))


@dataclass(frozen=True, slots=True)
class ProductRanking:
    """testhunch 0.2.0's own ranking, from the store's window of runs (ADR 0010)."""

    name: str = "testhunch-0.2.0"

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        return product_order(trial.tests, context.window(), trial.changed_files)


def product_order(
    tests: Sequence[str], history: list[CaseHistory], changed_files: Sequence[str]
) -> tuple[list[str], int]:
    """The order `benchmarks.replay` gives a job: unknown tests first, then by rank."""
    positions = {test.key: index for index, test in enumerate(rank(history, changed_files), 1)}
    order = sorted(tests, key=lambda key: (key in positions, positions.get(key, 0)))
    return order, sum(1 for test in tests if test in positions)


SIGNALS = ("failure_rate", "transitions", "file_failures", "name")


@dataclass(frozen=True, slots=True)
class Candidate:
    """The latest failure with signals added, as a step of the study commits them (ADR 0014).

    A known test scores its failure priority plus each signal times its weight. With a time
    exponent the score is divided by the expected duration to that power, and shorter tests go
    first among equal scores. With a window, a test that has not run in that many builds counts as
    unknown, and runs first like a new one. Without signals it orders as `LatestFailure`.
    """

    name: str
    weights: tuple[tuple[str, float], ...] = ()
    time_exponent: float | None = None
    window: int | None = None

    def __post_init__(self) -> None:
        unknown = {signal for signal, _ in self.weights} - set(SIGNALS)
        if unknown:
            raise ValueError(f"unknown signals: {sorted(unknown)}")

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        builds = context.builds
        records = builds.records
        now = builds.builds
        unknown: list[str] = []
        known: list[str] = []
        for test in trial.tests:
            record = records.get(test)
            stale = (
                self.window is not None
                and record is not None
                and record.last_run < now - self.window
            )
            (unknown if record is None or stale else known).append(test)
        signals = {name: _signal(name, trial, context) for name, _ in self.weights}
        durations = _expected_durations(known, records) if self.time_exponent is not None else {}

        def key(test: str) -> tuple[float, float, int, float, bytes]:
            record = records[test]
            score = record.priority_at(now)
            for name, weight in self.weights:
                score += weight * signals[name](test)
            duration = durations.get(test, 1.0)
            if self.time_exponent:
                score /= duration**self.time_exponent
            return (
                -score,
                duration,
                -record.last_failure,
                -record.priority,
                tie(trial.job_id, test),
            )

        known.sort(key=key)
        return unknown + known, len(known)


def _signal(name: str, trial: Trial, context: Context) -> Callable[[str], float]:
    builds = context.builds
    records = builds.records
    if name == "failure_rate":
        return lambda test: records[test].failures / records[test].runs
    if name == "transitions":
        return lambda test: records[test].transition_priority_at(builds.builds)
    if name == "file_failures":
        changed = [path for path in set(trial.changed_files) if builds.file_changes.get(path)]

        def file_failures(test: str) -> float:
            # The highest share of a changed file's past changes that this test failed after.
            return max(
                (
                    builds.file_failures.get(path, {}).get(test, 0) / builds.file_changes[path]
                    for path in changed
                ),
                default=0.0,
            )

        return file_failures
    if name == "name":
        stems = changed_stems(trial.changed_files)

        def name_match(test: str) -> float:
            haystack = f"{records[test].file or ''} {test}".lower()
            return float(any(s in haystack for s in stems))

        return name_match
    raise ValueError(f"unknown signal: {name}")


def _expected_durations(known: Sequence[str], records: dict[str, CaseRecord]) -> dict[str, float]:
    """Each known test's mean past duration, plus the epsilon of ADR 0014.

    A test with no known past duration gets the median of the others in the job: a ranking needs
    some cost to order it by, and the median neither favours nor buries it.
    """
    means = {test: records[test].mean_duration_ms() for test in known}
    measured = [mean for mean in means.values() if mean is not None]
    fallback = statistics.median(measured) if measured else 0.0
    return {
        test: (mean if mean is not None else fallback) + EPSILON_MS for test, mean in means.items()
    }
