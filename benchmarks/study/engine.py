"""Replay a project once and score every ranking on every failing trial (docs/adr/0014)."""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from benchmarks.replay import Job, concurrent_groups
from benchmarks.study.history import BuildHistory, RunWindow
from benchmarks.study.metrics import Trial, best_red_at, scores
from benchmarks.study.rankings import Context, Ranking
from benchmarks.study.release_020 import HISTORY_RUNS, CaseHistory
from testhunch.junit import collapse
from testhunch.models import CaseResult

PRIMARY = "apfdc_one_fault"
# The smallest mean improvement that counts (ADR 0014, amended after step 2).
MIN_DIFFERENCE = 0.005
MutantTrials = Callable[[Job, tuple[CaseResult, ...]], list[Trial]]


def job_trial(job: Job, results: Sequence[CaseResult]) -> Trial:
    return Trial(
        job_id=job.job_id,
        tests=tuple(result.key for result in results),
        failing=frozenset(r.key for r in results if r.status.is_failure and not r.flaky),
        durations={result.key: result.duration_ms for result in results},
        changed_files=job.changed_files or (),
    )


class Study:
    """The scoring half of a replay: rank trials from what is recorded, then record.

    Two drivers use it, and they differ only in **when** a job's results become history.
    `study` below walks concurrent groups, which is what RTPTorrent allows: its jobs carry no
    timestamp, so a group is the finest unit that cannot see itself. `benchmarks.lrts.engine`
    sweeps by time instead, because LRTS carries timestamps and its suites run for hours, so a
    build that started long ago may still be running (docs/adr/0033).

    Keeping one scorer is the point: the measures, the guardrail slice and the counts are defined
    once, and a second dataset cannot quietly acquire a second definition of them.
    """

    def __init__(self, rankings: Sequence[Ranking], mutants: MutantTrials | None = None) -> None:
        names = [ranking.name for ranking in rankings]
        if len(set(names)) != len(names):
            raise ValueError(f"rankings share a name: {names}")
        self.rankings = rankings
        self.mutants = mutants
        self.builds = BuildHistory()
        self.window = RunWindow(HISTORY_RUNS)
        self.counts: Counter[str] = Counter()
        self.kinds: list[str] = []
        self.job_ids: list[int] = []
        self.best: list[float | None] = []
        # Per trial: had any of its known failing tests ever failed before? The guardrail of
        # ADR 0018 only means something once the trials are split on this. None when the ranking
        # had seen none of them: that trial belongs to neither slice, since there was nothing to
        # rank them with.
        self.first_failures: list[bool | None] = []
        self.per_ranking: dict[str, list[dict[str, float | None]]] = {name: [] for name in names}

    def rank(self, jobs: Sequence[Job], collapsed: Sequence[tuple[CaseResult, ...]]) -> None:
        """Score every ranking on the failing trials of these jobs, from the history so far."""
        history: list[CaseHistory] | None = None

        def window_history() -> list[CaseHistory]:
            nonlocal history
            if history is None:
                history = self.window.history()
            return history

        context = Context(self.builds, window_history)
        for job, results in zip(jobs, collapsed, strict=True):
            self.counts["jobs"] += 1
            trials = [("job", job_trial(job, results))]
            if self.mutants is not None:
                trials += [("mutant", trial) for trial in self.mutants(job, results)]
            for kind, trial in trials:
                if not trial.failing:
                    continue
                if self.builds.builds == 0:
                    self.counts[f"{kind}s_ranked_from_empty_history"] += 1
                    continue
                self.counts[f"{kind}s_evaluated"] += 1
                self.kinds.append(kind)
                self.job_ids.append(trial.job_id)
                self.best.append(best_red_at(trial, self.builds.records))
                known_failing = [t for t in trial.failing if t in self.builds.records]
                self.first_failures.append(
                    all(self.builds.records[t].failures == 0 for t in known_failing)
                    if known_failing
                    else None
                )
                for ranking in self.rankings:
                    order, known = ranking.order(trial, context)
                    self.per_ranking[ranking.name].append(scores(trial, order, known))

    def record(self, jobs: Sequence[Job], collapsed: Sequence[tuple[CaseResult, ...]]) -> None:
        """Make these jobs history. Everything ranked after this call can see them."""
        changed = [path for job in jobs for path in job.changed_files or ()]
        self.builds.record(collapsed, changed)
        for results in collapsed:
            self.window.record(results)
        self.counts["builds"] += 1

    def result(self) -> dict[str, Any]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "trials": {
                "kinds": self.kinds,
                "job_ids": self.job_ids,
                "best_red_at": self.best,
                "first_failure": self.first_failures,
            },
            "rankings": {
                name: {
                    "means": {
                        kind: means(values, self.kinds, kind) for kind in sorted(set(self.kinds))
                    },
                    "per_trial": {
                        measure: [value[measure] for value in values]
                        for measure in ("apfd", PRIMARY, "red_at", "position")
                    },
                }
                for name, values in self.per_ranking.items()
            },
        }


def study(
    jobs: Iterable[Job], rankings: Sequence[Ranking], mutants: MutantTrials | None = None
) -> dict[str, Any]:
    """Every ranking's scores on the project's failing jobs and detected mutants, trial by trial.

    Jobs are ranked from the builds before their group, then the group is recorded, as in
    `benchmarks.replay`. Trials of the first group, ranked from an empty history, are counted and
    left out for every ranking.
    """
    engine = Study(rankings, mutants)
    for group in concurrent_groups(jobs):
        collapsed = [collapse(job.results) for job in group]
        engine.rank(group, collapsed)
        engine.record(group, collapsed)
    return engine.result()


def means(values: Sequence[Mapping[str, float | None]], kinds: Sequence[str], kind: str) -> Any:
    """The mean of each measure over the trials of a kind, and how many trials it covers."""
    chosen = [value for value, of in zip(values, kinds, strict=True) if of == kind]
    measures = sorted({measure for value in chosen for measure in value})
    result: dict[str, Any] = {}
    for measure in measures:
        known = [value[measure] for value in chosen if value[measure] is not None]
        result[measure] = {
            "mean": statistics.fmean(v for v in known if v is not None) if known else None,
            "trials": len(known),
        }
    return result


def compare(
    before: Mapping[str, float],
    after: Mapping[str, float],
    resamples: int = 10_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Whether `after` beats `before` over the same projects (ADR 0014).

    The mean of the per-project differences needs a 95% percentile bootstrap interval above 0 and
    a value of at least `MIN_DIFFERENCE`, and `after` must score higher on at least 60% of the
    projects (6 of 10).
    """
    if set(before) != set(after) or not before:
        raise ValueError("both need scores for the same projects")
    projects = sorted(before)
    differences = [after[project] - before[project] for project in projects]
    rng = random.Random(seed)
    resampled = sorted(
        statistics.fmean(rng.choices(differences, k=len(differences))) for _ in range(resamples)
    )
    low = resampled[math.floor(0.025 * resamples)]
    high = resampled[math.ceil(0.975 * resamples) - 1]
    wins = sum(1 for difference in differences if difference > 0)
    return {
        "mean_difference": statistics.fmean(differences),
        "interval": [low, high],
        "higher_on": wins,
        "projects": len(projects),
        "beats": low > 0
        and wins >= math.ceil(0.6 * len(projects))
        and statistics.fmean(differences) >= MIN_DIFFERENCE,
        "differences": dict(zip(projects, differences, strict=True)),
    }
