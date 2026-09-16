"""What a time budget should do with a test that does not fit (docs/adr/0029).

    uv run python -m benchmarks.budgetpacking            # the development projects
    uv run python -m benchmarks.budgetpacking --held-out # frozen versions only, writes a ledger row

The three rules of `testhunch.shadow.budget_ranks`, replayed side by side on the same rankings, so
the only thing that differs between the columns is what happens at the first test too expensive to
fit. Nothing else about the ranking changes.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from benchmarks.heldout import NotFrozen, record_peek
from benchmarks.replay import add_points, replay
from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_DEVELOPMENT, RTPTORRENT_HELD_OUT
from testhunch import __version__
from testhunch.shadow import BUDGETS, PACKINGS, PREFIX, ShadowPoint, evaluate
from testhunch.store import open_store

DEFAULT_CACHE = Path(".benchmark-cache") / "rtptorrent"
DEFAULT_OUT = Path("benchmarks") / "results" / "study" / "budget-packing"


def run_project(directory: Path) -> dict[str, Any]:
    """Replay one project once, and score every job under each packing rule."""
    project = directory.name
    points: dict[str, list[ShadowPoint]] = {
        packing: evaluate([], BUDGETS, packing) for packing in PACKINGS
    }
    evaluated = 0
    with tempfile.TemporaryDirectory() as scratch:
        store = open_store(f"sqlite:///{Path(scratch).as_posix()}/history.db")
        store.migrate()
        for ranked in replay(iter_jobs(directory), store, project):
            if ranked.cold:
                continue  # ranked from an empty history: no budget means anything yet
            evaluated += 1
            for packing in PACKINGS:
                scored = evaluate([ranked.run], BUDGETS, packing)
                points[packing] = [
                    add_points(total, one)
                    for total, one in zip(points[packing], scored, strict=True)
                ]
    return {
        "project": project,
        "evaluated": evaluated,
        "packing": {
            packing: [asdict(point) for point in totals] for packing, totals in points.items()
        },
    }


def rate(point: dict[str, Any], numerator: str, denominator: str) -> float | None:
    total = point[denominator]
    return point[numerator] / total if total else None


def markdown(results: Sequence[dict[str, Any]]) -> str:
    # The budgets come from the results rather than from BUDGETS: a page rebuilt from older runs
    # must describe what those runs measured, not what this version would measure.
    fractions = [point["fraction"] for point in results[0]["packing"][PREFIX]] if results else []
    totals = {
        packing: [
            {
                key: sum(result["packing"][packing][index][key] for result in results)
                for key in results[0]["packing"][packing][index]
                if key != "fraction"
            }
            for index in range(len(fractions))
        ]
        for packing in PACKINGS
    }
    lines = [
        "# What a budget does with a test that does not fit",
        "",
        "Three rules, replayed side by side on the **same** rankings: only what happens at the",
        "first test too expensive to fit differs between the columns.",
        "",
        "- **prefix**: stop there. The order is what the ranking promises, and nothing below a",
        "  left-out test ever runs.",
        "- **oversized**: pass over a test that could not have fitted in the whole budget however",
        "  early it came, and stop at any other test that does not fit.",
        "- **fill**: keep going past everything that does not fit, to the end of the ranking.",
        "",
        f"{len(results)} projects, "
        f"{sum(result['evaluated'] for result in results)} jobs with a usable ranking.",
        "",
        "Failing jobs that stay red, and the share of test time spent, per budget:",
        "",
        "| Budget | Rule | Failing jobs caught | Failing tests run | Test time spent |",
        "|---|---|---:|---:|---:|",
    ]
    for index, fraction in enumerate(fractions):
        for packing in PACKINGS:
            point = totals[packing][index]
            caught = rate(point, "caught_runs", "failing_runs")
            tests = rate(point, "caught_failures", "failures")
            time = rate(point, "time_run_ms", "time_total_ms")
            lines.append(
                f"| {fraction:.0%} | {packing} | {_pct(caught)} | {_pct(tests)} | {_pct(time)} |"
            )
    lines += [
        "",
        "A rule that catches more failing jobs while spending more time has not necessarily won:",
        "the budget is what a user asked to spend, and a rule that spends more of it is not",
        "cheating, it is doing what was asked. So the comparison that decides is at equal time.",
        "",
        "## At equal time",
        "",
        "`prefix` measured at three budgets gives a curve of failing jobs caught against test time",
        "spent. Each other rule is placed on that curve at **its own** time cost, by linear",
        "interpolation, and the column is what it catches beyond a prefix that spends the same.",
        "",
        "| Budget | Rule | Test time spent | Caught | `prefix` at that time | Difference |",
        "|---|---|---:|---:|---:|---:|",
    ]
    curve = sorted(
        (rate(point, "time_run_ms", "time_total_ms"), rate(point, "caught_runs", "failing_runs"))
        for point in totals[PREFIX]
    )
    for index, fraction in enumerate(fractions):
        for packing in PACKINGS:
            if packing == PREFIX:
                continue
            point = totals[packing][index]
            time = rate(point, "time_run_ms", "time_total_ms")
            caught = rate(point, "caught_runs", "failing_runs")
            same = _on_curve(curve, time)
            difference = (
                f"{(caught - same) * 100:+.1f} pt"
                if caught is not None and same is not None
                else "-"
            )
            lines.append(
                f"| {fraction:.0%} | {packing} | {_pct(time)} | {_pct(caught)} "
                f"| {_pct(same)} | {difference} |"
            )
    lines.append("")
    return "\n".join(lines)


def _on_curve(
    curve: Sequence[tuple[float | None, float | None]], time: float | None
) -> float | None:
    """What `prefix` catches for that share of test time, interpolated between its budgets.

    Outside the measured range the nearest segment's slope is continued, which is an
    extrapolation and is only ever a point or two beyond the last budget measured.
    """
    points = [(t, c) for t, c in curve if t is not None and c is not None]
    if time is None or len(points) < 2:
        return None
    lower, upper = points[0], points[1]
    for first, second in itertools.pairwise(points):
        if first[0] <= time <= second[0]:
            lower, upper = first, second
            break
        if time > second[0]:
            lower, upper = first, second
    if upper[0] == lower[0]:
        return lower[1]
    slope = (upper[1] - lower[1]) / (upper[0] - lower[0])
    return lower[1] + slope * (time - lower[0])


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.budgetpacking")
    parser.add_argument("projects", nargs="*")
    parser.add_argument("--held-out", action="store_true")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="leave alone the projects already measured under --out. A replay of the big projects "
        "takes tens of minutes, and losing it to an interruption is the only reason to restart",
    )
    args = parser.parse_args(argv)

    projects = args.projects or (RTPTORRENT_HELD_OUT if args.held_out else RTPTORRENT_DEVELOPMENT)
    held_out = [project for project in projects if project in RTPTORRENT_HELD_OUT]
    if held_out and not args.held_out:
        parser.error(f"held out, measured only with --held-out: {', '.join(held_out)}")
    if held_out and not args.from_cache:
        try:
            record_peek("benchmarks.budgetpacking", held_out, ", ".join(PACKINGS), __version__)
        except NotFrozen as exc:
            parser.error(str(exc))

    args.out.mkdir(parents=True, exist_ok=True)
    for project in projects:
        stored = args.out / f"{project}.json"
        if args.from_cache:
            if not stored.exists():
                parser.error(f"no stored result at {stored}")
        elif stored.exists() and args.resume:
            print(f"{project}: already measured", flush=True)
        else:
            result = run_project(fetch_project(project, args.cache))
            stored.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"{project}: {result['evaluated']} jobs", flush=True)

    everything = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.out.glob("*.json"))
    ]
    (args.out / "README.md").write_bytes(markdown(everything).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
