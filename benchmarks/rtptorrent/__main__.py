"""Run the RTPTorrent benchmark on projects (docs/adr/0010).

uv run python -m benchmarks.rtptorrent adamfisk@LittleProxy brettwooldridge@HikariCP
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from benchmarks.rtptorrent.data import STRATEGIES, fetch_project, load_jobs
from benchmarks.rtptorrent.replay import (
    HISTORY_RUNS,
    apfd,
    concurrent_groups,
    failing_classes,
    read_schedules,
    replay,
)
from testhunch import __version__
from testhunch.gitinfo import GitError, rev_parse
from testhunch.shadow import BUDGETS, evaluate
from testhunch.store import open_store

DEFAULT_CACHE = Path(".benchmark-cache") / "rtptorrent"
DEFAULT_OUT = Path("benchmarks") / "results" / "rtptorrent"


def run_project(directory: Path) -> dict[str, Any]:
    """Replay one fetched project and return every number the report shows."""
    project = directory.name
    jobs = load_jobs(directory)
    with tempfile.TemporaryDirectory() as scratch:
        store = open_store(f"sqlite:///{Path(scratch).as_posix()}/history.db")
        store.migrate()
        ranked = replay(jobs, store, project)

    warm = [r for r in ranked if not r.cold]
    points = evaluate([r.run for r in warm], BUDGETS)

    schedules = {
        strategy: read_schedules(directory / "baseline" / f"{strategy}.csv")
        for strategy in STRATEGIES
        if (directory / "baseline" / f"{strategy}.csv").exists()
    }
    by_id = {r.job.job_id: r for r in warm}
    compared = sorted(set(by_id).intersection(*(set(s) for s in schedules.values())))
    apfd_scores: dict[str, list[float]] = {"testhunch": []}
    for job_id in compared:
        ranked_job = by_id[job_id]
        failing = failing_classes(ranked_job.run.results)
        score = apfd(ranked_job.order, failing)
        if score is None:
            continue
        apfd_scores["testhunch"].append(score)
        for strategy, schedule in schedules.items():
            order, schedule_failing = schedule[job_id]
            strategy_score = apfd(order, schedule_failing)
            if strategy_score is not None:
                apfd_scores.setdefault(strategy, []).append(strategy_score)

    source = directory / "source.json"  # written by fetch_project; absent from the test extract
    return {
        "project": project,
        "dataset": json.loads(source.read_text(encoding="utf-8")) if source.exists() else None,
        "testhunch": {"version": __version__, "commit": _commit()},
        "history_runs": HISTORY_RUNS,
        "jobs": {
            "total": len(jobs),
            "concurrent_groups": len(concurrent_groups(jobs)),
            "ranked_from_empty_history": len(ranked) - len(warm),
            "without_commit": sum(1 for job in jobs if job.changed_files is None),
            "evaluated": len(warm),
            "evaluated_failing": points[0].failing_runs if points else 0,
        },
        "shadow": [asdict(point) for point in points],
        "apfd": {
            "jobs": len(apfd_scores["testhunch"]),
            "mean": {name: statistics.fmean(s) for name, s in apfd_scores.items() if s},
        },
    }


def markdown(result: dict[str, Any]) -> str:
    jobs = result["jobs"]
    lines = [
        f"### {result['project']}",
        "",
        f"{jobs['total']} jobs; {jobs['evaluated']} evaluated ({jobs['ranked_from_empty_history']} "
        f"ranked from an empty history are left out), {jobs['evaluated_failing']} of them failing; "
        f"{jobs['without_commit']} jobs have no known changed files.",
        "",
        "| Budget | Failing jobs caught | Failing classes caught | Classes run | Test time run |",
        "|---:|---:|---:|---:|---:|",
    ]
    for point in result["shadow"]:
        time = (
            f"{100 * point['time_run_ms'] / point['time_total_ms']:.0f}%"
            if point["time_total_ms"]
            else "unknown"
        )
        lines.append(
            f"| {point['fraction']:.0%} | {point['caught_runs']} of {point['failing_runs']} | "
            f"{point['caught_failures']} of {point['failures']} | "
            f"{point['tests_run']} of {point['tests_total']} | {time} |"
        )
    apfd_result = result["apfd"]
    lines += [
        "",
        f"Mean APFD on the {apfd_result['jobs']} jobs the authors' schedules cover:",
        "",
        "| Schedule | Mean APFD |",
        "|---|---:|",
    ]
    for name, mean in sorted(apfd_result["mean"].items(), key=lambda item: -item[1]):
        lines.append(f"| {name} | {mean:.3f} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.rtptorrent")
    parser.add_argument("projects", nargs="+", help="e.g. adamfisk@LittleProxy")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for project in args.projects:
        result = run_project(fetch_project(project, args.cache))
        (args.out / f"{project}.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        (args.out / f"{project}.md").write_text(markdown(result), encoding="utf-8")
        sys.stdout.write(markdown(result) + "\n")
    return 0


def _commit() -> str | None:
    try:
        return rev_parse("HEAD")
    except GitError:
        return None


if __name__ == "__main__":
    sys.exit(main())
