"""A measured failure rate in place of RTPTorrent's priority (docs/adr/0037).

    uv run python -m benchmarks.calibration training     # reported
    uv run python -m benchmarks.calibration validation   # judged

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

# The decision rule of docs/adr/0037, written before either candidate was replayed.
PRIMARY_LOSS = 0.003  # as in docs/adr/0036
TIME_SHARE = 0.5  # of the gap between the shipped ranking and random, in red at, first failures
HARM = 0.005  # ADR 0014's smallest difference


def rankings() -> list[Ranking]:
    return [
        STEP_3_KEPT,
        Calibrated(CALIBRATED),
        Calibrated(BY_RUNS, by_runs=True),
        STEP_1_KEPT,
        LatestFailure(),
        ProductRanking(),
        Shuffled(random.Random(0)),
    ]


def run(project: str) -> dict[str, Any]:
    directory = fetch_project(project, CACHE / "rtptorrent")
    return {"project": project, **study(iter_jobs(directory), rankings())}


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
    passing = [name for name in CANDIDATES if criteria(results, name)["passes"]]
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
            _interval(difference(results, name, MATCHED, PRIMARY, EVERY))
            if name in CANDIDATES
            else ""
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
    for name in CANDIDATES:
        found = criteria(results, name)
        lines.append(
            f"| {name} | {_f(found['primary'], True)} {_yes(found['affordable'])} | "
            f"{_f(found['red_at'], True)} ({_f(found['gap'])}) {_yes(found['sooner'])} | "
            f"{_f(found['position'], True)} {_yes(found['not_later'])} | "
            f"{_f(found['repeat'], True)} {_yes(found['harmless'])} | {_yes(found['passes'])} |"
        )
    if half == "validation":
        chosen = verdict(results)
        lines += [
            "",
            f"**Recommendation: NEEDS_HELD_OUT_CONFIRMATION, for {chosen}.** Development data "
            "cannot ship a ranking in this project (docs/adr/0013, docs/adr/0033)."
            if chosen
            else "**Recommendation: DO_NOT_SHIP.** No candidate meets the four conditions on the "
            "validation half.",
        ]
    return lines


def page(halves: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    lines = [
        "# A measured failure rate in place of the priority",
        "",
        "Generated by `python -m benchmarks.calibration`; protocol in docs/adr/0037. Development "
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
    args = parser.parse_args(argv)
    out = RESULTS / args.half
    if not args.from_cache:
        out.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for result in pool.map(run, HALVES[args.half]):
                result["testhunch"] = {"version": __version__}
                slug = result["project"].replace("/", "@")
                (out / f"{slug}.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
                sys.stdout.write(f"{result['project']}: {result['counts']}\n")
    halves = {}
    for half in HALVES:
        stored = sorted((RESULTS / half).glob("*.json"))
        if stored:
            halves[half] = [json.loads(p.read_text(encoding="utf-8")) for p in stored]
    (RESULTS / "README.md").write_bytes(page(halves).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
