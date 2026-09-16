"""Replaying LRTS under docs/adr/0033: a build knows only what had finished when it started.

RTPTorrent's jobs carry no timestamp, so its replay ranks a group of jobs from everything before
that group. LRTS carries a start time and a duration, and its suites run for hours: 29 980 of its
34 645 builds overlap another. Grouping would let a build read results that were not available when
it was scheduled, so this sweeps instead. **A build's history is the builds that finished before it
started**, which is the rule the ADR fixed before anything was measured.

The scoring is `benchmarks.study.engine.Study`, unchanged and shared with the RTPTorrent study, so
the measures and the guardrail slice have one definition and not two.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from benchmarks.firstfailures import shuffled
from benchmarks.lrts.data import Archive, Build, BuildMeta
from benchmarks.replay import Job
from benchmarks.study.engine import Study
from benchmarks.study.metrics import Trial
from benchmarks.study.projects import MODEL, STEP_3_KEPT
from benchmarks.study.rankings import Context, LatestFailure, ProductRanking, Ranking
from testhunch.models import CaseResult


@dataclass(frozen=True, slots=True)
class Shuffled:
    """The guardrail's bar: the trial's tests in a random order.

    Not a candidate, and not a new ranking either. The shuffle is `benchmarks.firstfailures`'s own,
    seeded once per replay so that rerunning this scores the same order for anyone.
    """

    seed: random.Random
    name: str = "random"

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        # Everything counts as unknown: a shuffle knows nothing, which is the whole point of it.
        return shuffled(trial, self.seed), 0


def rankings() -> list[Ranking]:
    """The six rankings ADR 0033 fixed, and the list is closed.

    Every one of them was frozen before that ADR was written. The learned model is included
    because the arbitration needs a candidate that actually trades one measure for the other, and
    phase 6 measured that it is the only one which does.
    """
    from benchmarks.study.learned import ColdLearned, LearnedRanking, load_model

    if not MODEL.exists():
        raise FileNotFoundError(
            f"{MODEL} is missing: the six rankings of ADR 0033 include the learned model, and "
            "measuring five of them would be a different study from the one that was registered"
        )
    model = load_model(MODEL)
    return [
        STEP_3_KEPT,  # what testhunch ships
        LatestFailure(),
        Shuffled(random.Random(0)),
        ProductRanking(),  # testhunch 0.2.0
        LearnedRanking(model),
        ColdLearned(model, STEP_3_KEPT),
    ]


def _jobs(build: Build, job_id: int) -> tuple[list[Job], list[tuple[CaseResult, ...]]]:
    """One job per stage of the build, sharing the build's commit and its changed files."""
    jobs: list[Job] = []
    collapsed: list[tuple[CaseResult, ...]] = []
    for offset, stage in enumerate(build.stages):
        jobs.append(
            Job(
                job_id=job_id + offset,
                commits=frozenset({build.head_sha}),
                changed_files=build.changed_files,
                results=stage.results,
            )
        )
        # The class tables are already one row per class: collapsing them would do nothing, and
        # `collapse` is for JUnit reports where a class appears several times.
        collapsed.append(stage.results)
    return jobs, collapsed


def replay(archive: Archive, project: str, rankings_: Sequence[Ranking]) -> dict[str, Any]:
    """Score every ranking on one project, oldest build first.

    Results are read twice, once to rank and once to record, rather than held until the build
    becomes history. A build can stay in flight for hours here, so holding them would grow with
    the concurrency of the project; reading a member of the zip twice costs seconds.
    """
    metas = sorted(archive.metadata(project), key=lambda m: (m.started, m.build_id))
    by_end = sorted(metas, key=lambda m: (m.ended, m.build_id))
    ids = _identifiers(metas)

    engine = Study(rankings_)
    recorded = 0
    for meta in metas:
        # Every build that had finished when this one started, and no other. A build cannot be its
        # own history: the archive holds no build of zero duration, checked over all 34 645 of
        # them, so an end is always strictly after its start.
        while recorded < len(by_end) and by_end[recorded].ended <= meta.started:
            finished = by_end[recorded]
            engine.record(*_jobs(archive.build(finished), ids[finished.key]))
            recorded += 1
        build = archive.build(meta)
        engine.rank(*_jobs(build, ids[meta.key]))

    result = engine.result()
    result["project"] = project
    result["builds"] = {
        "total": len(metas),
        "suite_runs": sum(len(meta.stage_ids) for meta in metas),
        # Builds still running when the last one started are never history. They are scored like
        # any other; nothing that came after them could read them.
        "never_recorded": len(metas) - recorded,
    }
    # What each scored trial belongs to. The inference of ADR 0033 resamples PRs inside a project,
    # because several builds of one pull request and several re-runs of one commit are not
    # independent observations, and a job id alone cannot say which is which.
    owners = {
        ids[meta.key] + offset: meta for meta in metas for offset in range(len(meta.stage_ids))
    }
    result["trials"]["pull_requests"] = [
        owners[job_id].pr_name if job_id in owners else None
        for job_id in result["trials"]["job_ids"]
    ]
    result["trials"]["builds"] = [
        f"{owners[job_id].pr_name}_build{owners[job_id].build_id}" if job_id in owners else None
        for job_id in result["trials"]["job_ids"]
    ]
    return result


def _identifiers(metas: Sequence[BuildMeta]) -> dict[tuple[str, str, str], int]:
    """A stable integer per build, since a job id is an integer and LRTS names builds with strings.

    Numbered by the sweep's own order and spaced by the number of stages, so a stage of one build
    can never collide with a stage of another. The keys are kept in the result so a number can be
    read back as a build.
    """
    identifiers: dict[tuple[str, str, str], int] = {}
    next_id = 0
    for meta in metas:
        identifiers[meta.key] = next_id
        next_id += max(len(meta.stage_ids), 1)
    return identifiers
