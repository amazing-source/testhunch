"""What skipping tests would have missed, measured on runs that ran everything (docs/adr/0006).

A recorded ranking is evaluated after the fact, for several budgets: running only the top
`fraction` of the tests it ranked, plus any test it did not know.
"""

from __future__ import annotations

import hashlib
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
    # The same, counting only failures confirmed by retries (docs/adr/0008).
    confirmed_failing_runs: int
    caught_confirmed_runs: int
    confirmed_failures: int
    caught_confirmed_failures: int
    tests_run: int
    tests_total: int
    time_run_ms: int
    time_total_ms: int  # results with a known duration only


def is_learning_run(repo: str, commit_sha: str, share: float) -> bool:
    """Whether this commit's build runs every test and records its ranking (docs/adr/0009).

    A hash of the repository and the commit, so every job of a build agrees and a re-run build
    gets the same answer, independently of what the change contains.
    """
    digest = hashlib.sha256(f"{repo}\0{commit_sha}".encode()).digest()
    return int.from_bytes(digest[:8], "big") < share * 2**64


def budget_size(fraction: float, known_tests: int) -> int:
    """How many of the top-ranked known tests a budget runs; `testhunch select` cuts the same."""
    # Rounded first so that 0.7 * 10 == 7.000000000000001 runs 7 tests, not 8.
    return math.ceil(round(fraction * known_tests, 9))


def evaluate(runs: Sequence[ShadowRun], fractions: Sequence[float] = BUDGETS) -> list[ShadowPoint]:
    return [_evaluate(runs, fraction) for fraction in fractions]


def _evaluate(runs: Sequence[ShadowRun], fraction: float) -> ShadowPoint:
    failing_runs = caught_runs = failures = caught_failures = 0
    confirmed_runs = caught_confirmed_runs = confirmed = caught_confirmed = 0
    tests_run = tests_total = time_run = time_total = 0
    for run in runs:
        cutoff = budget_size(fraction, len(run.positions))
        run_failures = run_caught = run_confirmed = run_caught_confirmed = 0
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
                if result.confirmed_failure:
                    run_confirmed += 1
                    run_caught_confirmed += selected
        failing_runs += run_failures > 0
        caught_runs += run_caught > 0
        failures += run_failures
        caught_failures += run_caught
        confirmed_runs += run_confirmed > 0
        caught_confirmed_runs += run_caught_confirmed > 0
        confirmed += run_confirmed
        caught_confirmed += run_caught_confirmed
    return ShadowPoint(
        fraction=fraction,
        runs=len(runs),
        failing_runs=failing_runs,
        caught_runs=caught_runs,
        failures=failures,
        caught_failures=caught_failures,
        confirmed_failing_runs=confirmed_runs,
        caught_confirmed_runs=caught_confirmed_runs,
        confirmed_failures=confirmed,
        caught_confirmed_failures=caught_confirmed,
        tests_run=tests_run,
        tests_total=tests_total,
        time_run_ms=time_run,
        time_total_ms=time_total,
    )
