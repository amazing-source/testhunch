"""Where the cost decides the order, and what each measure owes to it (docs/adr/0036).

docs/adr/0035 found the mechanism: a test the history says nothing about scores zero, so the
duration, second in the sort key, orders those tests cheapest first. Taking it out everywhere buys
first-failure position and costs primary measure. This module measures **where** the duration
decides and what each measure owes to it, then scores the closed set of variants ADR 0036 fixed,
on one half of the development projects at a time:

    uv run python -m benchmarks.costorder training     # where the variants were explored
    uv run python -m benchmarks.costorder validation   # where they are judged

Every known test of a trial is in one of four states, read from what the history knew before the
build. The unknown tests run first, in the job's order, and are not ranked at all.

- risk: its failure priority is above zero, so the history estimates a risk;
- signal: its priority is zero, but a signal of the score fires (the test's own file changed);
- faded: it did fail, so long ago that its priority underflowed to exactly zero (docs/adr/0018);
- silent: it has never failed, and no signal fires.

The first two have a score above zero, and a score divided by a duration almost never ties. The
last two score exactly zero, together, and that is where the sort key's second element decides.
"Cold start" in `benchmarks.study.rankings` means a priority of zero, which is signal, faded and
silent together; the first-failure slice is a property of a trial, not of a test. The three are
kept apart here because they are not the same population.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_TRAINING, RTPTORRENT_VALIDATION
from benchmarks.study.engine import PRIMARY, study
from benchmarks.study.metrics import BUDGETS, Trial, scores
from benchmarks.study.projects import CACHE, STEP_3_KEPT
from benchmarks.study.rankings import (
    Candidate,
    Context,
    LatestFailure,
    ProductRanking,
    Ranking,
    Shuffled,
    SortKey,
    _expected_durations,
)
from testhunch import __version__
from testhunch.gitinfo import GitError, rev_parse

HALVES = {"training": RTPTORRENT_TRAINING, "validation": RTPTORRENT_VALIDATION}
RESULTS = Path("benchmarks/results/study/cost-order")
STATES = ("risk", "signal", "faded", "silent")
ZERO = ("faded", "silent")  # the states that score exactly zero
SHIPPED = STEP_3_KEPT.name
HASH = f"{SHIPPED}/tie=hash"
RANDOM = "random"
RELEASE_020 = "testhunch-0.2.0"
RESAMPLES = 10_000


@dataclass(slots=True)
class Diagnosed:
    """A candidate that also writes down, trial by trial, what decided its order.

    The first one measured is the reference, and it alone classifies the tests: a test's state
    comes from its history and from whether a signal fires, which no variant changes. The others
    record how far their order moved from the reference's.
    """

    candidate: Candidate
    reference: Diagnosed | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    last: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.candidate.name

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        unknown, keys = self.candidate.keys(trial, context)
        known = sorted(keys, key=keys.__getitem__)
        order = unknown + known
        measured = scores(trial, order, len(known))
        row: dict[str, Any] = {
            f"time_{fraction}": measured[f"time_{fraction}"] for fraction in BUDGETS
        }
        row["duration_pairs"] = duration_pairs(keys.values())
        if self.reference is None:
            row.update(characterize(trial, context, order, known, keys))
        else:
            row["displaced"] = sum(
                1 for mine, theirs in zip(order, self.reference.last, strict=True) if mine != theirs
            )
        self.last = order
        self.rows.append(row)
        return order, len(known)


def duration_pairs(keys: Iterable[SortKey]) -> int:
    """How many pairs of tests the duration decides: equal on the score, unequal on the cost.

    The duration is second in a candidate's key, and 0.0 there when it does not decide.
    """
    groups: dict[float, Counter[float]] = defaultdict(Counter)
    for key in keys:
        groups[key[0]][key[1]] += 1
    return sum(_pairs(counts.values()) for counts in groups.values())


def _pairs(sizes: Iterable[int]) -> int:
    """Pairs across different values, given how many tests share each value."""
    sizes = list(sizes)
    total = sum(sizes)
    return total * (total - 1) // 2 - sum(size * (size - 1) // 2 for size in sizes)


def state_of(test: str, context: Context, score: float) -> str:
    record = context.builds.records[test]
    if record.priority_at(context.builds.builds) > 0:
        return "risk"
    if score > 0:
        return "signal"
    return "faded" if record.failures else "silent"


def characterize(
    trial: Trial,
    context: Context,
    order: Sequence[str],
    known: Sequence[str],
    keys: Mapping[str, SortKey],
) -> dict[str, Any]:
    """Where the reference's order came from, for one trial."""
    durations = _expected_durations(known, context.builds.records)
    states = {test: state_of(test, context, -keys[test][0]) for test in known}
    first = next(test for test in order if test in trial.failing)
    zero = [test for test in known if states[test] in ZERO]
    percentile = weighted = None
    if states.get(first) in ZERO and len(zero) > 1:
        # Where the failing test's cost sits among the other zero-score tests: 0 the cheapest, 1
        # the dearest, ties counted half. If the failure were a draw that ignores the cost, this
        # would average one half.
        mine = durations[first]
        cheaper = [durations[test] for test in zero if durations[test] < mine]
        same = sum(1 for test in zero if durations[test] == mine) - 1
        percentile = (len(cheaper) + same / 2) / (len(zero) - 1)
        # The same share, counted in time: the cost of the zero-score tests cheaper than it, its
        # own and its equals' counted half, over their total cost. A failure drawn in proportion
        # to cost averages exactly one half here. Between the two, the cheapest-first order is
        # the quickest way to the failure and not the shortest in tests: the two measures of the
        # guardrail pull apart (docs/adr/0036).
        weighted = (sum(cheaper) + (same + 1) * mine / 2) / sum(durations[test] for test in zero)
    by_state: dict[str, Counter[float]] = {state: Counter() for state in ZERO}
    for test in zero:
        by_state[states[test]][durations[test]] += 1
    faded, silent = by_state["faded"], by_state["silent"]
    zero_pairs = {
        "silent": _pairs(silent.values()),
        "faded": _pairs(faded.values()),
        "mixed": sum(faded.values()) * sum(silent.values())
        - sum(count * silent[duration] for duration, count in faded.items()),
    }
    return {
        "unknown": len(order) - len(known),
        "states": {state: sum(1 for s in states.values() if s == state) for state in STATES},
        "first": states.get(first, "unknown"),
        "first_percentile": percentile,
        "first_time_share": weighted,
        "pairs": zero_pairs,
    }


def rankings() -> list[Ranking]:
    """The reference first, then the variants of ADR 0036, then the rankings they are read against.

    Built inside each worker: a replay keeps its diagnostics on the rankings themselves.
    """
    reference = Diagnosed(STEP_3_KEPT)
    variants = [Diagnosed(candidate, reference) for candidate in VARIANTS]
    return [
        reference,
        *variants,
        LatestFailure(),
        ProductRanking(),
        Shuffled(random.Random(0)),
    ]


# The closed set of docs/adr/0036, fixed before any of them was replayed. Global hash is
# docs/adr/0035's candidate, measured again as the yardstick the narrower forms are read against.
SCORED = f"{SHIPPED}/tie=cost-if-scored"
RISK_ONLY = f"{SHIPPED}/cold-free/tie=cost-if-risk"
VARIANTS: tuple[Candidate, ...] = (
    replace(STEP_3_KEPT, name=HASH, tie_break="hash"),
    # The cost decides between equal scores only where the score says something.
    replace(STEP_3_KEPT, name=SCORED, tie_break="cost-if-scored"),
    # The cost only where the failure history estimates a risk: neither divisor nor tie-break for a
    # test whose failure priority is zero, even when its own file changed.
    replace(STEP_3_KEPT, name=RISK_ONLY, cold_time_exponent=0.0, tie_break="cost-if-risk"),
)
NARROWER = (SCORED, RISK_ONLY)

# The decision rule of docs/adr/0036, written before the variants were replayed. The first two
# bounds are half of what global hash measured on the ten development projects (docs/adr/0035),
# 0.102 of first-failure position for 0.006 of primary; the last is ADR 0014's smallest difference.
FIRST_GAIN = 0.051
PRIMARY_LOSS = 0.003
REPEAT_HARM = 0.005


def run(project: str) -> dict[str, Any]:
    directory = fetch_project(project, CACHE / "rtptorrent")
    measured = rankings()
    result = study(iter_jobs(directory), measured)
    result["diagnostics"] = {
        ranking.name: ranking.rows for ranking in measured if isinstance(ranking, Diagnosed)
    }
    return {"project": project, "source": "rtptorrent", **result}


# Reading the results back ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Slice:
    label: str
    keep: Callable[[Mapping[str, Any], int], bool]


def _first_failure(value: bool | None) -> Callable[[Mapping[str, Any], int], bool]:
    return lambda result, index: result["trials"]["first_failure"][index] is value


EVERY = Slice("every failing job", lambda result, index: True)
FIRST = Slice("never failed before", _first_failure(True))
BEFORE = Slice("had failed before", _first_failure(False))


def values(
    result: Mapping[str, Any], ranking: str, measure: str, chosen: Slice
) -> list[tuple[int, float]]:
    """(trial index, value) for every trial of the slice that has this measure."""
    per_trial = result["rankings"][ranking]["per_trial"]
    if measure in per_trial:
        column = per_trial[measure]
    else:
        column = [row[measure] for row in result["diagnostics"][ranking]]
    return [
        (index, value)
        for index, value in enumerate(column)
        if value is not None and chosen.keep(result, index)
    ]


def mean(results: Sequence[Mapping[str, Any]], ranking: str, measure: str, chosen: Slice) -> float:
    """The mean of the per-project means, as every study page aggregates (docs/adr/0014)."""
    means = [
        statistics.fmean(v for _, v in found)
        for result in results
        if (found := values(result, ranking, measure, chosen))
    ]
    return statistics.fmean(means) if means else math.nan


def difference(
    results: Sequence[Mapping[str, Any]],
    after: str,
    before: str,
    measure: str,
    chosen: Slice,
    resamples: int = RESAMPLES,
    seed: int = 0,
) -> tuple[float, float, float]:
    """`after` minus `before`, paired trial by trial, with a 95% interval.

    The bootstrap draws projects, then trials inside each drawn project, which is the LRTS rule
    of docs/adr/0033 with a job in place of a pull request: RTPTorrent does not record them.
    """
    per_project = []
    for result in results:
        left = dict(values(result, after, measure, chosen))
        right = dict(values(result, before, measure, chosen))
        paired = [left[index] - right[index] for index in left if index in right]
        if paired:
            per_project.append(paired)
    if not per_project:
        return math.nan, math.nan, math.nan
    observed = statistics.fmean(statistics.fmean(project) for project in per_project)
    rng = random.Random(seed)
    drawn = sorted(
        statistics.fmean(
            statistics.fmean(rng.choices(project, k=len(project)))
            for project in rng.choices(per_project, k=len(per_project))
        )
        for _ in range(resamples)
    )
    return observed, drawn[math.floor(0.025 * resamples)], drawn[math.ceil(0.975 * resamples) - 1]


def contributions(
    results: Sequence[Mapping[str, Any]], after: str, before: str, measure: str
) -> dict[tuple[str, str], float]:
    """Share out `after` minus `before` over (slice, state of the reference's first failing test).

    Each project's mean difference is a sum over its trials divided by their count, so it splits
    exactly by trial group, and so does the mean over projects: the cells add up to the total.
    """
    cells: dict[tuple[str, str], float] = defaultdict(float)
    counted = 0
    for result in results:
        left = dict(values(result, after, measure, EVERY))
        right = dict(values(result, before, measure, EVERY))
        common = [index for index in left if index in right]
        if not common:
            continue
        counted += 1
        rows = result["diagnostics"][SHIPPED]
        for index in common:
            cells[(_slice_name(result, index), rows[index]["first"])] += (
                left[index] - right[index]
            ) / len(common)
    return {cell: total / counted for cell, total in cells.items()} if counted else {}


def _slice_name(result: Mapping[str, Any], index: int) -> str:
    flag = result["trials"]["first_failure"][index]
    return {True: FIRST.label, False: BEFORE.label, None: "neither"}[flag]


# The page ----------------------------------------------------------------------------------------


def _f(value: float, signed: bool = False) -> str:
    if math.isnan(value):
        return "-"
    return f"{value:+.3f}" if signed else f"{value:.3f}"


def _share(part: float, whole: float) -> str:
    return f"{part / whole:.1%}" if whole else "-"


def characterization(half: str, results: Sequence[Mapping[str, Any]]) -> list[str]:
    """Section one: where the shipped ranking's cost order decides, on this half."""
    rows = [
        (_slice_name(r, index), row)
        for r in results
        for index, row in enumerate(r["diagnostics"][SHIPPED])
    ]
    lines = [
        f"## Where the cost decides, {half} half",
        "",
        "### What the history knew about the tests of each failing job",
        "",
        "Mean share of a failing job's tests in each state, then mean over the projects.",
        "",
        "| Project | failing jobs | unknown | " + " | ".join(STATES) + " |",
        "|---|---:|---:|" + "---:|" * len(STATES),
    ]
    for result in results:
        own = result["diagnostics"][SHIPPED]
        shares = []
        for column in ("unknown", *STATES):
            per_trial = []
            for row in own:
                total = row["unknown"] + sum(row["states"].values())
                count = row["unknown"] if column == "unknown" else row["states"][column]
                per_trial.append(count / total)
            shares.append(f"{statistics.fmean(per_trial):.1%}")
        lines.append(f"| {result['project']} | {len(own)} | " + " | ".join(shares) + " |")

    lines += [
        "",
        "### The state of the first failing test, under the shipped order",
        "",
        "Failing jobs pooled over the half's projects. `unknown` is a failing test the history had "
        "never seen, which runs first whatever the ranking.",
        "",
        "| Slice | jobs | " + " | ".join(("unknown", *STATES)) + " |",
        "|---|---:|" + "---:|" * (len(STATES) + 1),
    ]
    for label in (FIRST.label, BEFORE.label, "neither"):
        chosen = [row for name, row in rows if name == label]
        counts = Counter(row["first"] for row in chosen)
        lines.append(
            f"| {label} | {len(chosen)} | "
            + " | ".join(str(counts[state]) for state in ("unknown", *STATES))
            + " |"
        )

    first_rows = [row for name, row in rows if name == FIRST.label]
    in_zero = [row for row in first_rows if row["first"] in ZERO]
    moved = _moved(results, HASH, FIRST)
    lines += [
        "",
        f"**{_share(len(in_zero), len(first_rows))} of the first-failure jobs** "
        f"({len(in_zero)} of {len(first_rows)}) have their first failing test among the "
        "zero-score tests, where only the tie-break orders it. Under a hash tie-break, the "
        f"position of the first failing test changes in {moved[0]} of those {moved[1]} jobs.",
    ]

    measured = [row for row in in_zero if row["first_percentile"] is not None]
    if measured:
        lines += [
            "",
            "### How dear the failing test is, among the tests that score zero",
            "",
            "For each first-failure job whose failing test scored zero, where its cost sits among "
            "the zero-score tests: in tests, the share of them cheaper than it; in time, the "
            "share of their total cost spent on cheaper ones, its own counted half. A failure "
            "that ignored cost would average 0.5 in tests; one drawn in proportion to cost would "
            "average 0.5 in time. Between the two, running the cheapest first reaches the failure "
            "sooner in time and later in tests than a shuffle of the same tests.",
            "",
            "| counted in | jobs | mean | first quartile | median | third quartile | above 0.5 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for label, column in (("tests", "first_percentile"), ("time", "first_time_share")):
            found = [row[column] for row in measured]
            quartiles = statistics.quantiles(found, n=4) if len(found) > 1 else found * 3
            lines.append(
                f"| {label} | {len(found)} | {statistics.fmean(found):.3f} | "
                + " | ".join(f"{q:.3f}" for q in quartiles)
                + f" | {_share(sum(1 for p in found if p > 0.5), len(found))} |"
            )

    lines += [
        "",
        "### How far the shipped order is from a shuffle on first failures, and why",
        "",
        "Mean of the per-project means over the first-failure jobs. The distance to random splits "
        "exactly into what the cost tie-break adds (shipped minus hash) and what remains with a "
        "hash tie-break (hash minus random): the zero-score tests, however ordered, still run "
        "after every test with a failure priority above zero.",
        "",
        "| Jobs | measure | shipped | hash | random | from the cost tie-break | from the rest |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    silent = Slice(
        "never failed before, failing test silent",
        lambda result, index: (
            FIRST.keep(result, index) and result["diagnostics"][SHIPPED][index]["first"] == "silent"
        ),
    )
    for jobs in (FIRST, silent):
        for measure, label in (("position", "position"), ("red_at", "red at")):
            shipped, hashed, shuffled = (
                mean(results, ranking, measure, jobs) for ranking in (SHIPPED, HASH, RANDOM)
            )
            lines.append(
                f"| {jobs.label} | {label} | {_f(shipped)} | {_f(hashed)} | {_f(shuffled)} | "
                f"{_f(shipped - hashed, True)} | {_f(hashed - shuffled, True)} |"
            )

    ahead = []
    for result in results:
        in_front = [
            (row["unknown"] + row["states"]["risk"] + row["states"]["signal"])
            / (row["unknown"] + sum(row["states"].values()))
            for index, row in enumerate(result["diagnostics"][SHIPPED])
            if silent.keep(result, index)
        ]
        if in_front:
            ahead.append(statistics.fmean(in_front))
    unscored = sum(
        1 for _, row in rows if not row["states"]["risk"] and not row["states"]["signal"]
    )
    lines += [
        "",
        "On the first-failure jobs whose failing test is silent, the tests that run before every "
        "zero-score test (unknown, risk and signal) are "
        f"{_f(statistics.fmean(ahead)) if ahead else '-'} of the job, mean of the per-project "
        f"means. Of the {len(rows)} failing jobs, {unscored} have no known test scoring above zero "
        "at all.",
    ]

    lines += [
        "",
        "### What the cost order is worth, by regime",
        "",
        "The shipped ranking minus the same ranking with a hash tie-break, shared out over the "
        "slice of the job and the state of its first failing test under the shipped order. Each "
        "cell is its contribution to the mean of the per-project means, so a column adds up to "
        "its total. On the primary measure, higher is better, so a positive cell is what the "
        "cost order earns there; on the position, lower is better, so a positive cell is what it "
        "costs.",
        "",
        "| Slice | first failing test | primary (APFDc) | position |",
        "|---|---|---:|---:|",
    ]
    primary = contributions(results, SHIPPED, HASH, PRIMARY)
    position = contributions(results, SHIPPED, HASH, "position")
    for cell in sorted(set(primary) | set(position)):
        lines.append(
            f"| {cell[0]} | {cell[1]} | {_f(primary.get(cell, 0.0), True)} | "
            f"{_f(position.get(cell, 0.0), True)} |"
        )
    lines.append(
        f"| **total** | | **{_f(sum(primary.values()), True)}** | "
        f"**{_f(sum(position.values()), True)}** |"
    )

    pairs: Counter[str] = Counter()
    for _, row in rows:
        pairs.update(row["pairs"])
    every = sum(row["duration_pairs"] for _, row in rows)
    lines += [
        "",
        "### Which pairs the duration decides",
        "",
        "Pairs of tests the shipped key orders by duration, summed over the half's failing jobs: "
        "equal on the score, different on the cost.",
        "",
        "| between | pairs | share |",
        "|---|---:|---:|",
        f"| two silent tests | {pairs['silent']} | {_share(pairs['silent'], every)} |",
        f"| two faded tests | {pairs['faded']} | {_share(pairs['faded'], every)} |",
        f"| a faded and a silent test | {pairs['mixed']} | {_share(pairs['mixed'], every)} |",
        f"| two tests of equal score above zero | {every - sum(pairs.values())} | "
        f"{_share(every - sum(pairs.values()), every)} |",
        f"| **all** | {every} | |",
    ]
    return lines


def _moved(results: Sequence[Mapping[str, Any]], ranking: str, chosen: Slice) -> tuple[int, int]:
    """Jobs of the slice whose first failing test scored zero, and how many of them it moves."""
    moved = total = 0
    for result in results:
        rows = result["diagnostics"][SHIPPED]
        mine = dict(values(result, ranking, "position", chosen))
        theirs = dict(values(result, SHIPPED, "position", chosen))
        for index in mine:
            if rows[index]["first"] in ZERO:
                total += 1
                moved += mine[index] != theirs[index]
    return moved, total


def _pooled(
    results: Sequence[Mapping[str, Any]],
    ranking: str,
    measure: str,
    keep: Callable[[Mapping[str, Any], int, Mapping[str, Any]], bool],
) -> list[float]:
    """Differences against the shipped ranking, job by job, pooled over the half's projects."""
    found = []
    for result in results:
        mine = dict(values(result, ranking, measure, EVERY))
        theirs = dict(values(result, SHIPPED, measure, EVERY))
        rows = result["diagnostics"][SHIPPED]
        found += [mine[i] - theirs[i] for i in mine if i in theirs and keep(result, i, rows[i])]
    return found


def _interval(found: tuple[float, float, float]) -> str:
    value, low, high = found
    return f"{_f(value, True)} [{_f(low, True)}, {_f(high, True)}]"


def criteria(results: Sequence[Mapping[str, Any]], ranking: str) -> dict[str, Any]:
    """The three measured conditions of docs/adr/0036, for one variant against the shipped ranking.

    The other two, a causal rule and a simple one, hold by construction: every variant reads only
    the history before the build, and each is stated in one sentence.
    """

    def change(measure: str, chosen: Slice) -> float:
        return mean(results, ranking, measure, chosen) - mean(results, SHIPPED, measure, chosen)

    first = change("position", FIRST)
    primary = change(PRIMARY, EVERY)
    repeat_position = change("position", BEFORE)
    repeat_primary = change(PRIMARY, BEFORE)
    gains = -first >= FIRST_GAIN
    affordable = -primary <= PRIMARY_LOSS
    harmless = repeat_position < REPEAT_HARM and -repeat_primary < REPEAT_HARM
    return {
        "first": first,
        "primary": primary,
        "repeat_position": repeat_position,
        "repeat_primary": repeat_primary,
        "gains": gains,
        "affordable": affordable,
        "harmless": harmless,
        "passes": gains and affordable and harmless,
    }


def verdict(results: Sequence[Mapping[str, Any]]) -> str | None:
    """The narrower variant the validation half recommends for held-out data, if any."""
    passing = [name for name in NARROWER if criteria(results, name)["passes"]]
    return max(passing, key=lambda name: mean(results, name, PRIMARY, EVERY)) if passing else None


def variants(half: str, results: Sequence[Mapping[str, Any]]) -> list[str]:
    """Section two: the closed set of docs/adr/0036 on this half."""
    names = list(results[0]["rankings"])
    diagnosed = [name for name in names if name in results[0]["diagnostics"] and name != SHIPPED]
    lines = [
        f"## The variants, {half} half",
        "",
        "Mean of the per-project means, on the same failing jobs. Differences are against the "
        "shipped ranking, with a 95% interval that resamples projects, then jobs inside them. "
        "Position and red at: lower is better. Primary (APFDc) and the share of jobs caught "
        "within a quarter of the test time: higher is better.",
        "",
        "### The primary measure, and the jobs whose failing test had failed before",
        "",
        "| Ranking | primary | against shipped | against 0.2.0 | had failed: APFDc | "
        "against shipped | had failed: position | against shipped |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    base = {
        (measure, chosen.label): mean(results, SHIPPED, measure, chosen)
        for measure in (PRIMARY, "position")
        for chosen in (EVERY, BEFORE, FIRST)
    }
    release = mean(results, RELEASE_020, PRIMARY, EVERY)
    for name in names:
        primary = mean(results, name, PRIMARY, EVERY)
        against = (
            "" if name == SHIPPED else _interval(difference(results, name, SHIPPED, PRIMARY, EVERY))
        )
        repeat = mean(results, name, PRIMARY, BEFORE)
        position = mean(results, name, "position", BEFORE)
        lines.append(
            f"| {name} | {_f(primary)} | {against} | {_f(primary - release, True)} | "
            f"{_f(repeat)} | {_f(repeat - base[(PRIMARY, BEFORE.label)], True)} | "
            f"{_f(position)} | {_f(position - base[('position', BEFORE.label)], True)} |"
        )

    shuffled = mean(results, RANDOM, "position", FIRST)
    old = mean(results, RELEASE_020, "position", FIRST)
    lines += [
        "",
        "### The jobs whose failing test had never failed before",
        "",
        "| Ranking | position | against shipped | against random | against 0.2.0 | red at | "
        "caught within 25% of the time |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for name in names:
        position = mean(results, name, "position", FIRST)
        against = (
            ""
            if name == SHIPPED
            else _interval(difference(results, name, SHIPPED, "position", FIRST))
        )
        caught = (
            _f(mean(results, name, "time_0.25", FIRST))
            if name in results[0]["diagnostics"]
            else "-"
        )
        lines.append(
            f"| {name} | {_f(position)} | {against} | {_f(position - shuffled, True)} | "
            f"{_f(position - old, True)} | {_f(mean(results, name, 'red_at', FIRST))} | "
            f"{caught} |"
        )

    reference_pairs = sum(
        row["duration_pairs"] for r in results for row in r["diagnostics"][SHIPPED]
    )
    jobs = sum(len(r["diagnostics"][SHIPPED]) for r in results)
    lines += [
        "",
        "### What each variant changes",
        "",
        "Failing jobs pooled over the half. A job's order changes when any test moves; its first "
        "failing test moves when its position does. The pairs are those the duration decides, "
        "equal on the score and unequal on the cost, summed over the jobs: the shipped ranking "
        f"has {reference_pairs} of them here.",
        "",
        "| Ranking | jobs whose order changes | first failing test moved | of them, never "
        "failed before | pairs the duration still decides | moved away from the duration |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in diagnosed:
        changed = sum(1 for r in results for row in r["diagnostics"][name] if row["displaced"])
        moved = fresh = 0
        for r in results:
            mine = r["rankings"][name]["per_trial"]["position"]
            theirs = r["rankings"][SHIPPED]["per_trial"]["position"]
            for index, (a, b) in enumerate(zip(mine, theirs, strict=True)):
                if a != b:
                    moved += 1
                    fresh += r["trials"]["first_failure"][index] is True
        kept = sum(row["duration_pairs"] for r in results for row in r["diagnostics"][name])
        lines.append(
            f"| {name} | {changed} ({_share(changed, jobs)}) | {moved} ({_share(moved, jobs)}) "
            f"| {fresh} | {kept} | {_share(reference_pairs - kept, reference_pairs)} |"
        )

    lines += [
        "",
        "### Where the effect falls",
        "",
        "Mean difference against the shipped ranking, per failing job, pooled over the half, by "
        "the slice of the job and the state of its first failing test under the shipped order. "
        "`signal`, `faded` and `silent` together are what `benchmarks.study` calls cold start: a "
        "failure priority of zero.",
        "",
        "| Slice | first failing test | jobs | "
        + " | ".join(f"{_short(name)}: position | {_short(name)}: APFDc" for name in diagnosed)
        + " |",
        "|---|---|---:|" + "---:|" * (2 * len(diagnosed)),
    ]
    cells = sorted(
        {
            (_slice_name(r, index), row["first"])
            for r in results
            for index, row in enumerate(r["diagnostics"][SHIPPED])
        }
    )
    for cell in cells:

        def in_cell(
            result: Mapping[str, Any],
            index: int,
            row: Mapping[str, Any],
            cell: tuple[str, str] = cell,
        ) -> bool:
            return (_slice_name(result, index), row["first"]) == cell

        lines.append(
            f"| {cell[0]} | {cell[1]} | {len(_pooled(results, SHIPPED, 'position', in_cell))} | "
            + " | ".join(
                _mean_cell(_pooled(results, name, measure, in_cell))
                for name in diagnosed
                for measure in ("position", PRIMARY)
            )
            + " |"
        )

    lines += [
        "",
        "### Cheap and dear failing tests, where the history is silent",
        "",
        "The first-failure jobs whose failing test scored zero, split by where its cost sits among "
        "the zero-score tests, below or above the middle counted in tests. Mean difference "
        "against the shipped ranking, pooled over the half.",
        "",
        "| Failing test | jobs | "
        + " | ".join(
            f"{_short(name)}: position | {_short(name)}: red at | {_short(name)}: APFDc"
            for name in diagnosed
        )
        + " |",
        "|---|---:|" + "---:|" * (3 * len(diagnosed)),
    ]
    for label, cheap in (("cheaper than the middle", True), ("dearer than the middle", False)):

        def by_cost(
            result: Mapping[str, Any], index: int, row: Mapping[str, Any], cheap: bool = cheap
        ) -> bool:
            share = row["first_percentile"]
            return (
                result["trials"]["first_failure"][index] is True
                and share is not None
                and (share < 0.5) == cheap
            )

        lines.append(
            f"| {label} | {len(_pooled(results, SHIPPED, 'position', by_cost))} | "
            + " | ".join(
                _mean_cell(_pooled(results, name, measure, by_cost))
                for name in diagnosed
                for measure in ("position", "red_at", PRIMARY)
            )
            + " |"
        )

    lines += [
        "",
        "### The decision rule of docs/adr/0036",
        "",
        f"A narrower variant must gain at least {FIRST_GAIN} of first-failure position, lose at "
        f"most {PRIMARY_LOSS} of primary, and move neither measure of the jobs that had failed "
        f"before by {REPEAT_HARM} or more the wrong way. It is judged on the validation half; the "
        "training half is shown for reference. Global hash is the yardstick, not a candidate.",
        "",
        "| Ranking | first failures | gains enough | primary | loses little enough | had "
        "failed: position, APFDc | harmless | meets all three |",
        "|---|---:|---|---:|---|---|---|---|",
    ]
    for name in (HASH, *NARROWER):
        found = criteria(results, name)
        lines.append(
            f"| {name} | {_f(found['first'], True)} | {_yes(found['gains'])} | "
            f"{_f(found['primary'], True)} | {_yes(found['affordable'])} | "
            f"{_f(found['repeat_position'], True)}, {_f(found['repeat_primary'], True)} | "
            f"{_yes(found['harmless'])} | {_yes(found['passes'])} |"
        )
    if half == "validation":
        chosen = verdict(results)
        lines += [
            "",
            (
                f"**Recommendation: NEEDS_HELD_OUT_CONFIRMATION, for {chosen}.** It meets the "
                "three measured conditions on the validation half. Development data cannot ship a "
                "ranking in this project (docs/adr/0013, docs/adr/0033): the next step would be to "
                "freeze it and measure it once on held-out data."
                if chosen
                else "**Recommendation: DO_NOT_SHIP.** No narrower variant meets the three "
                "measured conditions on the validation half."
            ),
        ]
    return lines


def _mean_cell(found: Sequence[float]) -> str:
    return _f(statistics.fmean(found), True) if found else "-"


def _short(name: str) -> str:
    return name.removeprefix(f"{SHIPPED}/")


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def page(halves: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    lines = [
        "# Where the cost decides the order",
        "",
        "Generated by `python -m benchmarks.costorder`; protocol in docs/adr/0036. Development "
        "projects only, split into the halves of `benchmarks/split.py`: "
        + "; ".join(
            f"{half}: " + ", ".join(r["project"] for r in rs) for half, rs in halves.items()
        )
        + ". LRTS and the held-out projects are not touched.",
    ]
    for half, results in halves.items():
        lines += ["", *characterization(half, results)]
    for half, results in halves.items():
        if all(name in results[0]["rankings"] for name in NARROWER):
            lines += ["", *variants(half, results)]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.costorder")
    parser.add_argument("half", choices=sorted(HALVES))
    parser.add_argument("--jobs", type=int, default=3, help="projects replayed at once")
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="rebuild the page from the stored results, replaying nothing",
    )
    args = parser.parse_args(argv)
    out = RESULTS / args.half
    if not args.from_cache:
        out.mkdir(parents=True, exist_ok=True)
        commit = _commit()
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for result in pool.map(run, HALVES[args.half]):
                result["testhunch"] = {"version": __version__, "commit": commit}
                slug = result["project"].replace("/", "@")
                (out / f"{slug}.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
                sys.stdout.write(f"{result['project']}: {result['counts']}\n")
    halves = {}
    for half in sorted(HALVES, key=list(HALVES).index):
        stored = sorted((RESULTS / half).glob("*.json"))
        if stored:
            halves[half] = [json.loads(path.read_text(encoding="utf-8")) for path in stored]
    (RESULTS / "README.md").write_bytes(page(halves).encode("utf-8"))
    return 0


def _commit() -> str | None:
    try:
        return rev_parse("HEAD")
    except GitError:
        return None


if __name__ == "__main__":
    sys.exit(main())
