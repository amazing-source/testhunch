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
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from benchmarks.heldout import NotFrozen, record_peek
from benchmarks.replay import add_points, replay
from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_DEVELOPMENT, RTPTORRENT_HELD_OUT
from testhunch import __version__
from testhunch.models import ShadowRun, Status
from testhunch.shadow import BUDGETS, PACKINGS, PREFIX, ShadowPoint, evaluate, selected_ranks
from testhunch.store import open_store

DEFAULT_CACHE = Path(".benchmark-cache") / "rtptorrent"
DEFAULT_OUT = Path("benchmarks") / "results" / "study" / "budget-packing"


MONOTONICITY_KEYS = ("pairs", "dropped_a_test", "ran_fewer_failures", "lost_the_build")


def _failures_run(run: ShadowRun, ranks: set[int]) -> int:
    """How many of this run's real failures a budget runs. An unknown test always runs."""
    return sum(
        1
        for result in run.results
        if result.status is not Status.SKIPPED
        and result.status.is_failure
        and not result.flaky
        and (run.positions.get(result.key) is None or run.positions[result.key] in ranks)
    )


def _count_monotonicity(run: ShadowRun, packing: str, counts: Counter[str]) -> None:
    """Whether a wider budget takes back what a narrower one ran, over adjacent budget pairs.

    Filling greedily in rank order is first-fit, which is not monotone in the capacity: a test that
    did not fit in the narrow budget can fit in the wide one, take the room, and push out cheaper
    tests below it. Counted per job because the totals of a project hide it (docs/adr/0029).
    """
    selections = [selected_ranks(run, fraction, packing) for fraction in BUDGETS]
    if any(ranks is None for ranks in selections):
        return  # no budget can be cut for this run at all
    caught = [_failures_run(run, ranks) for ranks in selections if ranks is not None]
    for index, (small, large) in enumerate(itertools.pairwise(selections)):
        assert small is not None and large is not None
        counts["pairs"] += 1
        counts["dropped_a_test"] += not small <= large
        counts["ran_fewer_failures"] += caught[index + 1] < caught[index]
        counts["lost_the_build"] += caught[index] > 0 and caught[index + 1] == 0


def run_project(directory: Path) -> dict[str, Any]:
    """Replay one project once, and score every job under each packing rule."""
    project = directory.name
    points: dict[str, list[ShadowPoint]] = {
        packing: evaluate([], BUDGETS, packing) for packing in PACKINGS
    }
    monotonicity: dict[str, Counter[str]] = {packing: Counter() for packing in PACKINGS}
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
                _count_monotonicity(ranked.run, packing, monotonicity[packing])
    return {
        "project": project,
        "evaluated": evaluated,
        "packing": {
            packing: [asdict(point) for point in totals] for packing, totals in points.items()
        },
        "monotonicity": {
            packing: {key: counts[key] for key in MONOTONICITY_KEYS}
            for packing, counts in monotonicity.items()
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
    lines += _monotonicity_section(results)
    lines.append("")
    return "\n".join(lines)


def _monotonicity_section(results: Sequence[dict[str, Any]]) -> list[str]:
    """What a wider budget takes back, counted per job rather than per project."""
    measured = [result for result in results if "monotonicity" in result]
    if not measured:
        return []  # rebuilt from runs older than this measurement
    totals = {
        packing: {
            key: sum(result["monotonicity"][packing][key] for result in measured)
            for key in MONOTONICITY_KEYS
        }
        for packing in PACKINGS
    }
    lines = [
        "",
        "## What a wider budget takes back",
        "",
        "Filling greedily in rank order is first-fit, and first-fit is not monotone in the",
        "capacity: a test that did not fit in the narrow budget can fit in the wide one, take the",
        "room, and push out cheaper tests below it. A prefix cannot do this, since a longer prefix",
        "contains the shorter one. Counted over adjacent budget pairs of each job, because a",
        "project's totals hide it.",
        "",
        f"{len(measured)} projects, "
        f"{totals[PREFIX]['pairs']} budget pairs with a selection at both budgets.",
        "",
        "| Rule | The wider budget drops a test | It runs fewer failures "
        "| The build stops being red |",
        "|---|---:|---:|---:|",
    ]
    for packing in PACKINGS:
        row = totals[packing]
        pairs = row["pairs"]
        share = f"{row['dropped_a_test'] / pairs:.1%}" if pairs else "n/a"
        lines.append(
            f"| {packing} | {row['dropped_a_test']} ({share}) | {row['ran_fewer_failures']} | "
            f"{row['lost_the_build']} |"
        )
    return lines


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
