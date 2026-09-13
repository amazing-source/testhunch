"""Replay an RTPTorrent project through testhunch and measure its ranking (docs/adr/0010)."""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from benchmarks.rtptorrent.data import Job
from testhunch.junit import collapse
from testhunch.models import RunInput, ShadowResult, ShadowRun
from testhunch.prioritize import rank
from testhunch.store import SqlStore

HISTORY_RUNS = 50  # the window `testhunch prioritize` and the Action use by default


@dataclass(frozen=True, slots=True)
class RankedJob:
    job: Job
    run: ShadowRun  # positions: the ranking made before the job's group was recorded
    order: tuple[str, ...]  # every test class of the job, in the order testhunch would run them
    cold: bool  # ranked from an empty history
    group: int  # the number of its concurrent group, from 0


def concurrent_groups(jobs: Iterable[Job]) -> Iterator[list[Job]]:
    """Consecutive jobs building the same set of commits, which may have run at the same time."""
    group: list[Job] = []
    for job in jobs:
        if group and group[-1].commits != job.commits:
            yield group
            group = []
        group.append(job)
    if group:
        yield group


def replay(jobs: Iterable[Job], store: SqlStore, repo: str) -> Iterator[RankedJob]:
    """Rank every job from the history before its group, then record the group's results.

    Lazy, so that a project's jobs need not all be in memory: each job is yielded once recorded.
    """
    for number, group in enumerate(concurrent_groups(jobs)):
        history = store.history(repo, HISTORY_RUNS)
        rankings = [(job, rank(history, job.changed_files or ())) for job in group]
        for job, ranking in rankings:
            results = collapse(job.results)
            store.ingest(
                RunInput(
                    repo=repo,
                    commit_sha=",".join(sorted(job.commits)) or f"unknown-commit:{job.job_id}",
                    report_digest=str(job.job_id),
                    results=results,
                )
            )
            positions = {test.key: index for index, test in enumerate(ranking, start=1)}
            classes = [result.key for result in results]
            # Tests the ranking does not know always run (ADR 0006), so they come first.
            order = sorted(classes, key=lambda key: (key in positions, positions.get(key, 0)))
            run = ShadowRun(
                job.job_id,
                positions,
                tuple(
                    ShadowResult(r.key, r.status, r.flaky, r.duration_ms, r.attempts)
                    for r in results
                ),
            )
            yield RankedJob(job, run, tuple(order), cold=not history, group=number)


def apfd(order: Sequence[str], failing: Iterable[str]) -> float | None:
    """Average Percentage of Faults Detected, as in the RTPTorrent paper (equation 1).

    APFD(S, F) = 1 - sum(TF(f) for f in F) / (|S| * |F|) + 1 / (2 |S|), where TF(f) is the position
    of the first test that detects fault f, and each failing test class counts as one fault.
    Undefined without a fault.
    """
    positions = {test: index for index, test in enumerate(order, start=1)}
    faults = [positions[test] for test in set(failing)]
    if not faults or not order:
        return None
    size = len(order)
    return 1 - sum(faults) / (size * len(faults)) + 1 / (2 * size)


def failing_classes(results: Iterable[ShadowResult]) -> set[str]:
    return {result.key for result in results if result.status.is_failure}


def read_schedules(path: Path) -> dict[int, tuple[list[str], set[str]]]:
    """One of the authors' schedules: per job, its distinct test classes in order, and the failing.

    A class listed twice in a job keeps its first position, and fails if any of its rows failed.
    """
    rows: dict[int, list[tuple[int, str, bool]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            failed = int(row["failures"]) + int(row["errors"]) > 0
            rows[int(row["travisJobId"])].append((int(row["index"]), row["testName"], failed))
    schedules: dict[int, tuple[list[str], set[str]]] = {}
    for job_id, entries in rows.items():
        order: list[str] = []
        for _, test, _ in sorted(entries):
            if test not in order:
                order.append(test)
        schedules[job_id] = (order, {test for _, test, failed in entries if failed})
    return schedules
