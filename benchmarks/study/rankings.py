"""The candidate rankings of the study (docs/adr/0014).

A ranking orders a trial's tests: the ones its history does not know first, in the job's order,
then the known ones. Ties are broken by a hash of the job and the test, shared by every ranking.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from benchmarks.study.history import BuildHistory, CaseRecord
from benchmarks.study.metrics import Trial
from testhunch.models import CaseHistory
from testhunch.prioritize import rank


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
