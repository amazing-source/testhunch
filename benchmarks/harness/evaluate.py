"""Replay a project's collected commits through testhunch (docs/adr/0011)."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from benchmarks.harness.collect import CommitRun, Project
from benchmarks.replay import HISTORY_RUNS, Job, add_points, replay
from testhunch import __version__
from testhunch.gitinfo import GitError, changed_files, rev_parse
from testhunch.junit import collapse, parse_report
from testhunch.models import CaseResult
from testhunch.shadow import BUDGETS, evaluate
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
    assert run.report is not None
    first = collapse(parse_report(run.report.read_bytes()))
    if run.retry is None:
        return first
    durations = {result.key: result.duration_ms for result in first}
    both = collapse([*first, *parse_report(run.retry.read_bytes())])
    return tuple(replace(result, duration_ms=durations.get(result.key)) for result in both)


def run_project(project: Project, repository: Path, runs: Sequence[CommitRun]) -> dict[str, Any]:
    """Replay one project's collected runs in window order and return the report's numbers."""
    points = evaluate([], BUDGETS)
    total = cold = 0
    with tempfile.TemporaryDirectory() as scratch:
        store = open_store(f"sqlite:///{Path(scratch).as_posix()}/history.db")
        store.migrate()
        for ranked in replay(commit_jobs(repository, runs), store, project.name):
            total += 1
            if ranked.cold:
                cold += 1
                continue
            run_points = evaluate([ranked.run], BUDGETS)
            points = [add_points(a, b) for a, b in zip(points, run_points, strict=True)]

    return {
        "project": project.name,
        "end": project.end,
        "window": project.window,
        "images": sorted({run.image_id for run in runs}),
        "testhunch": {"version": __version__, "commit": _commit()},
        "history_runs": HISTORY_RUNS,
        "commits": {
            "collected": len(runs),
            "built": total,
            "not_built": [run.sha for run in runs if run.report is None],
            "ranked_from_empty_history": cold,
            "evaluated": total - cold,
            "evaluated_failing": points[0].failing_runs,
        },
        "shadow": [asdict(point) for point in points],
    }


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
    ]
    for point in result["shadow"]:
        time = (
            f"{100 * point['time_run_ms'] / point['time_total_ms']:.0f}%"
            if point["time_total_ms"]
            else "0 ms measured"
        )
        lines.append(
            f"| {point['fraction']:.0%} | {point['caught_runs']} of {point['failing_runs']} | "
            f"{point['caught_failures']} of {point['failures']} | "
            f"{point['tests_run']} of {point['tests_total']} | {time} |"
        )
    return "\n".join(lines) + "\n"


def _commit() -> str | None:
    try:
        return rev_parse("HEAD")
    except GitError:
        return None
