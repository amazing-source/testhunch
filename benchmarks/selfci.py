"""Measure testhunch on its own CI (docs/adr/0028).

    uv run python -m benchmarks.selfci collect     # download every main build's JUnit report
    uv run python -m benchmarks.selfci evaluate    # replay them and write the page

The history the real CI keeps lives in the Actions cache, which cannot be downloaded. This rebuilds
an equivalent one from the `reports-python-3.14` artifact of every build of `main`, ranking before
each ingest exactly as the Action does. Artifacts expire, so `collect` keeps what it downloads and
the page records the window it covers.

This reads no held-out project and appends no ledger row: the subject is this repository's own CI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from testhunch.gitinfo import changed_files
from testhunch.junit import parse_reports
from testhunch.models import FileChange, RankedTest, RunInput
from testhunch.prioritize import rank
from testhunch.shadow import evaluate, time_budget_size
from testhunch.store import SqlStore, open_store

DEFAULT_CACHE = Path(".benchmark-cache") / "selfci"
DEFAULT_OUT = Path("benchmarks") / "results" / "self.md"
REPOSITORY = "amazing-source/testhunch"
ARTIFACT = "reports-python-3.14"
WORKFLOW = "ci.yml"

# The budget the page reports in detail. The others are still evaluated; this is the one the prose
# talks about, because it is the one the Action's summary shows first.
HEADLINE = 0.25

# How many recent builds the budget table describes. A budget is about what a build would skip
# today, not about a history: the suite has changed shape several times over these builds.
RECENT = 10


@dataclass(frozen=True, slots=True)
class Build:
    """One build of main: the run that produced it, and the report it left behind."""

    run_id: int
    commit: str
    report: Path


@dataclass(frozen=True, slots=True)
class Cut:
    """What a time budget would have run for one build, measured on its own ranking."""

    commit: str
    ranked: int
    kept: int
    allowed_ms: float
    spent_ms: float
    total_ms: float

    @property
    def used(self) -> float:
        """The share of the allowed time the cut actually spends. 1.0 means the budget is full."""
        return self.spent_ms / self.allowed_ms if self.allowed_ms else 0.0


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def main_builds(limit: int) -> list[dict[str, str]]:
    """Every run of the CI workflow on main, oldest first."""
    out = gh(
        "run",
        "list",
        "--workflow",
        WORKFLOW,
        "--branch",
        "main",
        "--limit",
        str(limit),
        "--json",
        "databaseId,headSha,createdAt,conclusion",
    )
    runs = json.loads(out)
    return sorted(runs, key=lambda run: str(run["createdAt"]))


def collect(cache: Path, limit: int) -> int:
    """Download the report of every build of main that still has one."""
    cache.mkdir(parents=True, exist_ok=True)
    kept = gone = 0
    for run in main_builds(limit):
        folder = (
            cache / f"{run['createdAt'].replace(':', '-')}_{run['headSha'][:8]}_{run['databaseId']}"
        )
        if (folder / "junit.xml").exists():
            kept += 1
            continue
        folder.mkdir(parents=True, exist_ok=True)
        downloaded = subprocess.run(
            ["gh", "run", "download", str(run["databaseId"]), "-n", ARTIFACT, "-D", str(folder)],
            capture_output=True,
            text=True,
            check=False,
        )
        if downloaded.returncode == 0 and (folder / "junit.xml").exists():
            kept += 1
        else:
            # Expired, or a build that failed before the tests ran. Neither is an error here.
            gone += 1
            folder.rmdir()
    print(f"{kept} builds with a report, {gone} without")
    return 0


def builds(cache: Path) -> list[Build]:
    found = []
    for folder in sorted(cache.iterdir()):
        report = folder / "junit.xml"
        if not report.exists():
            continue
        _created, commit, run_id = folder.name.rsplit("_", 2)
        found.append(Build(run_id=int(run_id), commit=commit, report=report))
    return found


def full_sha(commit: str) -> str | None:
    """The whole commit hash, or None if this checkout does not have the commit.

    The ranking is seeded with the commit, which breaks ties between equal scores, so an
    abbreviated hash would rank differently from what CI actually ran (docs/adr/0009).
    """
    found = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.strip() if found.returncode == 0 else None


def replay(store: SqlStore, found: Sequence[Build], repo: str) -> list[Cut]:
    """Rank before each build from the history before it, then record it, as the Action does."""
    cuts = []
    for build in found:
        changes: tuple[FileChange, ...] = ()
        paths: list[str] = []
        sha = full_sha(build.commit)
        if sha is not None:
            changes = tuple(changed_files(f"{sha}~1", sha))
            paths = [change.path for change in changes]

        ranked = rank(store.history(repo), paths, seed=sha or build.commit)
        if ranked:
            cuts.append(_cut(build.commit, ranked))
            # Recorded before the run is ingested, exactly as shadow mode does in CI (ADR 0006):
            # the ranking must not be able to have seen the results it is judged against.
            last_run_id = store.latest_run_id(repo)
            if last_run_id is not None:
                store.record_prediction(repo, sha or build.commit, ranked, last_run_id=last_run_id)

        results, digest = parse_reports([build.report.read_bytes()])
        store.ingest(
            RunInput(
                repo=repo,
                commit_sha=sha or build.commit,
                report_digest=digest,
                results=results,
                branch="main",
                changes=changes,
            )
        )
    return cuts


def _cut(commit: str, ranked: Sequence[RankedTest]) -> Cut:
    expected = [test.expected_ms for test in ranked]
    total = sum(expected)
    kept = time_budget_size(HEADLINE, expected)
    return Cut(
        commit=commit,
        ranked=len(ranked),
        kept=kept,
        allowed_ms=HEADLINE * total,
        spent_ms=sum(expected[:kept]),
        total_ms=total,
    )


TEMPLATE = """# testhunch on testhunch

Rebuilt from the `{artifact}` artifact of every build of `main`, ranking before each
ingest exactly as the Action does. The history the real CI keeps lives in the Actions
cache, which cannot be downloaded, so this is a reconstruction: `python -m
benchmarks.selfci` makes it again, for as long as the artifacts have not expired.

**{builds} builds**, `{first}` to `{last}`.

## It cannot measure its own ranking, and that is the finding

**{failing} of those builds had a failing test.** Shadow mode compares a ranking recorded
before a build against what the build then did; with no build that went red there is
nothing to compare, and every budget reports nothing caught because nothing was there to
catch.

This is not a measurement problem to work around. A repository whose suite has never
failed is a repository where test prioritisation cannot be validated, and that belongs on
the page whose subject is how well testhunch works. It is worse than neutral: the first
failure here would land in the regime where the ranking is worse than random
([ADR 0018](../../docs/adr/0018-first-failures-are-a-guardrail-not-an-average.md)),
because no test has ever failed, so nothing yet carries the signal the ranking reads.

## What a budget does here

Over the {recent} most recent builds, at a budget of {headline:.0%} of the expected test
time:

| Build | Tests ranked | Tests kept | Test time run | Budget used |
|---|---:|---:|---:|---:|
{recent_rows}

The saving is real and large, and **none of it comes from prediction**. One test dominates
this suite's time, so the budget's whole effect is to leave that one test out. The
duration divisor does all the work, and anyone could have the same result by running that
test separately.

## The prefix rule truncates, and it is visible here

A time budget takes the longest prefix of the ranking that fits and stops at the first
test too expensive to fit
([ADR 0017](../../docs/adr/0017-a-budget-is-a-share-of-the-test-time.md)). When the slow
test's own file changes, the ranking lifts it near the top, it does not fit, and
**everything below it is cut with it**.

It happened in **{truncated} of {cuts} builds**, counting every build whose cut spends
less than half of what its budget allows:

| Build | Tests kept | Test time run | Budget used |
|---|---:|---:|---:|
{truncated_rows}

The rule is deliberate: the order is what the ranking promises, and packing the budget
better would run tests the ranking placed below ones it did not. But a build that spends
{worst:.0%} of its budget is not honouring an order, it is losing the budget. Whether to
keep filling after a test that does not fit changes the published budget tables, so it is
a decision to measure and record, not a quiet fix.
"""


def markdown(store: SqlStore, repo: str, found: Sequence[Build], cuts: Sequence[Cut]) -> str:
    points = evaluate(store.shadow_runs(repo, len(found) or 1))
    recent = list(cuts)[-RECENT:]
    truncated = [cut for cut in cuts if cut.used < 0.5]
    return TEMPLATE.format(
        artifact=ARTIFACT,
        builds=len(found),
        first=found[0].commit,
        last=found[-1].commit,
        failing=points[0].failing_runs if points else 0,
        recent=len(recent),
        headline=HEADLINE,
        recent_rows="\n".join(
            f"| `{cut.commit}` | {cut.ranked} | {cut.kept} "
            f"| {cut.spent_ms / 1000:.1f} s of {cut.total_ms / 1000:.1f} s | {cut.used:.0%} |"
            for cut in recent
        ),
        truncated=len(truncated),
        cuts=len(cuts),
        worst=min((cut.used for cut in cuts), default=0.0),
        truncated_rows="\n".join(
            f"| `{cut.commit}` | {cut.kept} of {cut.ranked} "
            f"| {cut.spent_ms / 1000:.1f} s of {cut.allowed_ms / 1000:.1f} s allowed "
            f"| {cut.used:.0%} |"
            for cut in truncated
        )
        or "| none | | | |",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.selfci")
    parser.add_argument("action", choices=("collect", "evaluate"))
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=200, help="how many builds to look back over")
    parser.add_argument("--repo", default=REPOSITORY)
    args = parser.parse_args(argv)

    if args.action == "collect":
        return collect(args.cache, args.limit)

    found = builds(args.cache)
    if not found:
        raise SystemExit(f"no reports in {args.cache}: run `collect` first")

    database = args.cache / "history.db"
    database.unlink(missing_ok=True)
    store = open_store(f"sqlite:///{database.as_posix()}")
    store.migrate()
    cuts = replay(store, found, args.repo)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown(store, args.repo, found, cuts), encoding="utf-8")
    print(f"wrote {args.out} from {len(found)} builds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
