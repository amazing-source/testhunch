"""Replay one development project with the rankings of a study step (docs/adr/0014).

In a module of its own so that worker processes can import it: Windows starts them afresh.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from benchmarks.harness.collect import PROJECTS, clone, read_run, window
from benchmarks.harness.evaluate import commit_jobs, mutant_outcome
from benchmarks.replay import Job, apfd
from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.rtptorrent.schedules import read_schedules
from benchmarks.study.engine import study
from benchmarks.study.metrics import Trial
from benchmarks.study.rankings import (
    HISTORY_SIGNALS,
    PROXIMITY_SIGNALS,
    Candidate,
    LatestFailure,
    ProductRanking,
    Ranking,
)
from testhunch.models import CaseResult, ShadowResult, ShadowRun, Status

CACHE = Path(".benchmark-cache")
AUTHORS_SCHEDULE = "recently-failed"


# The values each added signal is tried with, fixed before any step runs (ADR 0014).
WEIGHTS = (0.1, 0.5, 2.0)
TIME_EXPONENTS = (0.0, 0.5, 1.0)
WINDOWS = (10, 50, 200)


@dataclass(frozen=True, slots=True)
class Step:
    current: Ranking
    candidates: tuple[Ranking, ...] = ()
    references: tuple[Ranking, ...] = ()  # measured for context, never kept

    def rankings(self) -> list[Ranking]:
        return [self.current, *self.candidates, *self.references]


def additions(
    current: Candidate, signals: Sequence[str] = HISTORY_SIGNALS, other_changes: bool = True
) -> tuple[Candidate, ...]:
    """The current version with each signal it does not use yet, at each of its values.

    `other_changes` also tries adding durations and a window, when the current version has none.
    """
    used = {signal for signal, _ in current.weights}
    candidates: list[Candidate] = []
    if other_changes and current.time_exponent is None:
        candidates += [
            replace(current, name=f"{current.name}+time^{exponent}", time_exponent=exponent)
            for exponent in TIME_EXPONENTS
        ]
    for signal in signals:
        if signal not in used:
            candidates += [
                replace(
                    current,
                    name=f"{current.name}+{signal}*{weight}",
                    weights=(*current.weights, (signal, weight)),
                )
                for weight in WEIGHTS
            ]
    if other_changes and current.window is None:
        candidates += [
            replace(current, name=f"{current.name}+window={size}", window=size) for size in WINDOWS
        ]
    return tuple(candidates)


STEPS = {
    "baseline": Step(LatestFailure(), references=(ProductRanking(),)),
    "step-1": Step(
        Candidate("latest-failure"),
        additions(Candidate("latest-failure")),
        references=(ProductRanking(),),
    ),
}
# Kept by step 1 (benchmarks/results/study/step-1.md).
STEP_1_KEPT = Candidate("latest-failure+time^1.0", time_exponent=1.0)
STEPS["step-2"] = Step(
    STEP_1_KEPT, additions(STEP_1_KEPT), references=(LatestFailure(), ProductRanking())
)
# Step 2 kept nothing. The extension step (ADR 0014) tries only the proximity signals: the history
# signals, durations and windows would repeat step 2's candidates exactly.
STEPS["step-3"] = Step(
    STEP_1_KEPT,
    additions(STEP_1_KEPT, PROXIMITY_SIGNALS, other_changes=False),
    references=(LatestFailure(), ProductRanking()),
)
# Kept by step 3 (benchmarks/results/study/step-3.md). The current version changed, so step 4 tries
# every signal it does not use yet, history and proximity alike, and windows (ADR 0014).
STEP_3_KEPT = Candidate(
    "latest-failure+time^1.0+test_file_changed*0.5",
    weights=(("test_file_changed", 0.5),),
    time_exponent=1.0,
)
STEPS["step-4"] = Step(
    STEP_3_KEPT,
    additions(STEP_3_KEPT, (*HISTORY_SIGNALS, *PROXIMITY_SIGNALS)),
    references=(STEP_1_KEPT, LatestFailure(), ProductRanking()),
)


def rankings(step: str) -> list[Ranking]:
    return STEPS[step].rankings()


def run_rtptorrent(project: str, step: str) -> dict[str, Any]:
    directory = fetch_project(project, CACHE / "rtptorrent")
    result = study(iter_jobs(directory), rankings(step))
    schedule = directory / "baseline" / f"{AUTHORS_SCHEDULE}.csv"
    if schedule.exists():
        result["authors_schedule"] = _authors_apfd(read_schedules(schedule), result)
    return {"project": project, "source": "rtptorrent", **result}


def _authors_apfd(schedules: dict[int, tuple[list[str], set[str]]], result: Any) -> Any:
    """The authors' recently-failed APFD and each ranking's, on the jobs their schedule covers."""
    job_ids = result["trials"]["job_ids"]
    covered = [index for index, job_id in enumerate(job_ids) if job_id in schedules]
    authors = [apfd(*schedules[job_ids[index]]) for index in covered]
    compared = [index for index, score in zip(covered, authors, strict=True) if score is not None]
    means = {
        AUTHORS_SCHEDULE: statistics.fmean(s for s in authors if s is not None)
        if compared
        else None
    }
    for name, ranking in result["rankings"].items():
        values = [ranking["per_trial"]["apfd"][index] for index in compared]
        means[name] = statistics.fmean(values) if values else None
    return {"jobs": len(compared), "mean_apfd": means}


def run_harness(name: str, step: str) -> dict[str, Any]:
    project = PROJECTS[name]
    cache = CACHE / "harness"
    repository = clone(project, cache)
    runs_directory = cache / project.slug / "runs"
    runs = [
        read_run(runs_directory / sha)
        for sha in window(repository, project.end, project.window)
        if (runs_directory / sha / "run.json").exists()
    ]

    def mutants(job: Job, results: tuple[CaseResult, ...]) -> list[Trial]:
        commit = ShadowRun(
            job.job_id,
            {},
            tuple(
                ShadowResult(r.key, r.status, r.flaky, r.duration_ms, r.attempts) for r in results
            ),
        )
        trials = []
        for mutant in runs[job.job_id].mutants:
            outcome = mutant_outcome(mutant, commit)
            if isinstance(outcome, ShadowRun):
                trials.append(
                    Trial(
                        job_id=job.job_id,
                        tests=tuple(result.key for result in outcome.results),
                        failing=frozenset(
                            r.key for r in outcome.results if r.status is Status.FAILED
                        ),
                        durations={r.key: r.duration_ms for r in outcome.results},
                        changed_files=job.changed_files or (),
                    )
                )
        return trials

    result = study(commit_jobs(repository, runs), rankings(step), mutants)
    return {"project": name, "source": "harness", **result}


def run(task: tuple[str, str, str]) -> dict[str, Any]:
    source, project, step = task
    if source == "rtptorrent":
        return run_rtptorrent(project, step)
    return run_harness(project, step)
