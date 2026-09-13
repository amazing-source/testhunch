"""What skipping tests would have missed, measured on runs that ran everything (docs/adr/0006).

A recorded ranking is evaluated after the fact, for several budgets: running only the top
`fraction` of the tests it ranked, plus any test it did not know.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from testhunch.models import ShadowRun, Status

BUDGETS = (0.1, 0.25, 0.5)


@dataclass(frozen=True, slots=True)
class ShadowPoint:
    """Totals over the evaluated runs for one budget. Counts, not rates: rates hide how few."""

    fraction: float
    runs: int
    failing_runs: int
    caught_runs: int  # failing runs where at least one failure was selected: the build goes red
    failures: int
    caught_failures: int
    tests_run: int
    tests_total: int
    time_run_ms: int
    time_total_ms: int  # results with a known duration only


def evaluate(runs: Sequence[ShadowRun], fractions: Sequence[float] = BUDGETS) -> list[ShadowPoint]:
    return [_evaluate(runs, fraction) for fraction in fractions]


def _evaluate(runs: Sequence[ShadowRun], fraction: float) -> ShadowPoint:
    failing_runs = caught_runs = failures = caught_failures = 0
    tests_run = tests_total = time_run = time_total = 0
    for run in runs:
        # Rounded first so that 0.7 * 10 == 7.000000000000001 selects 7 tests, not 8.
        cutoff = math.ceil(round(fraction * len(run.positions), 9))
        run_failures = run_caught = 0
        for result in run.results:
            if result.status is Status.SKIPPED:
                continue
            position = run.positions.get(result.key)
            selected = position is None or position <= cutoff  # unknown tests always run
            tests_total += 1
            tests_run += selected
            if result.duration_ms is not None:
                time_total += result.duration_ms
                time_run += result.duration_ms if selected else 0
            if result.status.is_failure and not result.flaky:
                run_failures += 1
                run_caught += selected
        failing_runs += run_failures > 0
        caught_runs += run_caught > 0
        failures += run_failures
        caught_failures += run_caught
    return ShadowPoint(
        fraction=fraction,
        runs=len(runs),
        failing_runs=failing_runs,
        caught_runs=caught_runs,
        failures=failures,
        caught_failures=caught_failures,
        tests_run=tests_run,
        tests_total=tests_total,
        time_run_ms=time_run,
        time_total_ms=time_total,
    )
