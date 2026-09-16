"""Aggregating the LRTS replay, under the rule docs/adr/0033 fixed before it was measured.

Two things here are decided by that ADR rather than by what the numbers turn out to be.

**Never pool the rows.** Kafka is 68.5 of the 104 million class-test rows, so a mean over trials
would publish a result labelled "ten projects" that is a result about Kafka. Every measure is a
mean per project, then a mean of those.

**Cluster the resampling.** 2 140 builds are not 2 140 independent facts: several builds belong to
one pull request and several re-runs to one commit. The bootstrap resamples projects, and pull
requests inside each project.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

PRIMARY = "apfdc_one_fault"
GUARDRAIL = "position"
RESAMPLES = 10_000


def _slice_values(
    result: Mapping[str, Any], ranking: str, measure: str, first_failure: bool | None
) -> list[tuple[str, float]]:
    """(pull request, value) for every trial of the slice that has this measure.

    `first_failure` None takes every trial, True only the ones whose failing test had never failed,
    False only the others. A trial whose failing tests were all unknown to the ranking is in
    neither slice and the engine already marks it None.
    """
    trials = result["trials"]
    values = result["rankings"][ranking]["per_trial"][measure]
    chosen: list[tuple[str, float]] = []
    for value, flag, pull_request in zip(
        values, trials["first_failure"], trials["pull_requests"], strict=True
    ):
        if value is None or pull_request is None:
            continue
        if first_failure is not None and flag is not first_failure:
            continue
        chosen.append((pull_request, value))
    return chosen


def project_mean(
    result: Mapping[str, Any], ranking: str, measure: str, first_failure: bool | None = None
) -> float | None:
    values = [value for _, value in _slice_values(result, ranking, measure, first_failure)]
    return statistics.fmean(values) if values else None


def mean_of_projects(
    results: Sequence[Mapping[str, Any]],
    ranking: str,
    measure: str,
    first_failure: bool | None = None,
) -> float | None:
    means = [project_mean(r, ranking, measure, first_failure) for r in results]
    known = [mean for mean in means if mean is not None]
    return statistics.fmean(known) if known else None


def difference(
    results: Sequence[Mapping[str, Any]],
    after: str,
    before: str,
    measure: str,
    first_failure: bool | None = None,
    resamples: int = RESAMPLES,
    seed: int = 0,
) -> dict[str, Any]:
    """`after` minus `before`, with a clustered 95% percentile bootstrap interval.

    Paired: both rankings scored the same trials, so the difference is taken trial by trial before
    anything is averaged. Resampling draws projects with replacement, then pull requests with
    replacement inside each drawn project, which is what ADR 0033 fixed.
    """
    per_project: list[dict[str, list[float]]] = []
    for result in results:
        left = _slice_values(result, after, measure, first_failure)
        right = _slice_values(result, before, measure, first_failure)
        if len(left) != len(right):
            raise ValueError("the two rankings did not score the same trials")
        grouped: dict[str, list[float]] = {}
        for (pull_request, a), (_, b) in zip(left, right, strict=True):
            grouped.setdefault(pull_request, []).append(a - b)
        if grouped:
            per_project.append(grouped)
    if not per_project:
        return {"mean": None, "interval": None, "higher_on": 0, "projects": 0}

    def mean_of(drawn: Sequence[dict[str, list[float]]]) -> float:
        return statistics.fmean(
            statistics.fmean([value for values in project.values() for value in values])
            for project in drawn
        )

    observed = mean_of(per_project)
    rng = random.Random(seed)
    resampled = []
    for _ in range(resamples):
        drawn = []
        for _ in range(len(per_project)):
            project = rng.choice(per_project)
            keys = rng.choices(list(project), k=len(project))
            drawn.append({f"{index}": project[key] for index, key in enumerate(keys)})
        resampled.append(mean_of(drawn))
    resampled.sort()
    return {
        "mean": observed,
        "interval": [
            resampled[math.floor(0.025 * resamples)],
            resampled[math.ceil(0.975 * resamples) - 1],
        ],
        "higher_on": sum(
            1
            for project in per_project
            if statistics.fmean([v for values in project.values() for v in values]) > 0
        ),
        "projects": len(per_project),
    }


def verdict(results: Sequence[Mapping[str, Any]], ranking: str) -> dict[str, Any]:
    """The two conditions of ADR 0033, neither of which chose a number.

    1. It clears the guardrail: on the first-failure slice it is not worse than random, so the
       interval of (ranking minus random) on the position is not entirely above zero. Lower is
       better there, which is why the test is on the upper end.
    2. It stays above the baseline it was built to beat: its primary measure is higher than
       `latest-failure`, with the interval of the difference above zero.
    """
    guardrail = difference(results, ranking, "random", GUARDRAIL, first_failure=True)
    primary = difference(results, ranking, "latest-failure", PRIMARY)
    clears = guardrail["interval"] is not None and guardrail["interval"][0] <= 0
    above = primary["interval"] is not None and primary["interval"][0] > 0
    return {
        "guardrail": guardrail,
        "primary": primary,
        "clears_the_guardrail": clears,
        "above_the_baseline": above,
        "ships": clears and above,
    }
