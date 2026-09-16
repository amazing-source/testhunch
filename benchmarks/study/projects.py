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
# Where `python -m benchmarks.learn train` leaves the fitted model (docs/adr/0030).
MODEL = CACHE / "learned" / "model.pkl"


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


def cold_start(
    current: Candidate, signals: Sequence[str] = PROXIMITY_SIGNALS
) -> tuple[Candidate, ...]:
    """Each signal at each weight, in the two forms of docs/adr/0018.

    `always` is the form the study's steps already tried: the signal is added to every test's
    score. `cold` adds it only to a test whose failure priority is 0, so it speaks exactly where
    the history says nothing and leaves the rest of the ranking untouched.
    """
    candidates: list[Candidate] = []
    for signal in signals:
        for weight in WEIGHTS:
            others = tuple((s, w) for s, w in current.weights if s != signal)
            candidates.append(
                replace(
                    current,
                    name=f"{current.name}/always+{signal}*{weight}",
                    weights=(*others, (signal, weight)),
                )
            )
            candidates.append(
                replace(
                    current,
                    name=f"{current.name}/cold+{signal}*{weight}",
                    cold_weights=((signal, weight),),
                )
            )
    return tuple(candidates)


# The step of ADR 0018: what the proximity signals are worth where the history says nothing. Its
# rule was fixed before any candidate was run, and the guardrail is the first-failure slice.
STEPS["cold-start"] = Step(
    STEP_3_KEPT,
    cold_start(STEP_3_KEPT),
    references=(LatestFailure(), ProductRanking()),
)

# The step that follows it (docs/adr/0018, amended): the same forms, but with the one signal the
# first step could not try, because the code files it under the history signals rather than the
# proximity ones — `name`, which is testhunch 0.2.0's own file-stem affinity. It is selective where
# the five proximity signals are continuous, and being continuous is what sank them.
STEPS["selective"] = Step(
    STEP_3_KEPT,
    cold_start(STEP_3_KEPT, ("name",)),
    references=(LatestFailure(), ProductRanking()),
)

# The last step of ADR 0018, and the last whatever it returns: not another signal, but the cost.
# Dividing a score by a duration arbitrates between tests whose risk is estimated; where the
# history is silent there is nothing to arbitrate, and the divisor buries a slow test whose name
# matches the change — which is what the two steps before measured without naming it.
_NO_COST = replace(STEP_3_KEPT, name=f"{STEP_3_KEPT.name}/cold-free", cold_time_exponent=0.0)
STEPS["cold-free"] = Step(
    STEP_3_KEPT,
    (
        _NO_COST,
        *(
            replace(
                _NO_COST,
                name=f"{_NO_COST.name}+name*{weight}",
                cold_weights=(("name", weight),),
            )
            for weight in WEIGHTS
        ),
    ),
    references=(LatestFailure(), ProductRanking()),
)


# Phase 6 (docs/adr/0030). The step exists only once a model has been fitted, which is deliberate:
# the alternative is a step that silently scores nothing, and every worker process re-reads the
# file, so what they all score is one model rather than one per process.
if MODEL.exists():  # pragma: no cover - depends on whether the model was fitted
    from benchmarks.study.learned import LearnedRanking, load_model

    _MODEL = load_model(MODEL)
    STEPS["learned"] = Step(
        STEP_3_KEPT,
        (
            LearnedRanking(_MODEL),
            LearnedRanking(_MODEL, name="learned+time^1.0", time_exponent=1.0),
        ),
        references=(LatestFailure(), ProductRanking()),
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
    shas = window(repository, project.end, project.window)
    missing = [sha for sha in shas if not (runs_directory / sha / "run.json").exists()]
    if missing:
        # A partial window would be scored as if it were the project's history.
        raise RuntimeError(f"{name}: {len(missing)} of {len(shas)} commits are not collected yet")
    runs = [read_run(runs_directory / sha) for sha in shas]

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


# The study stopped at step 4 (benchmarks/results/study/step-4.md): the held-out projects are
# replayed once, for the reference, testhunch 0.2.0 and every version kept (ADR 0013, 0014).
HELD_OUT_STEP = "held-out"
STEPS[HELD_OUT_STEP] = Step(
    LatestFailure(), (STEP_1_KEPT, STEP_3_KEPT), references=(ProductRanking(),)
)
