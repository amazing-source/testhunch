"""Replay a CI history through testhunch and score its rankings (docs/adr/0010, 0011, 0015).

Every job is ranked from the history recorded before it, with testhunch's own ranking, then its
results are recorded, as they would have been in CI.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, fields

from testhunch.junit import collapse
from testhunch.models import CaseResult, History, RunInput, ShadowResult, ShadowRun
from testhunch.prioritize import rank
from testhunch.shadow import ShadowPoint
from testhunch.store import SqlStore


@dataclass(frozen=True, slots=True)
class Job:
    """One CI job: its commits, their changed files, and its test results."""

    job_id: int
    commits: frozenset[str]  # empty when the commits are unknown
    changed_files: tuple[str, ...] | None  # None when unknown, which is not an empty change
    results: tuple[CaseResult, ...]


@dataclass(frozen=True, slots=True)
class RankedJob:
    job: Job
    run: ShadowRun  # positions: the ranking made before the job's group was recorded
    order: tuple[str, ...]  # every test of the job, in the order testhunch would run them
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
    """Rank every job from the builds before its group, then record the group's results.

    A group is one build, as in the study's engine: the store sees it as a commit of its own. Each
    job is ranked on its own tests, seeded with its id, as the engine ranks a job (ADR 0015).
    Lazy, so that a project's jobs need not all be in memory: each job is yielded once recorded.
    """
    for number, group in enumerate(concurrent_groups(jobs)):
        history = store.history(repo)
        commit = f"group-{number}:{','.join(sorted(group[0].commits))}"
        collapsed = [collapse(job.results) for job in group]
        rankings = []
        for job, results in zip(group, collapsed, strict=True):
            tests = {result.key for result in results}
            # Only the job's tests, so that a test with no known duration gets their median.
            own = History(history.builds, tuple(c for c in history.cases if c.key in tests))
            rankings.append(rank(own, job.changed_files or (), seed=str(job.job_id)))
        for job, results, ranking in zip(group, collapsed, rankings, strict=True):
            store.ingest(
                RunInput(
                    repo=repo,
                    commit_sha=commit,
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
                # What the ranking expected, as `prioritize --record` stores it (docs/adr/0017).
                {test.key: test.expected_ms for test in ranking},
            )
            yield RankedJob(job, run, tuple(order), cold=history.builds == 0, group=number)


def apfd(order: Sequence[str], failing: Iterable[str]) -> float | None:
    """Average Percentage of Faults Detected, as in the RTPTorrent paper (equation 1).

    APFD(S, F) = 1 - sum(TF(f) for f in F) / (|S| * |F|) + 1 / (2 |S|), where TF(f) is the position
    of the first test that detects fault f, and each failing test counts as one fault.
    Undefined without a fault.
    """
    positions = {test: index for index, test in enumerate(order, start=1)}
    faults = [positions[test] for test in set(failing)]
    if not faults or not order:
        return None
    size = len(order)
    return 1 - sum(faults) / (size * len(faults)) + 1 / (2 * size)


def failing_tests(results: Iterable[ShadowResult]) -> set[str]:
    return {result.key for result in results if result.status.is_failure}


def add_points(a: ShadowPoint, b: ShadowPoint) -> ShadowPoint:
    """The totals of two evaluations at the same budget: every count adds up."""
    if a.fraction != b.fraction:
        raise ValueError(f"budgets differ: {a.fraction} and {b.fraction}")
    return ShadowPoint(
        a.fraction,
        *(getattr(a, f.name) + getattr(b, f.name) for f in fields(ShadowPoint)[1:]),
    )
