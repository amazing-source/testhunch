"""What skipping tests would have missed, measured on runs that ran everything (docs/adr/0006).

A recorded ranking is evaluated after the fact, for several budgets: running only the top
`fraction` of the tests it ranked, plus any test it did not know.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass

from testhunch.models import RankedTest, ShadowRun, Status

BUDGETS = (0.1, 0.25, 0.5)

# How a time budget deals with a test that does not fit in what is left (docs/adr/0029).
PREFIX = "prefix"
OVERSIZED = "oversized"
FILL = "fill"
PACKINGS = (PREFIX, OVERSIZED, FILL)
# What testhunch ships, measured against the other two before it was chosen (ADR 0029): at equal
# test time it catches two to three points more failing builds than the prefix rule it replaced.
DEFAULT_PACKING = FILL


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
    # Runs whose ranking was recorded before expected durations were stored, so a time budget
    # cannot be cut for them: they are left out of every count above (docs/adr/0017).
    runs_without_expected_time: int = 0


def is_learning_run(repo: str, commit_sha: str, share: float) -> bool:
    """Whether this commit's build runs every test and records its ranking (docs/adr/0009).

    A hash of the repository and the commit, so every job of a build agrees and a re-run build
    gets the same answer, independently of what the change contains.
    """
    digest = hashlib.sha256(f"{repo}\0{commit_sha}".encode()).digest()
    return int.from_bytes(digest[:8], "big") < share * 2**64


def budget_size(fraction: float, known_tests: int) -> int:
    """How many of the top-ranked known tests a budget of tests runs (`--budget-unit tests`)."""
    # Rounded first so that 0.7 * 10 == 7.000000000000001 runs 7 tests, not 8.
    return math.ceil(round(fraction * known_tests, 9))


def time_budget_size(fraction: float, expected_ms: Sequence[float]) -> int:
    """How long a prefix of the ranking fits in a share of the expected time (docs/adr/0017).

    The prefix rule, kept for callers that want a length rather than a selection. What testhunch
    runs is `budget_ranks`, which since ADR 0029 is not always a prefix.
    """
    return len(budget_ranks(fraction, expected_ms, PREFIX))


def budget_ranks(
    fraction: float, expected_ms: Sequence[float], packing: str = DEFAULT_PACKING
) -> set[int]:
    """The 1-based ranks a time budget runs, under one of the packing rules (docs/adr/0029).

    `expected_ms` is the ranking's own expected duration per test, in ranked order.

    **The ranking's first choice always runs**, whatever it costs, under every rule: a budget that
    runs nothing measures nothing, and that is what "at least one test" has meant since ADR 0017.
    The rules differ only in what happens at a later test that does not fit in what is left:

    - `prefix`: stop there. The order is what the ranking promises, so nothing below a test that
      was left out ever runs.
    - `oversized`: pass over a test that could not have fitted in the whole budget however early it
      came, since no order would have run it, and stop at any other test that does not fit.
    - `fill`: pass over everything that does not fit, to the end of the ranking.
    """
    if not expected_ms:
        return set()
    # Rounded like budget_size, so that a budget meant to fit exactly is not lost to floating point.
    allowed = round(fraction * sum(expected_ms), 9)
    ranks = {1}
    spent = expected_ms[0]
    for rank_, duration in enumerate(expected_ms[1:], 2):
        if round(spent + duration, 9) > allowed:
            if packing == PREFIX:
                break
            if packing == OVERSIZED and round(duration, 9) <= allowed:
                break
            continue
        spent += duration
        ranks.add(rank_)
    return ranks


def budget_selection(
    fraction: float, ranked: Sequence[RankedTest], by_time: bool = True
) -> set[int]:
    """The 1-based ranks a budget runs, by expected time (ADR 0017, 0029) or by count (ADR 0007).

    A budget of tests is still a prefix: there is nothing a test can be too expensive for.
    """
    if not by_time:
        return set(range(1, budget_size(fraction, len(ranked)) + 1))
    return budget_ranks(fraction, [test.expected_ms for test in ranked])


def evaluate(
    runs: Sequence[ShadowRun],
    fractions: Sequence[float] = BUDGETS,
    packing: str = DEFAULT_PACKING,
) -> list[ShadowPoint]:
    return [_evaluate(runs, fraction, packing) for fraction in fractions]


def _evaluate(
    runs: Sequence[ShadowRun], fraction: float, packing: str = DEFAULT_PACKING
) -> ShadowPoint:
    failing_runs = caught_runs = failures = caught_failures = 0
    confirmed_runs = caught_confirmed_runs = confirmed = caught_confirmed = 0
    tests_run = tests_total = time_run = time_total = 0
    without_expected = 0
    for run in runs:
        ranks = selected_ranks(run, fraction, packing)
        if ranks is None:
            # Recorded before expected durations were stored: no time budget can be cut for it.
            without_expected += 1
            continue
        run_failures = run_caught = run_confirmed = run_caught_confirmed = 0
        for result in run.results:
            if result.status is Status.SKIPPED:
                continue
            position = run.positions.get(result.key)
            selected = position is None or position in ranks  # unknown tests always run
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
        runs=len(runs) - without_expected,
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
        runs_without_expected_time=without_expected,
    )


def selected_ranks(
    run: ShadowRun, fraction: float, packing: str = DEFAULT_PACKING
) -> set[int] | None:
    """The ranks the budget runs for this run, or None if the run cannot be cut at all.

    The expected durations are the ones recorded with the ranking, before the run happened: cutting
    with the run's own durations would report a budget nobody could have spent (docs/adr/0017).
    """
    if not run.positions:
        return set()  # nothing was ranked, so nothing is left out: every test is unknown
    if not run.expected_ms:
        return None
    ordered = sorted(run.positions, key=lambda key: run.positions[key])
    return budget_ranks(fraction, [run.expected_ms.get(key, 0.0) for key in ordered], packing)
