"""Replay a project's collected commits through testhunch (docs/adr/0011, 0012)."""

from __future__ import annotations

import tempfile
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from benchmarks.harness.collect import CommitRun, MutantRun, Project
from benchmarks.replay import Job, RankedJob, add_points, replay
from testhunch import __version__
from testhunch.gitinfo import GitError, changed_files, rev_parse
from testhunch.junit import collapse, parse_report
from testhunch.models import CaseResult, ShadowResult, ShadowRun, Status
from testhunch.shadow import BUDGETS, ShadowPoint, evaluate
from testhunch.store import open_store


def commit_jobs(repository: Path, runs: Sequence[CommitRun]) -> Iterator[Job]:
    """The built commits as jobs, in window order, with the files each changed."""
    for index, run in enumerate(runs):
        if run.report is None:
            continue
        try:
            changes = changed_files(f"{run.sha}^1", run.sha, cwd=repository)
            changed: tuple[str, ...] | None = tuple(change.path for change in changes)
        except GitError:  # the first commit of the repository has no parent to compare with
            changed = None
        yield Job(index, frozenset({run.sha}), changed, commit_results(run))


def commit_results(run: CommitRun) -> tuple[CaseResult, ...]:
    """One result per test; with a retry, both runs count as attempts (docs/adr/0008).

    Durations are the first run's: the retry repeats the suite, it does not make its tests slower.
    """
    if run.report is None:
        raise ValueError(f"{run.sha} was not built: it has no results")
    first = collapse(parse_report(run.report.read_bytes()))
    if run.retry is None:
        return first
    durations = {result.key: result.duration_ms for result in first}
    both = collapse([*first, *parse_report(run.retry.read_bytes())])
    return tuple(replace(result, duration_ms=durations.get(result.key)) for result in both)


def mutant_outcome(mutant: MutantRun, commit: ShadowRun) -> str | ShadowRun:
    """Why a mutant cannot be evaluated, or the run to evaluate it with (docs/adr/0012).

    The run has the commit's ranking; its failures are the tests that detected the mutant, those
    that failed on it and passed on every attempt on the commit.
    """
    if not mutant.compiled:
        return "not_compiled"
    if mutant.report is None:
        return "no_report"
    passed_on_commit = {
        result.key
        for result in commit.results
        if result.status is Status.PASSED and not result.flaky
    }
    results = []
    detected = False
    for result in collapse(parse_report(mutant.report.read_bytes())):
        detecting = result.status.is_failure and result.key in passed_on_commit
        detected |= detecting
        status = result.status
        if detecting:
            status = Status.FAILED
        elif status.is_failure:
            status = Status.PASSED  # it ran, but its failure is not the mutant's doing
        results.append(ShadowResult(result.key, status, False, result.duration_ms, 1))
    if not detected:
        return "survived"
    # The commit's ranking, with what it expected each test to cost: the mutant is judged by the
    # budget that ranking would have spent, not by the mutant run's own durations (ADR 0017).
    return ShadowRun(commit.run_id, commit.positions, tuple(results), commit.expected_ms)


def run_project(project: Project, repository: Path, runs: Sequence[CommitRun]) -> dict[str, Any]:
    """Replay one project's collected runs in window order and return the report's numbers."""
    points = evaluate([], BUDGETS)
    mutant_points = evaluate([], BUDGETS)
    mutants: Counter[str] = Counter()
    total = cold = 0
    with tempfile.TemporaryDirectory() as scratch:
        store = open_store(f"sqlite:///{Path(scratch).as_posix()}/history.db")
        store.migrate()
        for ranked in replay(commit_jobs(repository, runs), store, project.name):
            total += 1
            if ranked.cold:
                cold += 1
                mutants["ranked_from_empty_history"] += len(runs[ranked.job.job_id].mutants)
                continue
            points = _add(points, evaluate([ranked.run], BUDGETS))
            mutant_points = _evaluate_mutants(ranked, runs, mutants, mutant_points)
    mutants["tried"] = sum(len(run.mutants) for run in runs)

    return {
        "project": project.name,
        "end": project.end,
        "window": project.window,
        "images": sorted({run.image_id for run in runs}),
        "testhunch": {"version": __version__, "commit": _commit()},
        "commits": {
            "collected": len(runs),
            "built": total,
            "not_built": [run.sha for run in runs if run.report is None],
            "ranked_from_empty_history": cold,
            "evaluated": total - cold,
            "evaluated_failing": points[0].failing_runs,
        },
        "shadow": [asdict(point) for point in points],
        "mutants": {
            key: mutants[key]
            for key in (
                "tried",
                "ranked_from_empty_history",
                "not_compiled",
                "no_report",
                "survived",
                "detected",
            )
        },
        "mutant_shadow": [asdict(point) for point in mutant_points],
    }


def _evaluate_mutants(
    ranked: RankedJob,
    runs: Sequence[CommitRun],
    counts: Counter[str],
    points: list[ShadowPoint],
) -> list[ShadowPoint]:
    for mutant in runs[ranked.job.job_id].mutants:
        outcome = mutant_outcome(mutant, ranked.run)
        if isinstance(outcome, str):
            counts[outcome] += 1
            continue
        counts["detected"] += 1
        points = _add(points, evaluate([outcome], BUDGETS))
    return points


def _add(totals: list[ShadowPoint], more: list[ShadowPoint]) -> list[ShadowPoint]:
    return [add_points(a, b) for a, b in zip(totals, more, strict=True)]


def markdown(result: dict[str, Any]) -> str:
    commits = result["commits"]
    not_built = len(commits["not_built"])
    lines = [
        f"### {result['project']}",
        "",
        f"{commits['collected']} of the {result['window']} commits up to {result['end'][:12]} "
        f"collected; {commits['built']} built and {not_built} not built. "
        f"{commits['evaluated']} evaluated ({commits['ranked_from_empty_history']} ranked from an "
        f"empty history are left out), {commits['evaluated_failing']} of them with failing tests.",
        "",
        "| Budget | Failing commits caught | Failing tests caught | Tests run | Test time run |",
        "|---:|---:|---:|---:|---:|",
        *_rows(result["shadow"]),
    ]
    mutants = result.get("mutants")
    if mutants and mutants["tried"]:
        lines += [
            "",
            f"Mutants (docs/adr/0012): {mutants['tried']} tried, "
            f"{mutants['detected']} detected by a test and evaluated; "
            f"{mutants['survived']} survived, {mutants['not_compiled']} did not compile, "
            f"{mutants['no_report']} wrote no report, and {mutants['ranked_from_empty_history']} "
            "belong to the commit ranked from an empty history.",
            "",
            "| Budget | Mutants caught | Detecting tests run | Tests run | Test time run |",
            "|---:|---:|---:|---:|---:|",
            *_rows(result["mutant_shadow"]),
        ]
    return "\n".join(lines) + "\n"


def _rows(points: list[dict[str, Any]]) -> list[str]:
    rows = []
    for point in points:
        time = (
            f"{100 * point['time_run_ms'] / point['time_total_ms']:.0f}%"
            if point["time_total_ms"]
            else "0 ms measured"
        )
        rows.append(
            f"| {point['fraction']:.0%} | {point['caught_runs']} of {point['failing_runs']} | "
            f"{point['caught_failures']} of {point['failures']} | "
            f"{point['tests_run']} of {point['tests_total']} | {time} |"
        )
    return rows


def _commit() -> str | None:
    try:
        return rev_parse("HEAD")
    except GitError:
        return None
