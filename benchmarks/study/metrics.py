"""What one order of a failing job is worth (docs/adr/0014)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from benchmarks.replay import apfd
from testhunch.shadow import budget_size

BUDGETS = (0.1, 0.25, 0.5)
# Added to every duration, as Cheng et al. add 0.001 s: a test reported as 0 ms still takes time.
EPSILON_MS = 1


@dataclass(frozen=True, slots=True)
class Trial:
    """Results to order from the history before their build: a failing job, or a detected mutant."""

    job_id: int
    tests: tuple[str, ...]  # every test that ran, in the job's own order
    failing: frozenset[str]  # failures that are not flaky (ADR 0006), or a mutant's detectors
    durations: Mapping[str, int | None]
    changed_files: tuple[str, ...]


def scores(trial: Trial, order: Sequence[str], known: int) -> dict[str, float | None]:
    """Every measure of ADR 0014 for one order of the trial's tests.

    `order` runs the unknown tests first, so the known ones are its last `known` entries. Time
    measures are None when a duration is unknown.
    """
    if sorted(order) != sorted(trial.tests):
        raise ValueError(f"job {trial.job_id}: the order does not hold the job's tests")
    positions = [index for index, test in enumerate(order) if test in trial.failing]
    if not positions:
        raise ValueError(f"job {trial.job_id} has no failing test to score")
    unknown = len(order) - known
    result: dict[str, float | None] = {"apfd": apfd(order, trial.failing)}
    for fraction in BUDGETS:
        cut = unknown + budget_size(fraction, known)
        result[f"tests_{fraction}"] = float(positions[0] < cut)

    raw = [trial.durations[test] for test in order]
    if any(duration is None for duration in raw):
        result.update(
            {"apfdc_one_fault": None, "apfdc": None, **{f"time_{f}": None for f in BUDGETS}}
        )
        return result
    costs = [duration + EPSILON_MS for duration in raw if duration is not None]
    before = [0] * len(costs)  # time spent before each position
    for index in range(1, len(costs)):
        before[index] = before[index - 1] + costs[index - 1]
    total = before[-1] + costs[-1]
    first = positions[0]
    result["apfdc_one_fault"] = 1 - (before[first] + costs[first] / 2) / total
    result["apfdc"] = sum(
        total - before[position] - costs[position] / 2 for position in positions
    ) / (total * len(positions))
    for fraction in BUDGETS:
        result[f"time_{fraction}"] = float(before[first] + costs[first] <= fraction * total)
    return result
