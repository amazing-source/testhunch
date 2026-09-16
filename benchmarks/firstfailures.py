"""Does testhunch help when a test fails for the first time? (ROADMAP phase 4)

uv run python -m benchmarks.firstfailures              # every development project
uv run python -m benchmarks.firstfailures dynjs@dynjs

A ranking built on the recency of failures has nothing to say about a test that has never failed:
its priority is 0, and the ranking puts it behind every test that has failed before. Cheng et al.
(ISSTA 2024, Table 10) measured that on the first failure of each test, the latest failure falls
below random. This measures the same thing on testhunch's own ranking.

Failing jobs are split in two: those where at least one known failing test had failed before, and
those where none had. Two measures are reported per slice, and they must be read together:

- the position of the first failing test, normalized: what the ranking *predicts*;
- `red_at`, the share of the job's test time spent when the build turns red: prediction and cost
  together.

A ranking with no predictive power at all can still beat random on `red_at`, by running the quick
tests first. Reporting only the time would therefore claim a skill the ranking does not have.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from benchmarks.heldout import NotFrozen, record_peek
from benchmarks.replay import concurrent_groups
from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_DEVELOPMENT, RTPTORRENT_HELD_OUT
from benchmarks.study.engine import job_trial
from benchmarks.study.history import BuildHistory
from benchmarks.study.metrics import EPSILON_MS, Trial
from benchmarks.study.projects import CACHE, STEP_3_KEPT
from benchmarks.study.rankings import (
    PROXIMITY_SIGNALS,
    Context,
    LatestFailure,
    Ranking,
    _signal,
    tie,
)
from testhunch import __version__
from testhunch.junit import collapse

DEFAULT_OUT = Path("benchmarks") / "results" / "study" / "first-failures.md"
SIGNALS_OUT = Path("benchmarks") / "results" / "study" / "first-failures-signals.md"
REPEATED, FIRST = "had failed before", "had never failed before"
MEASURES = ("position", "position_known", "red_at")


def position(order: Sequence[str], failing: frozenset[str]) -> float:
    """Where the first failing test sits in the order, from just above 0 to 1."""
    for index, test in enumerate(order, start=1):
        if test in failing:
            return index / len(order)
    raise ValueError("the order holds no failing test")


def red_at(order: Sequence[str], trial: Trial) -> float | None:
    """Share of the job's test time spent when the first failing test ends.

    None when any duration of the job is unknown, as the share would be a guess.
    """
    costs = []
    for test in order:
        duration = trial.durations[test]
        if duration is None:
            return None
        costs.append(duration + EPSILON_MS)
    total = sum(costs)
    elapsed = 0
    for test, cost in zip(order, costs, strict=True):
        elapsed += cost
        if test in trial.failing:
            return elapsed / total
    raise ValueError("the order holds no failing test")


def shuffled(trial: Trial, seed: random.Random) -> list[str]:
    order = list(trial.tests)
    seed.shuffle(order)
    return order


@dataclass(frozen=True, slots=True)
class OneSignal:
    """The known tests ordered by a single proximity signal, with no history at all.

    A diagnostic, not a candidate ranking: it answers "does this signal separate the test that
    breaks from the tests that do not", which is the only question worth asking before deciding how
    to combine it (docs/adr/0014 step 3 rejected these signals on the mean of every job, where the
    ones with a usable history drown the ones without).
    """

    name: str

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        value = _signal(self.name, trial, context)
        unknown = [test for test in trial.tests if test not in context.builds.records]
        known = sorted(
            (test for test in trial.tests if test in context.builds.records),
            key=lambda test: (-value(test), tie(trial.job_id, test)),
        )
        return unknown + known, len(known)


def measure(
    directory: Path, rankings: Mapping[str, Ranking], changed_only: bool = False
) -> dict[str, dict[str, list[float]]]:
    """Every failing job of the project, measured per slice and per ranking.

    `directory` is a fetched project, so that a caller with the rows already on disk does not go
    and get them again: the tests pass the extract in `tests/fixtures/rtptorrent`, which is what
    keeps them from downloading the dataset on every run.

    `changed_only` keeps the jobs whose changed files are known: a proximity signal has nothing to
    say about a job whose change is unknown, so counting those would only dilute it.
    """
    builds = BuildHistory()
    rng = random.Random(0)  # seeded: the random baseline is the same for anyone who reruns this
    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for group in concurrent_groups(iter_jobs(directory)):
        collapsed = [collapse(job.results) for job in group]
        context = Context(builds, list)
        for job, results in zip(group, collapsed, strict=True):
            trial = job_trial(job, results)
            known_failing = {test for test in trial.failing if test in builds.records}
            # A job ranked from an empty history, or whose failures are all in tests the ranking
            # has never seen, says nothing about the ranking: it had nothing to rank them with.
            if not known_failing or builds.builds == 0:
                continue
            if changed_only and not job.changed_files:
                continue
            fresh = all(builds.records[test].failures == 0 for test in known_failing)
            values = out[FIRST if fresh else REPEATED]
            values["jobs"].append(1.0)
            orders = {name: ranking.order(trial, context)[0] for name, ranking in rankings.items()}
            orders["random"] = shuffled(trial, rng)
            for name, order in orders.items():
                values[f"{name}:position"].append(position(order, trial.failing))
                # Among the known tests only: separates the ranking's own bias from the rule that
                # runs every never-seen test first (docs/adr/0006, 0007).
                known = [test for test in order if test in builds.records]
                if known:
                    values[f"{name}:position_known"].append(position(known, trial.failing))
                spent = red_at(order, trial)
                if spent is not None:
                    values[f"{name}:red_at"].append(spent)
        builds.record(collapsed, [path for job in group for path in job.changed_files or ()])
    return out


def markdown(
    totals: Mapping[str, Mapping[str, list[float]]],
    names: Sequence[str],
    projects: Sequence[str] = (),
) -> str:
    lines = [
        "# Testhunch on a test's first failure",
        "",
        "Generated by `python -m benchmarks.firstfailures`, development projects only"
        + (", here " + ", ".join(projects) if projects else "")
        + " (docs/adr/0013). Failing jobs are split by whether any of their known failing tests "
        "had ever failed before. `position` is where the first failing test sits in the order, "
        "normalized; `position known` leaves out the tests the ranking has never seen, which "
        "always run first (docs/adr/0006); `red_at` is the share of the job's test time spent when "
        "the build turns red. **Lower is better in every column.**",
        "",
        "Read `position` and `red_at` together: a ranking with no predictive power can still beat "
        "random on `red_at` by running the quick tests first, and reporting only the time would "
        "claim a skill it does not have.",
    ]
    for slice_name in (REPEATED, FIRST):
        values = totals.get(slice_name)
        if not values:
            continue
        jobs = len(values["jobs"])
        lines += [
            "",
            f"## Jobs whose failing tests {slice_name} ({jobs} job{'' if jobs == 1 else 's'})",
            "",
            "| Ranking | position | position known | red_at |",
            "|---|---:|---:|---:|",
        ]
        for name in names:
            cells = []
            for kind in MEASURES:
                numbers = values.get(f"{name}:{kind}", [])
                cells.append(f"{statistics.fmean(numbers):.3f}" if numbers else "-")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def signals_markdown(totals: Mapping[str, Mapping[str, list[float]]], names: Sequence[str]) -> str:
    """The page of `--signals`: each proximity signal ordering on its own, with no history."""
    lines = [
        "# Do the proximity signals separate the test that breaks?",
        "",
        "Generated by `python -m benchmarks.firstfailures --signals`, development projects only "
        "(docs/adr/0013). Each row orders the known tests by **that signal alone, with no failure "
        "history at all**; `testhunch` is the whole current ranking, for scale. `position` is "
        "where the first failing test sits, normalized — **lower is better**, and random is "
        "about 0.47.",
        "",
        "Step 3 of the ranking study (docs/adr/0014) tried these signals and kept only "
        "`test_file_changed`. It judged them on the mean of every failing job, where the 94% "
        "with a usable failure history drown the 6% without. This asks the other question: what "
        "are they worth exactly where the history says nothing?",
        "",
        "Only jobs whose changed files are known are counted here; a proximity signal cannot say "
        "anything about the others.",
    ]
    for slice_name in (REPEATED, FIRST):
        values = totals.get(slice_name)
        if not values:
            continue
        jobs = len(values["jobs"])
        lines += [
            "",
            f"## Jobs whose failing tests {slice_name} ({jobs} job{'' if jobs == 1 else 's'})",
            "",
            "| Ordered by | position | red_at |",
            "|---|---:|---:|",
        ]
        for name in names:
            cells = []
            for kind in ("position", "red_at"):
                numbers = values.get(f"{name}:{kind}", [])
                cells.append(f"{statistics.fmean(numbers):.3f}" if numbers else "-")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.firstfailures")
    parser.add_argument(
        "projects", nargs="*", help="e.g. dynjs@dynjs; default: every development project"
    )
    parser.add_argument(
        "--held-out",
        action="store_true",
        help="allow held-out projects: only for versions frozen before the replay (docs/adr/0013)",
    )
    parser.add_argument(
        "--signals",
        action="store_true",
        help="order by each proximity signal alone, with no history: a diagnostic of whether the "
        "signal separates the test that breaks from the tests that do not",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=CACHE / "rtptorrent")
    args = parser.parse_args(argv)
    out = args.out or (SIGNALS_OUT if args.signals else DEFAULT_OUT)
    projects = args.projects or (RTPTORRENT_HELD_OUT if args.held_out else RTPTORRENT_DEVELOPMENT)
    held_out = [project for project in projects if project in RTPTORRENT_HELD_OUT]
    if held_out and not args.held_out:
        parser.error(
            f"held out, measured only with --held-out (docs/adr/0013): {', '.join(held_out)}"
        )
    if held_out:
        try:
            record_peek("benchmarks.firstfailures", held_out, "the product's ranking", __version__)
        except NotFrozen as exc:
            parser.error(str(exc))

    rankings: dict[str, Ranking] = {"testhunch": STEP_3_KEPT, "latest-failure": LatestFailure()}
    if args.signals:
        rankings = {f"{name} alone": OneSignal(name) for name in PROXIMITY_SIGNALS}
        rankings["testhunch"] = STEP_3_KEPT
    names = [*rankings, "random"]
    totals: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for project in projects:
        directory = fetch_project(project, args.cache)
        for slice_name, values in measure(directory, rankings, args.signals).items():
            for key, numbers in values.items():
                totals[slice_name][key].extend(numbers)
        counts = {name: len(values["jobs"]) for name, values in totals.items()}
        sys.stdout.write(f"{project}: {counts}\n")
    page = signals_markdown(totals, names) if args.signals else markdown(totals, names, projects)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
