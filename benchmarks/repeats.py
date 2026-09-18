"""Why the measured failure rate delays repeat failures: exploration after docs/adr/0037.

    uv run python -m benchmarks.repeats training

The training half only, and no candidate. ADR 0037's `calibrated` reaches first failures far sooner
and loses APFDc on the jobs whose failing test had failed before. Three explanations compete, and
two descriptions tell them apart:

- **Where the time goes.** On those jobs, the share of the test time spent before the failing test
  ends, under the shipped ranking and under `calibrated`, split by the state of the tests that run
  before it. More time on tests that never failed points to cheap silent tests overtaking; more on
  tests that failed a while ago, to the rate decaying more slowly with age than the priority does.
- **Streaks.** Among tests whose last failure was the build just before, how often they fail
  again, by how many builds in a row they had failed. If a long streak fails far more often than a
  single failure, pooling them in one state is what defers a test that is simply broken.
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
from benchmarks.split import RTPTORRENT_TRAINING
from benchmarks.study.engine import Study
from benchmarks.study.history import CaseRecord
from benchmarks.study.metrics import EPSILON_MS, Trial
from benchmarks.study.projects import CACHE, STEP_3_KEPT
from benchmarks.study.rankings import Calibrated, Candidate, Context
from testhunch.junit import collapse
from testhunch.models import CaseResult, Status

HALVES = {"training": RTPTORRENT_TRAINING}
RESULTS = Path("benchmarks/results/study/repeats")
GROUPS = (
    "unknown",
    "never failed",
    "failed 0",
    "failed 1",
    "failed 2-7",
    "failed 8-63",
    "failed 64+",
)
STREAKS = ((1, 1), (2, 3), (4, 7), (8, None))


def group(state: str) -> str:
    """The coarse group of a `CaseRecord.state`: never failed, or the age of the last failure."""
    if state.startswith("never"):
        return "never failed"
    age = state.removeprefix("failed ").split(",", 1)[0]
    low = int(age.split("-")[0].rstrip("+"))
    if low <= 1:
        return f"failed {low}"
    return "failed 2-7" if low < 8 else ("failed 8-63" if low < 64 else "failed 64+")


def streak(record: CaseRecord) -> int:
    return record.streak()


def _span(value: int) -> str:
    for low, high in STREAKS:
        if value >= low and (high is None or value <= high):
            return f"{low}+" if high is None else (f"{low}" if low == high else f"{low}-{high}")
    raise ValueError(value)


@dataclass
class Where:
    """A ranking that also writes down what runs before the failing test on repeat failures."""

    ranking: Candidate | Calibrated
    rows: list[dict[str, float]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.ranking.name

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        order, known = self.ranking.order(trial, context)
        records = context.builds.records
        failing = [test for test in trial.failing if test in records]
        repeat = any(records[test].failures for test in failing)
        if repeat and all(trial.durations[test] is not None for test in order):
            now = context.builds.builds
            cost = {test: (trial.durations[test] or 0) + EPSILON_MS for test in order}
            total = sum(cost.values())
            first = next(test for test in order if test in trial.failing)
            parts: dict[str, float] = {}
            for test in order[: order.index(first)]:
                part = group(records[test].state(now)) if test in records else "unknown"
                parts[part] = parts.get(part, 0.0) + cost[test] / total
            parts["half its own cost"] = cost[first] / 2 / total
            parts[
                "its own state: "
                + (group(records[first].state(now)) if first in records else "unknown")
            ] = 1.0
            self.rows.append(parts)
        return order, known


class Streaks(Study):
    """The study's engine, counting how tests that failed in the build just before fare next."""

    def __init__(self, rankings: Sequence[Where]) -> None:
        super().__init__(rankings)
        self.runs: Counter[str] = Counter()
        self.failed: Counter[str] = Counter()

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
            if record is None or not record.failures or now - 1 - record.last_failure:
                continue
            span = _span(streak(record))
            self.runs[span] += 1
            self.failed[span] += failed
        super().record(jobs, collapsed)


SHIPPED = STEP_3_KEPT.name
CALIBRATED = "calibrated"
BY_RUNS = "calibrated+runs"
MEASURED = (SHIPPED, CALIBRATED, BY_RUNS)


def run(project: str) -> dict[str, Any]:
    directory = fetch_project(project, CACHE / "rtptorrent")
    probes = [
        Where(STEP_3_KEPT),
        Where(Calibrated(CALIBRATED)),
        Where(Calibrated(BY_RUNS, by_runs=True)),
    ]
    engine = Streaks(probes)
    for group_ in concurrent_groups(iter_jobs(directory)):
        collapsed = [collapse(job.results) for job in group_]
        engine.rank(group_, collapsed)
        engine.record(group_, collapsed)
    return {
        "project": project,
        "where": {probe.name: probe.rows for probe in probes},
        "streak_runs": dict(engine.runs),
        "streak_failed": dict(engine.failed),
    }


def page(half: str, results: Sequence[Mapping[str, Any]]) -> str:
    names = [r["project"].split("@", 1)[1] for r in results]
    lines = [
        f"# Why the measured rate delays repeat failures ({half} half)",
        "",
        "Generated by `python -m benchmarks.repeats`; exploration after docs/adr/0037, development "
        "projects of the training half only: " + ", ".join(r["project"] for r in results) + ".",
        "",
        "## Where the time goes before the failing test, on jobs that had failed before",
        "",
        "Mean share of the job's test time spent on each group of tests before the failing test "
        f"ends, per project: `{SHIPPED}` (shipped), `{CALIBRATED}` and `{BY_RUNS}`. The "
        "groups are the state of the tests that run first; the last rows are where the failing "
        "test itself stood, as a share of the jobs.",
        "",
        "| Group | " + " | ".join(f"{n}: shipped / calibrated / +runs" for n in names) + " |",
        "|---|" + "---|" * len(names),
    ]
    parts = [*GROUPS, "half its own cost"]
    for part in [*parts, "red at", *(f"its own state: {g}" for g in GROUPS)]:
        cells = []
        for r in results:
            means = []
            for name in MEASURED:
                rows = r["where"][name]
                if part == "red at":
                    means.append(
                        statistics.fmean(
                            sum(v for k, v in row.items() if not k.startswith("its own state"))
                            + row["half its own cost"]
                            for row in rows
                        )
                    )
                else:
                    means.append(statistics.fmean(row.get(part, 0.0) for row in rows))
            cells.append(" / ".join(f"{value:.3f}" for value in means))
        lines.append(f"| {part} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Tests whose last failure was the build just before, by the length of their streak",
        "",
        "Failures per thousand runs that are not flaky, with the runs in brackets. The streak is "
        "how many of the test's latest runs in a row had failed.",
        "",
        "| Streak | " + " | ".join(names) + " |",
        "|---|" + "---:|" * len(names),
    ]
    for low, high in STREAKS:
        span = f"{low}+" if high is None else (f"{low}" if low == high else f"{low}-{high}")
        cells = []
        for r in results:
            runs = r["streak_runs"].get(span, 0)
            failed = r["streak_failed"].get(span, 0)
            cells.append(f"{1000 * failed / runs:.0f} ({runs})" if runs else "-")
        lines.append(f"| {span} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.repeats")
    parser.add_argument("half", choices=sorted(HALVES))
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--from-cache", action="store_true")
    args = parser.parse_args(argv)
    out = RESULTS / args.half
    if not args.from_cache:
        out.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for result in pool.map(run, HALVES[args.half]):
                slug = result["project"].replace("/", "@")
                (out / f"{slug}.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
                sys.stdout.write(f"{result['project']}\n")
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.json"))]
    (out.parent / f"{args.half}.md").write_bytes(page(args.half, results).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
