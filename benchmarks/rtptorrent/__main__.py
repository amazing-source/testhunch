"""Run the RTPTorrent benchmark on projects (docs/adr/0010).

uv run python -m benchmarks.rtptorrent dynjs@dynjs brettwooldridge@HikariCP
uv run python -m benchmarks.rtptorrent              # every development project (docs/adr/0013)
uv run python -m benchmarks.rtptorrent --held-out   # every held-out project, frozen versions only
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

from benchmarks.heldout import NotFrozen, record_peek
from benchmarks.replay import add_points, apfd, failing_tests, replay
from benchmarks.rtptorrent.data import STRATEGIES, fetch_project, iter_jobs
from benchmarks.rtptorrent.schedules import read_schedules
from benchmarks.rtptorrent.summary import summary
from benchmarks.split import RTPTORRENT_DEVELOPMENT, RTPTORRENT_HELD_OUT
from testhunch import __version__
from testhunch.gitinfo import GitError, rev_parse
from testhunch.shadow import BUDGETS, evaluate
from testhunch.store import open_store

DEFAULT_CACHE = Path(".benchmark-cache") / "rtptorrent"
DEFAULT_OUT = Path("benchmarks") / "results" / "rtptorrent"


def run_project(directory: Path) -> dict[str, Any]:
    """Replay one fetched project and return every number the report shows.

    Jobs are scored as they are replayed and then dropped, so memory does not grow with the project.
    """
    project = directory.name
    schedule_scores: dict[str, dict[int, float | None]] = {}
    for strategy in STRATEGIES:
        path = directory / "baseline" / f"{strategy}.csv"
        if path.exists():
            schedule = read_schedules(path)
            schedule_scores[strategy] = {job: apfd(*ordered) for job, ordered in schedule.items()}
    # Without any schedule there is nothing to compare with.
    covered = set.intersection(*map(set, schedule_scores.values())) if schedule_scores else set()

    points = evaluate([], BUDGETS)
    testhunch_scores: dict[int, float] = {}
    total = groups = cold = without_commit = 0
    with tempfile.TemporaryDirectory() as scratch:
        store = open_store(f"sqlite:///{Path(scratch).as_posix()}/history.db")
        store.migrate()
        for ranked in replay(iter_jobs(directory), store, project):
            total, groups = total + 1, ranked.group + 1
            without_commit += ranked.job.changed_files is None
            if ranked.cold:
                cold += 1
                continue
            run_points = evaluate([ranked.run], BUDGETS)
            points = [add_points(a, b) for a, b in zip(points, run_points, strict=True)]
            if ranked.job.job_id in covered:
                score = apfd(ranked.order, failing_tests(ranked.run.results))
                if score is not None:
                    testhunch_scores[ranked.job.job_id] = score

    apfd_scores: dict[str, list[float]] = {"testhunch": []}
    for job_id, score in sorted(testhunch_scores.items()):
        apfd_scores["testhunch"].append(score)
        for strategy, scores in schedule_scores.items():
            strategy_score = scores[job_id]
            if strategy_score is not None:
                apfd_scores.setdefault(strategy, []).append(strategy_score)

    source = directory / "source.json"  # written by fetch_project; absent from the test extract
    return {
        "project": project,
        "dataset": json.loads(source.read_text(encoding="utf-8")) if source.exists() else None,
        "testhunch": {"version": __version__, "commit": _commit()},
        "jobs": {
            "total": total,
            "concurrent_groups": groups,
            "ranked_from_empty_history": cold,
            "without_commit": without_commit,
            "evaluated": total - cold,
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
    if not apfd_result["jobs"]:
        lines += ["", "The dataset has no schedule by its authors to compare APFD with."]
        return "\n".join(lines) + "\n"
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
    parser.add_argument(
        "projects", nargs="*", help="e.g. dynjs@dynjs; default: every development project"
    )
    parser.add_argument(
        "--held-out",
        action="store_true",
        help="allow held-out projects, by default all of them: only for versions frozen before "
        "the replay (docs/adr/0013)",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    projects = args.projects or (RTPTORRENT_HELD_OUT if args.held_out else RTPTORRENT_DEVELOPMENT)
    held_out = [project for project in projects if project in RTPTORRENT_HELD_OUT]
    if held_out and not args.held_out:
        parser.error(
            f"held out, measured only with --held-out (docs/adr/0013): {', '.join(held_out)}"
        )
    if held_out:
        # Written before the replay, from a frozen commit, so the look cannot be hidden (ADR 0016).
        try:
            record_peek("benchmarks.rtptorrent", held_out, "the product's ranking", __version__)
        except NotFrozen as exc:
            parser.error(str(exc))
    args.out.mkdir(parents=True, exist_ok=True)
    for project in projects:
        result = run_project(fetch_project(project, args.cache))
        (args.out / f"{project}.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        (args.out / f"{project}.md").write_text(markdown(result), encoding="utf-8")
        sys.stdout.write(markdown(result) + "\n")
    # Every project measured so far in this directory, not only the ones of this call.
    everything = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.out.glob("*.json"))
    ]
    (args.out / "README.md").write_text(summary(everything), encoding="utf-8")
    return 0


def _commit() -> str | None:
    try:
        return rev_parse("HEAD")
    except GitError:
        return None


if __name__ == "__main__":
    sys.exit(main())
