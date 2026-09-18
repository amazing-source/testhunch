"""Two candidates, one rule written first, and one look at the held-out projects (docs/adr/0038).

    uv run python -m benchmarks.confirmation training              # explored, predictions checked
    uv run python -m benchmarks.confirmation held-out --held-out   # the one look, ledger row first

The candidates and the rule are fixed in docs/adr/0038 and in this module before either is
replayed. The training half can reveal a defect in the code, which is then fixed and stated; it
cannot add, remove or alter a candidate. The held-out replay writes its row in the ledger before it
starts (docs/adr/0016) and is judged by `criteria` and `verdict`, nothing else.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from benchmarks.costorder import BEFORE, EVERY, FIRST, Slice, caught, mean, values
from benchmarks.heldout import NotFrozen, record_peek
from benchmarks.replay import Job, concurrent_groups
from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_HELD_OUT, RTPTORRENT_TRAINING
from benchmarks.study.engine import PRIMARY, Study
from benchmarks.study.history import changed_suffixes, file_changed
from benchmarks.study.projects import CACHE, STEP_3_KEPT
from benchmarks.study.rankings import (
    Calibrated,
    LatestFailure,
    ProductRanking,
    Ranking,
    Shuffled,
    TwoStage,
)
from testhunch import __version__
from testhunch.junit import collapse
from testhunch.models import CaseResult, Status

MODES = {"training": RTPTORRENT_TRAINING, "held-out": RTPTORRENT_HELD_OUT}
RESULTS = Path("benchmarks/results/study/confirmation")
SHIPPED = STEP_3_KEPT.name
LATEST = "latest-failure"
RANDOM = "random"
RELEASE_020 = "testhunch-0.2.0"
FROZEN = "calibrated+runs"  # docs/adr/0037's candidate, measured again as a reference
WITH_FILES = "calibrated+runs+file"
TWO_STAGE = "two-stage"
CANDIDATES = (TWO_STAGE, WITH_FILES)
_FILES = Calibrated(WITH_FILES, by_runs=True, files=True)

# The rule of docs/adr/0038. `REPEAT_VETO` is ADR 0014's smallest difference; the bootstrap is the
# one ADR 0033 fixed, with a build in place of a pull request.
REPEAT_VETO = -0.005
SHARE_OF_PROJECTS = 0.6
RESAMPLES = 10_000
# Predicted chance of failing, in decades, for the calibration check.
BINS = (0.0, 0.001, 0.01, 0.1, 1.0)


def rankings() -> list[Ranking]:
    return [
        STEP_3_KEPT,
        TwoStage(TWO_STAGE, STEP_3_KEPT, _FILES),
        _FILES,
        Calibrated(FROZEN, by_runs=True),
        LatestFailure(),
        ProductRanking(),
        Shuffled(random.Random(0)),
    ]


class Checked(Study):
    """The study's engine, also comparing `calibrated+runs+file`'s chances with what happens."""

    def __init__(self, measured: Sequence[Ranking]) -> None:
        super().__init__(measured)
        self.runs: Counter[int] = Counter()
        self.predicted: dict[int, float] = {}
        self.failed: Counter[int] = Counter()

    def record(self, jobs: Sequence[Job], collapsed: Sequence[tuple[CaseResult, ...]]) -> None:
        builds = self.builds
        rate = _FILES.rates(builds)
        known = all(job.changed_files is not None for job in jobs)
        tails = changed_suffixes(path for job in jobs for path in job.changed_files or ())
        outcome: dict[str, bool] = {}
        for results in collapsed:
            for result in results:
                if result.status is not Status.SKIPPED:
                    failed = result.status.is_failure and not result.flaky
                    outcome[result.key] = outcome.get(result.key, False) or failed
        for key, failed in outcome.items():
            record = builds.records.get(key)
            if record is None:
                continue
            if not known:
                cell = "unknown"
            else:
                cell = "changed" if file_changed(key, record.file, tails) else "unchanged"
            chance = rate(record.state(builds.builds), cell)
            last = len(BINS) - 2
            index = next(i for i in range(last + 1) if chance < BINS[i + 1] or i == last)
            self.runs[index] += 1
            self.predicted[index] = self.predicted.get(index, 0.0) + chance
            self.failed[index] += failed
        super().record(jobs, collapsed)


def run(project: str) -> dict[str, Any]:
    directory = fetch_project(project, CACHE / "rtptorrent")
    engine = Checked(rankings())
    for group in concurrent_groups(iter_jobs(directory)):
        collapsed = [collapse(job.results) for job in group]
        engine.rank(group, collapsed)
        engine.record(group, collapsed)
    result = engine.result()
    result["calibration"] = {
        "runs": dict(engine.runs),
        "predicted": dict(engine.predicted),
        "failed": dict(engine.failed),
    }
    return {"project": project, "source": "rtptorrent", **result}


# Reading the results ------------------------------------------------------------------------------


def difference(
    results: Sequence[Mapping[str, Any]],
    after: str,
    before: str,
    measure: str,
    chosen: Slice,
    resamples: int = RESAMPLES,
    seed: int = 0,
) -> tuple[float, float, float]:
    """`after` minus `before`, paired by trial, mean of per-project means, with a 95% interval.

    The bootstrap draws projects with replacement, then builds with replacement inside each
    drawn project, and every trial of a drawn build comes with it (docs/adr/0038).
    """
    per_project: list[list[list[float]]] = []
    for result in results:
        left = dict(values(result, after, measure, chosen))
        right = dict(values(result, before, measure, chosen))
        builds: dict[int, list[float]] = {}
        for index in left:
            if index in right:
                build = result["trials"]["builds"][index]
                builds.setdefault(build, []).append(left[index] - right[index])
        if builds:
            per_project.append(list(builds.values()))
    if not per_project:
        return math.nan, math.nan, math.nan

    def mean_of(projects: Sequence[Sequence[Sequence[float]]]) -> float:
        return statistics.fmean(
            statistics.fmean(value for build in project for value in build) for project in projects
        )

    observed = mean_of(per_project)
    rng = random.Random(seed)
    drawn = sorted(
        mean_of(
            [
                rng.choices(project, k=len(project))
                for project in rng.choices(per_project, k=len(per_project))
            ]
        )
        for _ in range(resamples)
    )
    return observed, drawn[math.floor(0.025 * resamples)], drawn[math.ceil(0.975 * resamples) - 1]


def criteria(results: Sequence[Mapping[str, Any]], ranking: str) -> dict[str, Any]:
    """The four conditions of docs/adr/0038, for one candidate."""
    time = difference(results, ranking, RANDOM, "red_at", FIRST)
    baseline = difference(results, ranking, LATEST, PRIMARY, EVERY)
    shipped = difference(results, ranking, SHIPPED, PRIMARY, EVERY)
    repeat = difference(results, ranking, SHIPPED, PRIMARY, BEFORE)
    higher = sum(
        1
        for result in results
        if mean([result], ranking, PRIMARY, EVERY) > mean([result], SHIPPED, PRIMARY, EVERY)
    )
    needed = math.ceil(SHARE_OF_PROJECTS * len(results))
    found: dict[str, Any] = {
        "time": time,
        "baseline": baseline,
        "shipped": shipped,
        "higher_on": higher,
        "needed": needed,
        "repeat": repeat,
        "position": difference(results, ranking, RANDOM, "position", FIRST),
    }
    found["sooner_than_random"] = time[2] < 0
    found["above_the_baseline"] = baseline[1] > 0
    found["not_below_shipped"] = shipped[0] >= 0 and higher >= needed
    found["no_repeat_veto"] = not repeat[2] < REPEAT_VETO
    found["passes"] = all(
        found[k]
        for k in ("sooner_than_random", "above_the_baseline", "not_below_shipped", "no_repeat_veto")
    )
    found["worse_than_random_in_position"] = found["position"][1] > 0
    return found


def verdict(results: Sequence[Mapping[str, Any]]) -> str | None:
    passing = [name for name in CANDIDATES if criteria(results, name)["passes"]]
    return max(passing, key=lambda name: mean(results, name, PRIMARY, EVERY)) if passing else None


def predictions(results: Sequence[Mapping[str, Any]]) -> list[tuple[str, bool, str]]:
    """The five predictions of docs/adr/0038, on the training half, as point estimates."""

    def m(name: str, measure: str, chosen: Slice) -> float:
        return mean(results, name, measure, chosen)

    files_repeat = m(WITH_FILES, PRIMARY, BEFORE) - m(FROZEN, PRIMARY, BEFORE)
    files_first = m(WITH_FILES, "red_at", FIRST) - m(FROZEN, "red_at", FIRST)
    two_repeat = m(TWO_STAGE, PRIMARY, BEFORE)
    gain_files = m(WITH_FILES, "red_at", FIRST) - m(SHIPPED, "red_at", FIRST)
    gain_two = m(TWO_STAGE, "red_at", FIRST) - m(SHIPPED, "red_at", FIRST)
    position = m(TWO_STAGE, "position", BEFORE) - m(SHIPPED, "position", BEFORE)
    bins = _calibration(results)
    judged = [(p, o) for n, p, o in bins if max(p * n, o * n) >= 20]
    return [
        (
            "1. The file cell gives back APFDc on repeat failures, and moves first failures by no "
            "more than 0.02 of red at",
            files_repeat > 0 and abs(files_first) <= 0.02,
            f"repeat APFDc {files_repeat:+.4f}, first-failure red at {files_first:+.4f}",
        ),
        (
            "2. Two stages lose no APFDc on repeat failures against `calibrated+runs+file`, and at "
            "most 0.002 against the shipped ranking",
            two_repeat > m(WITH_FILES, PRIMARY, BEFORE)
            and two_repeat - m(SHIPPED, PRIMARY, BEFORE) >= -0.002,
            f"against it {two_repeat - m(WITH_FILES, PRIMARY, BEFORE):+.4f}, against shipped "
            f"{two_repeat - m(SHIPPED, PRIMARY, BEFORE):+.4f}",
        ),
        (
            "3. Two stages keep at least half of `calibrated+runs+file`'s first-failure gain "
            "in red at over the shipped ranking",
            gain_files < 0 and gain_two <= gain_files / 2,
            f"its gain {gain_two:+.4f}, the other's {gain_files:+.4f}",
        ),
        (
            "4. Two stages place repeat failures within 0.02 of the shipped ranking in position",
            abs(position) <= 0.02,
            f"{position:+.4f}",
        ),
        (
            "5. Where at least 20 failures are expected or seen, the observed rate is within a "
            "factor of two of the predicted one",
            bool(judged) and all(0.5 * p <= o <= 2 * p for p, o in judged),
            "; ".join(f"predicted {p:.4f}, observed {o:.4f}" for p, o in judged) or "no bin",
        ),
    ]


def _calibration(results: Sequence[Mapping[str, Any]]) -> list[tuple[int, float, float]]:
    """Pooled over the projects: runs, mean predicted chance and observed rate, per bin."""
    rows = []
    for index in range(len(BINS) - 1):
        runs = sum(r["calibration"]["runs"].get(str(index), 0) for r in results)
        predicted = sum(r["calibration"]["predicted"].get(str(index), 0.0) for r in results)
        failed = sum(r["calibration"]["failed"].get(str(index), 0) for r in results)
        if runs:
            rows.append((runs, predicted / runs, failed / runs))
    return rows


def _f(value: float, signed: bool = False) -> str:
    return "-" if math.isnan(value) else (f"{value:+.3f}" if signed else f"{value:.3f}")


def _i(found: tuple[float, float, float]) -> str:
    return f"{_f(found[0], True)} [{_f(found[1], True)}, {_f(found[2], True)}]"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def page(mode: str, results: Sequence[Mapping[str, Any]]) -> str:
    names = list(results[0]["rankings"])
    lines = [
        f"# Two candidates under the rule of docs/adr/0038: {mode}",
        "",
        "Generated by `python -m benchmarks.confirmation`; protocol in docs/adr/0038. Projects: "
        + ", ".join(r["project"] for r in results)
        + ". Mean of the per-project means, paired by job; 95% intervals resample projects, then "
        "builds inside them. Primary, APFDc and share caught: higher is better. Red at and "
        "position: lower is better.",
        "",
        "| Ranking | primary | against shipped | had failed: APFDc against shipped | first "
        "failures: red at | against random | position | against random | caught within 25% |",
        "|---|---:|---|---|---:|---|---:|---|---:|",
    ]
    for name in names:
        against = "" if name == SHIPPED else _i(difference(results, name, SHIPPED, PRIMARY, EVERY))
        repeat = "" if name == SHIPPED else _i(difference(results, name, SHIPPED, PRIMARY, BEFORE))
        time = "" if name == RANDOM else _i(difference(results, name, RANDOM, "red_at", FIRST))
        place = "" if name == RANDOM else _i(difference(results, name, RANDOM, "position", FIRST))
        lines.append(
            f"| {name} | {_f(mean(results, name, PRIMARY, EVERY))} | {against} | {repeat} | "
            f"{_f(mean(results, name, 'red_at', FIRST))} | {time} | "
            f"{_f(mean(results, name, 'position', FIRST))} | {place} | "
            f"{_f(caught(results, name, 0.25, FIRST))} |"
        )
    lines += [
        "",
        "## The rule of docs/adr/0038",
        "",
        "1. On first failures, red at against random: interval entirely below zero. "
        "2. Primary against `latest-failure`: interval entirely above zero. 3. Primary against "
        f"the shipped ranking: mean at least zero, higher on at least {SHARE_OF_PROJECTS:.0%} of "
        f"the projects. 4. APFDc on jobs that had failed before, against the shipped ranking: "
        f"vetoes only with an interval entirely below {REPEAT_VETO}. Position is published and "
        "does not decide.",
        "",
        "| Candidate | 1. red at vs random | 2. primary vs latest-failure | 3. primary vs shipped, "
        "projects higher | 4. repeat APFDc vs shipped | passes | position vs random |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in CANDIDATES:
        c = criteria(results, name)
        lines.append(
            f"| {name} | {_i(c['time'])} {_yes(c['sooner_than_random'])} | "
            f"{_i(c['baseline'])} {_yes(c['above_the_baseline'])} | "
            f"{_i(c['shipped'])}, {c['higher_on']} of {len(results)} "
            f"{_yes(c['not_below_shipped'])} | {_i(c['repeat'])} {_yes(c['no_repeat_veto'])} | "
            f"**{_yes(c['passes'])}** | {_i(c['position'])} |"
        )
    if mode == "training":
        lines += [
            "",
            "The training half does not decide: the rule is applied here for reference only.",
            "",
            "## Predictions written before the replay",
            "",
            "| Prediction | held | measured |",
            "|---|---|---|",
            *(
                f"| {text} | {_yes(held)} | {measured} |"
                for text, held, measured in predictions(results)
            ),
            "",
            "## Calibration of `calibrated+runs+file`, pooled over the projects",
            "",
            "| Predicted chance | runs | mean predicted | observed |",
            "|---|---:|---:|---:|",
        ]
        labels = [f"{BINS[i]:g} to {BINS[i + 1]:g}" for i in range(len(BINS) - 1)]
        for index in range(len(BINS) - 1):
            runs = sum(r["calibration"]["runs"].get(str(index), 0) for r in results)
            if not runs:
                continue
            predicted = sum(r["calibration"]["predicted"].get(str(index), 0.0) for r in results)
            failed = sum(r["calibration"]["failed"].get(str(index), 0) for r in results)
            lines.append(
                f"| {labels[index]} | {runs} | {predicted / runs:.4f} | {failed / runs:.4f} |"
            )
    else:
        chosen = verdict(results)
        if chosen is None:
            lines += ["", "**Verdict: DO_NOT_SHIP.** No candidate meets the four conditions."]
        else:
            worse = criteria(results, chosen)["worse_than_random_in_position"]
            lines += [
                "",
                f"**Verdict: SHIP proposal, for {chosen}.** It meets the four conditions on the "
                "held-out projects; the release is the maintainer's decision (docs/adr/0038)."
                + (
                    " **It is worse than random in position on first failures**, which the README "
                    "must say."
                    if worse
                    else ""
                ),
            ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.confirmation")
    parser.add_argument("mode", choices=sorted(MODES))
    parser.add_argument("--held-out", action="store_true", help="required by the held-out mode")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--from-cache", action="store_true")
    args = parser.parse_args(argv)
    if (args.mode == "held-out") != args.held_out:
        parser.error("--held-out goes with the held-out mode, and only with it (docs/adr/0016)")
    out = RESULTS / args.mode
    if not args.from_cache:
        if args.held_out:
            try:
                record_peek(
                    "benchmarks.confirmation held-out",
                    MODES["held-out"],
                    ", ".join(ranking.name for ranking in rankings()),
                    __version__,
                )
            except NotFrozen as exc:
                parser.error(str(exc))
        out.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for result in pool.map(run, MODES[args.mode]):
                result["testhunch"] = {"version": __version__}
                slug = result["project"].replace("/", "@")
                (out / f"{slug}.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
                sys.stdout.write(f"{result['project']}: {result['counts']}\n")
    stored = sorted(out.glob("*.json"))
    if not stored:
        parser.error(f"no stored results in {out}")
    results = [json.loads(path.read_text(encoding="utf-8")) for path in stored]
    (RESULTS / f"{args.mode}.md").write_bytes(page(args.mode, results).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
