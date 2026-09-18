"""A measured failure rate in place of RTPTorrent's priority (docs/adr/0037).

    uv run python -m benchmarks.calibration training     # reported
    uv run python -m benchmarks.calibration validation   # judged
    uv run python -m benchmarks.calibration training --step streaks   # explored after it

The candidates are `Calibrated` in `benchmarks.study.rankings`. Neither uses the changed-file
signal, so each is read twice: against what testhunch ships, which decides, and against the same
ranking without that signal, `latest-failure+time^1.0`, which isolates what the calibration does.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from benchmarks.costorder import (
    BEFORE,
    EVERY,
    FIRST,
    RANDOM,
    RELEASE_020,
    SHIPPED,
    Slice,
    caught,
    difference,
    mean,
)
from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_TRAINING, RTPTORRENT_VALIDATION
from benchmarks.study.engine import PRIMARY, study
from benchmarks.study.projects import CACHE, STEP_1_KEPT, STEP_3_KEPT
from benchmarks.study.rankings import Calibrated, LatestFailure, ProductRanking, Ranking, Shuffled
from testhunch import __version__

HALVES = {"training": RTPTORRENT_TRAINING, "validation": RTPTORRENT_VALIDATION}
RESULTS = Path("benchmarks/results/study/calibration")
MATCHED = STEP_1_KEPT.name
CALIBRATED = "calibrated"
BY_RUNS = "calibrated+runs"
CANDIDATES = (CALIBRATED, BY_RUNS)
STREAKS = "calibrated+runs+streaks"
# Each step: where its results go, and the candidates it replays. `adr-0037` is the step that
# record judged; `streaks` came after it, from `benchmarks/repeats.py`, on the training half.
STEPS: dict[str, tuple[Path, tuple[Calibrated, ...]]] = {
    "adr-0037": (RESULTS, (Calibrated(CALIBRATED), Calibrated(BY_RUNS, by_runs=True))),
    "streaks": (
        Path("benchmarks/results/study/calibration-streaks"),
        (Calibrated(BY_RUNS, by_runs=True), Calibrated(STREAKS, by_runs=True, streaks=True)),
    ),
}

# The decision rule of docs/adr/0037, written before either candidate was replayed.
PRIMARY_LOSS = 0.003  # as in docs/adr/0036
TIME_SHARE = 0.5  # of the gap between the shipped ranking and random, in red at, first failures
HARM = 0.005  # ADR 0014's smallest difference


def rankings(step: str = "adr-0037") -> list[Ranking]:
    return [
        STEP_3_KEPT,
        *STEPS[step][1],
        STEP_1_KEPT,
        LatestFailure(),
        ProductRanking(),
        Shuffled(random.Random(0)),
    ]


def run(project: str, step: str = "adr-0037") -> dict[str, Any]:
    directory = fetch_project(project, CACHE / "rtptorrent")
    return {"project": project, **study(iter_jobs(directory), rankings(step))}


def candidates(results: Sequence[Mapping[str, Any]]) -> list[str]:
    """The calibrated rankings the results hold, in their order."""
    return [name for name in results[0]["rankings"] if name.startswith(CALIBRATED)]


def criteria(results: Sequence[Mapping[str, Any]], ranking: str) -> dict[str, Any]:
    """The four conditions of docs/adr/0037 against the shipped ranking, on the same jobs."""

    def change(measure: str, chosen: Slice) -> float:
        return mean(results, ranking, measure, chosen) - mean(results, SHIPPED, measure, chosen)

    gap = mean(results, SHIPPED, "red_at", FIRST) - mean(results, RANDOM, "red_at", FIRST)
    found = {
        "primary": change(PRIMARY, EVERY),
        "red_at": change("red_at", FIRST),
        "gap": gap,
        "position": change("position", FIRST),
        "repeat": change(PRIMARY, BEFORE),
    }
    found["affordable"] = -found["primary"] <= PRIMARY_LOSS
    found["sooner"] = -found["red_at"] >= TIME_SHARE * gap
    found["not_later"] = found["position"] < HARM
    found["harmless"] = -found["repeat"] < HARM
    found["passes"] = all(found[k] for k in ("affordable", "sooner", "not_later", "harmless"))
    return found


def verdict(results: Sequence[Mapping[str, Any]]) -> str | None:
    passing = [name for name in candidates(results) if criteria(results, name)["passes"]]
    return max(passing, key=lambda name: mean(results, name, PRIMARY, EVERY)) if passing else None


def _f(value: float, signed: bool = False) -> str:
    if math.isnan(value):
        return "-"
    return f"{value:+.3f}" if signed else f"{value:.3f}"


def _interval(found: tuple[float, float, float]) -> str:
    value, low, high = found
    return f"{_f(value, True)} [{_f(low, True)}, {_f(high, True)}]"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def section(half: str, results: Sequence[Mapping[str, Any]]) -> list[str]:
    names = list(results[0]["rankings"])
    chosen = candidates(results)
    lines = [
        f"## {half.capitalize()} half: " + ", ".join(r["project"] for r in results),
        "",
        "Mean of the per-project means, on the same failing jobs; 95% intervals resample "
        "projects, then jobs inside them. Primary and share caught: higher is better. Position "
        "and red at: lower is better.",
        "",
        "| Ranking | primary | against shipped | against the same without the file signal | "
        "had failed: APFDc | had failed: position |",
        "|---|---:|---|---|---:|---:|",
    ]
    for name in names:
        against = (
            "" if name == SHIPPED else _interval(difference(results, name, SHIPPED, PRIMARY, EVERY))
        )
        matched = (
            _interval(difference(results, name, MATCHED, PRIMARY, EVERY)) if name in chosen else ""
        )
        lines.append(
            f"| {name} | {_f(mean(results, name, PRIMARY, EVERY))} | {against} | {matched} | "
            f"{_f(mean(results, name, PRIMARY, BEFORE))} | "
            f"{_f(mean(results, name, 'position', BEFORE))} |"
        )
    lines += [
        "",
        "Jobs whose failing test had never failed before:",
        "",
        "| Ranking | position | against random | red at | against shipped | caught within 25% "
        "of the time | caught within 50% |",
        "|---|---:|---|---:|---|---:|---:|",
    ]
    for name in names:
        against = (
            ""
            if name == SHIPPED
            else _interval(difference(results, name, SHIPPED, "red_at", FIRST))
        )
        vs_random = (
            ""
            if name == RANDOM
            else _interval(difference(results, name, RANDOM, "position", FIRST))
        )
        lines.append(
            f"| {name} | {_f(mean(results, name, 'position', FIRST))} | {vs_random} | "
            f"{_f(mean(results, name, 'red_at', FIRST))} | {against} | "
            f"{_f(caught(results, name, 0.25, FIRST))} | {_f(caught(results, name, 0.5, FIRST))} |"
        )
    lines += [
        "",
        f"Decision rule of docs/adr/0037, against the shipped ranking: lose at most {PRIMARY_LOSS} "
        f"of primary; on first failures, turn red sooner by at least {TIME_SHARE:.0%} of the gap "
        f"between the shipped ranking and random, and do not place the failing test later by "
        f"{HARM} or more; on the jobs that had failed before, do not lose {HARM} of APFDc or more.",
        "",
        "| Candidate | primary | red at, first failures (gap to random) | position, first "
        "failures | had failed: APFDc | meets all four |",
        "|---|---|---|---|---|---|",
    ]
    for name in chosen:
        found = criteria(results, name)
        lines.append(
            f"| {name} | {_f(found['primary'], True)} {_yes(found['affordable'])} | "
            f"{_f(found['red_at'], True)} ({_f(found['gap'])}) {_yes(found['sooner'])} | "
            f"{_f(found['position'], True)} {_yes(found['not_later'])} | "
            f"{_f(found['repeat'], True)} {_yes(found['harmless'])} | {_yes(found['passes'])} |"
        )
    lines += [
        "",
        "Project by project, each candidate minus the shipped ranking: a mean over a half can be "
        "carried by one project.",
        "",
        "| Project | first-failure jobs | "
        + " | ".join(
            f"{n}: primary | {n}: had failed, APFDc | {n}: red at, first failures" for n in chosen
        )
        + " |",
        "|---|---:|" + "---:|" * (3 * len(chosen)),
    ]
    for result in results:
        cells = []
        for name in chosen:
            for measure, part in ((PRIMARY, EVERY), (PRIMARY, BEFORE), ("red_at", FIRST)):
                cells.append(
                    _f(
                        mean([result], name, measure, part)
                        - mean([result], SHIPPED, measure, part),
                        True,
                    )
                )
        jobs = sum(1 for flag in result["trials"]["first_failure"] if flag is True)
        lines.append(f"| {result['project']} | {jobs} | " + " | ".join(cells) + " |")
    better = {
        name: [
            sum(
                1
                for r in results
                if mean([r], name, measure, part) > mean([r], SHIPPED, measure, part)
            )
            for measure, part in ((PRIMARY, EVERY), (PRIMARY, BEFORE))
        ]
        for name in chosen
    }
    sooner = {
        name: sum(
            1
            for r in results
            if mean([r], name, "red_at", FIRST) < mean([r], SHIPPED, "red_at", FIRST)
        )
        for name in chosen
    }
    lines += [
        "",
        "Projects where the candidate does better than the shipped ranking, of "
        f"{len(results)}: "
        + "; ".join(
            f"{name}, primary {better[name][0]}, had failed {better[name][1]}, first failures "
            f"sooner {sooner[name]}"
            for name in chosen
        )
        + ".",
    ]
    if half == "validation":
        winner = verdict(results)
        lines += [
            "",
            f"**Recommendation: NEEDS_HELD_OUT_CONFIRMATION, for {winner}.** Development data "
            "cannot ship a ranking in this project (docs/adr/0013, docs/adr/0033)."
            if winner
            else "**Recommendation: DO_NOT_SHIP.** No candidate meets the four conditions on the "
            "validation half.",
        ]
    return lines


def page(halves: Mapping[str, Sequence[Mapping[str, Any]]], step: str = "adr-0037") -> str:
    title = (
        "# A measured failure rate in place of the priority"
        if step == "adr-0037"
        else f"# A measured failure rate in place of the priority: step `{step}`"
    )
    lines = [
        title,
        "",
        "Generated by `python -m benchmarks.calibration"
        + ("" if step == "adr-0037" else f" --step {step}")
        + "`; protocol in docs/adr/0037"
        + (" and after it, exploration on the training half" if step != "adr-0037" else "")
        + ". Development "
        f"projects only. `{SHIPPED}` is what testhunch ships; `{MATCHED}` is the same without the "
        f"changed-file signal, which neither candidate uses; `{RELEASE_020}` and `{RANDOM}` are "
        "read alongside. LRTS and the held-out projects are not touched.",
    ]
    for half, results in halves.items():
        lines += ["", *section(half, results)]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.calibration")
    parser.add_argument("half", choices=sorted(HALVES))
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument("--step", choices=sorted(STEPS), default="adr-0037")
    args = parser.parse_args(argv)
    results_dir = STEPS[args.step][0]
    out = results_dir / args.half
    if not args.from_cache:
        out.mkdir(parents=True, exist_ok=True)
        projects = HALVES[args.half]
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for result in pool.map(run, projects, [args.step] * len(projects)):
                result["testhunch"] = {"version": __version__}
                slug = result["project"].replace("/", "@")
                (out / f"{slug}.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
                sys.stdout.write(f"{result['project']}: {result['counts']}\n")
    halves = {}
    for half in HALVES:
        stored = sorted((results_dir / half).glob("*.json"))
        if stored:
            halves[half] = [json.loads(p.read_text(encoding="utf-8")) for p in stored]
    (results_dir / "README.md").write_bytes(page(halves, args.step).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
