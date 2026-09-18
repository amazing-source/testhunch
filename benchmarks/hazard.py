"""Does an old failure still predict one, and where does the time go before a first failure?

Two descriptions of the shipped ranking, on one half of the development projects, before any
candidate is written (docs/adr/0036 named the question, ROADMAP phase 7):

    uv run python -m benchmarks.hazard training

**The hazard.** Before each build, every test that runs is in a state read from the history: it
never failed, or its last failure was k builds before. Counting, over the replay, how often a test
in each state fails in the build says how much each state predicts. RTPTorrent's priority,
0.8 * 0.2^k, says a failure k builds old outweighs never having failed at any k; the counts say
whether it does. The outcome is a failure that is not flaky (docs/adr/0006), what the rankings are
scored on.

**The time.** On the jobs whose failing test had never failed and scored zero, everything that runs
before it, split by state: the unknown tests, the tests with a live priority by the age of their
failure, the tests whose file changed, and the zero-score tests the cost order puts first. The
parts add up to the job's `red_at` less half the failing test's own cost.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.replay import Job, concurrent_groups
from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_TRAINING, RTPTORRENT_VALIDATION
from benchmarks.study.engine import Study
from benchmarks.study.history import AGE_BUCKETS, bucket
from benchmarks.study.metrics import EPSILON_MS, Trial
from benchmarks.study.projects import CACHE, STEP_3_KEPT
from benchmarks.study.rankings import Context
from testhunch import __version__
from testhunch.junit import collapse
from testhunch.models import CaseResult, Status

HALVES = {"training": RTPTORRENT_TRAINING, "validation": RTPTORRENT_VALIDATION}
RESULTS = Path("benchmarks/results/study/hazard")
# Builds since the last failure: 0 is a failure in the build just before. The same spans as the
# calibrated ranking counts in (docs/adr/0037).
AGES = AGE_BUCKETS
# Past failures of a test whose last failure is at least `OLD` builds back.
OLD = 16
COUNTS = ((1, 1), (2, 4), (5, None))
# Runs of a test that never failed.
RUNS = ((1, 3), (4, 15), (16, 63), (64, 255), (256, None))
NEVER = "never failed"


def age_bucket(age: int) -> str:
    return bucket(age, AGES)


def _span(value: int, spans: Sequence[tuple[int, int | None]]) -> str:
    for low, high in spans:
        if value >= low and (high is None or value <= high):
            return f"{low}+" if high is None else (f"{low}" if low == high else f"{low}-{high}")
    raise ValueError(value)


class Hazard(Study):
    """The study's engine, counting before each build how each state of test fares in it."""

    def __init__(self, probe: Probe) -> None:
        super().__init__([probe])
        self.probe = probe
        self.by_age: Counter[str] = Counter()
        self.failed_by_age: Counter[str] = Counter()
        self.by_count: Counter[str] = Counter()  # old failures, by how many
        self.failed_by_count: Counter[str] = Counter()
        self.by_runs: Counter[str] = Counter()  # never failed, by how many runs
        self.failed_by_runs: Counter[str] = Counter()

    def record(self, jobs: Sequence[Job], collapsed: Sequence[tuple[CaseResult, ...]]) -> None:
        outcome: dict[str, bool] = {}
        for results in collapsed:
            for result in results:
                if result.status is Status.SKIPPED:
                    continue
                failed = result.status.is_failure and not result.flaky
                outcome[result.key] = outcome.get(result.key, False) or failed
        now = self.builds.builds
        for key, failed in outcome.items():
            record = self.builds.records.get(key)
            if record is None:
                continue
            if not record.failures:
                self._count(NEVER, failed)
                self.by_runs[_span(record.runs, RUNS)] += 1
                self.failed_by_runs[_span(record.runs, RUNS)] += failed
                continue
            age = now - 1 - record.last_failure
            self._count(age_bucket(age), failed)
            if age >= OLD:
                self.by_count[_span(record.failures, COUNTS)] += 1
                self.failed_by_count[_span(record.failures, COUNTS)] += failed
        super().record(jobs, collapsed)

    def _count(self, state: str, failed: bool) -> None:
        self.by_age[state] += 1
        self.failed_by_age[state] += failed


@dataclass
class Probe:
    """The shipped ranking, writing down what runs before a first failure that scored zero."""

    name: str = STEP_3_KEPT.name
    rows: list[dict[str, float]] = field(default_factory=list)

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        unknown, keys = STEP_3_KEPT.keys(trial, context)
        known = sorted(keys, key=keys.__getitem__)
        order = unknown + known
        records = context.builds.records
        failing = [test for test in trial.failing if test in records]
        first = next(test for test in order if test in trial.failing)
        fresh = bool(failing) and all(records[test].failures == 0 for test in failing)
        raw = [trial.durations[test] for test in order]
        if fresh and first in keys and keys[first][0] == 0 and None not in raw:
            cost = {test: (trial.durations[test] or 0) + EPSILON_MS for test in order}
            total = sum(cost.values())
            now = context.builds.builds
            parts: dict[str, float] = {}
            for test in order[: order.index(first)]:
                record = records.get(test)
                if record is None:
                    part = "unknown"
                elif keys[test][0] == 0:
                    part = "zero score, cheaper"
                elif record.priority_at(now) > 0:
                    part = f"failed {age_bucket(now - 1 - record.last_failure)} builds before"
                else:
                    part = "file changed"
                parts[part] = parts.get(part, 0.0) + cost[test] / total
            parts["half its own cost"] = cost[first] / 2 / total
            self.rows.append(dict(parts))
        return order, len(known)


def run(project: str) -> dict[str, Any]:
    directory = fetch_project(project, CACHE / "rtptorrent")
    probe = Probe()
    engine = Hazard(probe)
    for group in concurrent_groups(iter_jobs(directory)):
        collapsed = [collapse(job.results) for job in group]
        engine.rank(group, collapsed)
        engine.record(group, collapsed)
    return {
        "project": project,
        "builds": engine.builds.builds,
        "by_age": dict(engine.by_age),
        "failed_by_age": dict(engine.failed_by_age),
        "by_count": dict(engine.by_count),
        "failed_by_count": dict(engine.failed_by_count),
        "by_runs": dict(engine.by_runs),
        "failed_by_runs": dict(engine.failed_by_runs),
        "first_failures": probe.rows,
    }


def _rate(failed: int, runs: int) -> str:
    return f"{1000 * failed / runs:.2f} ({runs})" if runs else "-"


def _labels(spans: Sequence[tuple[int, int | None]]) -> list[str]:
    return [f"{lo}+" if hi is None else (f"{lo}" if lo == hi else f"{lo}-{hi}") for lo, hi in spans]


def page(half: str, results: Sequence[Mapping[str, Any]]) -> str:
    names = [r["project"].split("@", 1)[1] for r in results]
    ages = [NEVER, *(age_bucket(low) for low, _ in AGES), f"{AGES[-1][1] + 1}+"]
    lines = [
        f"# Does an old failure still predict one? ({half} half)",
        "",
        "Generated by `python -m benchmarks.hazard`; development projects only, "
        + ", ".join(r["project"] for r in results)
        + ". Failures per thousand runs of a test in that state, with the runs in brackets. A run "
        "is a test that passed or failed in a build; the failure is one that is not flaky.",
        "",
        "## By the age of the last failure, in builds",
        "",
        "| Last failure | " + " | ".join(names) + " |",
        "|---|" + "---:|" * len(names),
    ]
    for state in ages:
        cells = [
            _rate(r["failed_by_age"].get(state, 0), r["by_age"].get(state, 0)) for r in results
        ]
        lines.append(f"| {state} | " + " | ".join(cells) + " |")
    lines += [
        "",
        f"## Failures at least {OLD} builds old, by how many the test had",
        "",
        "| Past failures | " + " | ".join(names) + " |",
        "|---|" + "---:|" * len(names),
    ]
    for label in _labels(COUNTS):
        cells = [
            _rate(r["failed_by_count"].get(label, 0), r["by_count"].get(label, 0)) for r in results
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Tests that never failed, by how many times they ran",
        "",
        "| Runs | " + " | ".join(names) + " |",
        "|---|" + "---:|" * len(names),
    ]
    for label in _labels(RUNS):
        cells = [
            _rate(r["failed_by_runs"].get(label, 0), r["by_runs"].get(label, 0)) for r in results
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    parts = sorted({part for r in results for row in r["first_failures"] for part in row})
    lines += [
        "",
        "## Where the time goes before a first failure",
        "",
        "Jobs whose failing test had never failed and scored zero, under the shipped order. Each "
        "cell is the mean share of the job's test time spent on that part before the failing test "
        "ends, per project; the column adds up to the project's mean red at.",
        "",
        "| Part | "
        + " | ".join(
            f"{n} ({len(r['first_failures'])})" for n, r in zip(names, results, strict=True)
        )
        + " |",
        "|---|" + "---:|" * len(names),
    ]
    for part in [*parts, "red at"]:
        cells = []
        for r in results:
            rows = r["first_failures"]
            if not rows:
                cells.append("-")
                continue
            if part == "red at":
                value = statistics.fmean(
                    sum(row.values()) + row["half its own cost"] for row in rows
                )
            else:
                value = statistics.fmean(row.get(part, 0.0) for row in rows)
            cells.append(f"{value:.3f}")
        lines.append(f"| {part} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.hazard")
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
                sys.stdout.write(f"{result['project']}: {len(result['first_failures'])} jobs\n")
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.json"))]
    (out.parent / f"{args.half}.md").write_bytes(page(args.half, results).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
