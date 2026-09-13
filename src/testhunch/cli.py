"""The `testhunch` command."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from testhunch import __version__
from testhunch.gitinfo import GitError, changed_files, current_branch, detect_repo, rev_parse
from testhunch.junit import ReportError, parse_reports
from testhunch.models import RankedTest, RunInput
from testhunch.prioritize import rank
from testhunch.runners import (
    go_skip,
    nextest_filterset,
    parse_go_test_list,
    parse_vitest_list,
    surefire_exclusions,
    vitest_skip,
)
from testhunch.shadow import ShadowPoint, budget_size, evaluate, is_learning_run
from testhunch.store import DEFAULT_DATABASE_URL, SqlStore, StoreError, open_store


def run() -> None:
    sys.exit(main())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code: int = args.handler(args)
    except (ReportError, GitError, StoreError, OSError) as exc:
        print(f"testhunch: error: {exc}", file=sys.stderr)
        return 2
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testhunch",
        description="Learn from CI history which tests a change is likely to break.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--db",
        default=os.environ.get("TESTHUNCH_DATABASE_URL", DEFAULT_DATABASE_URL),
        help="database URL (env TESTHUNCH_DATABASE_URL, default %(default)s)",
    )
    common.add_argument("--repo", help="repository name (default: from GITHUB_REPOSITORY or git)")

    commands = parser.add_subparsers(dest="command", required=True)

    migrate = commands.add_parser("migrate", parents=[common], help="create or upgrade the schema")
    migrate.set_defaults(handler=_migrate)

    ingest = commands.add_parser("ingest", parents=[common], help="record JUnit XML reports")
    ingest.add_argument("reports", nargs="+", help="JUnit XML files or glob patterns")
    ingest.add_argument("--commit", default="HEAD", help="commit that was tested (default HEAD)")
    ingest.add_argument("--branch", help="branch that was tested (default: detected)")
    ingest.add_argument("--base", help="also record files changed since this ref, e.g. origin/main")
    ingest.set_defaults(handler=_ingest)

    report = commands.add_parser("report", parents=[common], help="flaky, slow and failing tests")
    report.add_argument("--last", type=_positive, default=50, help="runs to look back over")
    report.add_argument("--limit", type=_positive, default=10, help="rows per section")
    report.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    report.set_defaults(handler=_report)

    ranking = argparse.ArgumentParser(add_help=False)
    changed = ranking.add_mutually_exclusive_group()
    changed.add_argument("--base", help="rank for the files changed since this ref")
    changed.add_argument("--changed", nargs="+", default=[], help="rank for these changed paths")
    ranking.add_argument("--last", type=_positive, default=50, help="runs to look back over")

    prioritize = commands.add_parser(
        "prioritize", parents=[common, ranking], help="order tests by how likely they are to fail"
    )
    prioritize.add_argument("--limit", type=_positive, help="show only the top N tests")
    prioritize.add_argument(
        "--format", choices=["text", "json", "keys", "markdown"], default="text"
    )
    prioritize.add_argument(
        "--record",
        action="store_true",
        help="store the full ranking for the commit about to be tested, for `testhunch shadow`",
    )
    prioritize.add_argument(
        "--commit", default="HEAD", help="with --record: the commit about to be tested (HEAD)"
    )
    prioritize.set_defaults(handler=_prioritize)

    select = commands.add_parser(
        "select",
        parents=[common, ranking],
        help="list the known tests a test budget leaves out, for the test runner to skip",
    )
    select.add_argument(
        "--budget",
        type=parse_budget,
        required=True,
        help="share of the known tests to run, top-ranked first, e.g. 25%%",
    )
    select.add_argument(
        "--runner",
        choices=["pytest", "go", "surefire", "nextest", "vitest"],
        required=True,
        help="pytest: keys for `pytest -p testhunch.pytest_plugin --testhunch-skip=FILE`; "
        'go: a pattern for `go test ./... -skip "$(testhunch select ...)"`; '
        'surefire: a value for `mvn test "-Dtest=$(testhunch select ...)"`; '
        'nextest: an expression for `cargo nextest run -E "$(testhunch select ...)"`; '
        'vitest: a pattern for `vitest run -t "$(testhunch select ...)"`',
    )
    select.add_argument(
        "--vitest-list",
        metavar="FILE",
        help="with --runner vitest: the output of `vitest list --json --no-static-parse`",
    )
    select.add_argument(
        "--go-test-list",
        metavar="FILE",
        help="with --runner go: the output of `go test -list '.*' ./...` for the code under test",
    )
    select.add_argument(
        "--learning-runs",
        type=parse_share,
        default=0.25,
        help="share of builds that run every test and record the ranking for `testhunch shadow` "
        "(default 25%%; 0%% turns learning runs off)",
    )
    select.add_argument("--commit", default="HEAD", help="the commit about to be tested (HEAD)")
    select.set_defaults(handler=_select)

    shadow = commands.add_parser(
        "shadow", parents=[common], help="what skipping low-ranked tests would have missed"
    )
    shadow.add_argument(
        "--last", type=_positive, default=50, help="recent runs with a recorded ranking to use"
    )
    shadow.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    shadow.set_defaults(handler=_shadow)

    return parser


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_share(value: str) -> float:
    """`25%` or `0.25`, from 0% to 100%."""
    try:
        fraction = float(value.removesuffix("%")) / 100 if value.endswith("%") else float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a share, such as 25% or 0.25") from None
    if not 0 <= fraction <= 1:  # also refuses nan
        raise argparse.ArgumentTypeError(f"{value!r} must be from 0% to 100%")
    return fraction


def parse_budget(value: str) -> float:
    """`25%` or `0.25`: the share of the known tests to run, more than 0%."""
    fraction = parse_share(value)
    if fraction == 0:
        raise argparse.ArgumentTypeError(f"{value!r} would run no known test: use more than 0%")
    return fraction


def _store(args: argparse.Namespace) -> SqlStore:
    # Migrating is idempotent and cheap, and it means a fresh database never fails with
    # "no such table" just because the first command was `report` rather than `ingest`.
    store = open_store(args.db)
    store.migrate()
    return store


def _repo(args: argparse.Namespace) -> str:
    return str(args.repo) if args.repo else detect_repo()


def _migrate(args: argparse.Namespace) -> int:
    applied = open_store(args.db).migrate()
    print(f"applied migrations: {', '.join(map(str, applied))}" if applied else "schema up to date")
    return 0


def _expand(patterns: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern, recursive=True)) if glob.has_magic(pattern) else []
        if glob.has_magic(pattern) and not matches:
            raise ReportError(f"no files match {pattern!r}")
        paths.extend(Path(match) for match in matches or [pattern])
    return paths


def _ingest(args: argparse.Namespace) -> int:
    paths = _expand(args.reports)
    results, digest = parse_reports(path.read_bytes() for path in paths)
    commit = rev_parse(args.commit)
    changes = changed_files(args.base, commit) if args.base else ()
    store = _store(args)
    outcome = store.ingest(
        RunInput(
            repo=_repo(args),
            commit_sha=commit,
            report_digest=digest,
            results=results,
            branch=args.branch or current_branch(),
            base_sha=rev_parse(args.base) if args.base else None,
            changes=changes,
        )
    )
    if outcome.created:
        counts = f"{outcome.results} results from {len(paths)} report(s)"
        print(f"ingested {counts} as run {outcome.run_id}")
    else:
        print(f"already ingested as run {outcome.run_id}; nothing changed")
    return 0


def _report(args: argparse.Namespace) -> int:
    store, repo = _store(args), _repo(args)
    flaky = store.flaky_tests(repo, args.limit)
    slowest = store.slowest_tests(repo, args.last, args.limit)
    failing = store.failing_tests(repo, args.last, args.limit)

    if args.format == "json":
        payload = {
            "repo": repo,
            "flaky": [asdict(t) for t in flaky],
            "slowest": [asdict(t) for t in slowest],
            "failing": [asdict(t) for t in failing],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.format == "markdown":
        print(f"### testhunch report for {repo} ({store.run_count(repo)} runs recorded)")
        _print_markdown_table(
            "Flaky (passed and failed on the same commit)",
            ("Commits", "Test"),
            [(str(t.flaky_commits), markdown_code(t.key)) for t in flaky],
        )
        _print_markdown_table(
            f"Slowest (average over the last {args.last} runs)",
            ("Average", "Test"),
            [(f"{t.avg_ms:.0f} ms", markdown_code(t.key)) for t in slowest],
        )
        _print_markdown_table(
            f"Failing (last {args.last} runs)",
            ("Failures", "Test"),
            [(f"{t.failures} / {t.executions}", markdown_code(t.key)) for t in failing],
        )
        return 0

    print(f"testhunch report for {repo} ({store.run_count(repo)} runs recorded)")
    print("\nFlaky (passed and failed on the same commit):")
    _print_rows([f"{t.flaky_commits:>4} commit(s)  {t.key}" for t in flaky])
    print(f"\nSlowest (average over the last {args.last} runs):")
    _print_rows([f"{t.avg_ms:>9.0f} ms  {t.key}" for t in slowest])
    print(f"\nFailing (last {args.last} runs):")
    _print_rows([f"{t.failures:>4} / {t.executions:<4} {t.key}" for t in failing])
    return 0


def _print_rows(rows: Sequence[str]) -> None:
    print("\n".join(f"  {row}" for row in rows) if rows else "  none")


def _changed_paths(args: argparse.Namespace) -> list[str]:
    return [c.path for c in changed_files(args.base)] if args.base else list(args.changed)


def _select(args: argparse.Namespace) -> int:
    store, repo = _store(args), _repo(args)
    history = store.history(repo, args.last)
    if args.runner == "go" and not args.go_test_list:
        print(
            "testhunch: error: --runner go needs --go-test-list, the output of "
            "`go test -list '.*' ./...`: -skip matches test names in every package",
            file=sys.stderr,
        )
        return 2
    if args.runner == "vitest" and not args.vitest_list:
        print(
            "testhunch: error: --runner vitest needs --vitest-list, the output of "
            "`vitest list --json --no-static-parse`: -t matches full names in every file",
            file=sys.stderr,
        )
        return 2
    if not history:
        print(f"no history for {repo} yet: nothing is left out", file=sys.stderr)
        return 0
    changed = _changed_paths(args)
    ranked = rank(history, changed)

    if is_learning_run(repo, rev_parse(args.commit), args.learning_runs):
        # Every test runs, so this build's results can measure the ranking (docs/adr/0009).
        print(
            f"learning run (about {args.learning_runs:.0%} of builds): nothing is left out",
            file=sys.stderr,
        )
        _record(args, store, repo, ranked)
        return 0

    # Tests are left out, so the ranking is not recorded: shadow mode needs full runs (ADR 0007).
    cutoff = budget_size(args.budget, len(ranked))
    below = [r.key for r in ranked[cutoff:]]
    unreachable = 0
    if args.runner == "go":
        skip = go_skip(
            below,
            [r.key for r in ranked[:cutoff]],
            parse_go_test_list(Path(args.go_test_list).read_text(encoding="utf-8")),
            changed,
        )
        # No line ending: on Windows it would be \r\n, and "$(...)" only strips the \n.
        sys.stdout.write(skip.pattern)
        left_out, unreachable = len(skip.left_out), len(below) - len(skip.left_out)
    elif args.runner == "surefire":
        exclusions = surefire_exclusions(below, [r.key for r in ranked[:cutoff]], changed)
        sys.stdout.write(exclusions.value)  # no line ending either, for the same reason
        left_out = len(exclusions.left_out)
        unreachable = len(below) - left_out
    elif args.runner == "nextest":
        suites = {case.key: case.suite for case in history}
        filterset = nextest_filterset(below, suites)
        sys.stdout.write(filterset.expression)  # no line ending either, for the same reason
        left_out = len(filterset.left_out)
        unreachable = len(below) - left_out
    elif args.runner == "vitest":
        try:
            listed = parse_vitest_list(Path(args.vitest_list).read_text(encoding="utf-8"))
        except (ValueError, KeyError) as exc:
            print(f"testhunch: error: cannot read {args.vitest_list}: {exc}", file=sys.stderr)
            return 2
        vitest = vitest_skip(below, listed)
        sys.stdout.write(vitest.pattern)  # no line ending either, for the same reason
        left_out = len(vitest.left_out)
        unreachable = len(below) - left_out
    else:
        if below:
            print("\n".join(below))
        left_out = len(below)
    print(
        f"leaving out {left_out} of {len(ranked)} known tests: the top {args.budget:.0%} run, "
        "and so does every test testhunch has no result for",
        file=sys.stderr,
    )
    if unreachable:
        print(
            f"{unreachable} more tests below the budget run anyway: {args.runner} cannot leave "
            "them out without also leaving out tests that must run (docs/adr/0007)",
            file=sys.stderr,
        )
    return 0


def _record(args: argparse.Namespace, store: SqlStore, repo: str, ranked: list[RankedTest]) -> None:
    commit = rev_parse(args.commit)
    # Read after the history the ranking came from, so it can only be newer than what the ranking
    # saw: at worst a run is left out of the shadow report, never judged by a ranking that saw it.
    last_run_id = store.latest_run_id(repo)
    if last_run_id is None:  # pragma: no cover - the history was not empty a moment ago
        return
    prediction_id = store.record_prediction(
        repo,
        commit,
        ranked,
        last_run_id=last_run_id,
        base_sha=rev_parse(args.base) if args.base else None,
    )
    # stderr, so that stdout stays exactly the ranking in the requested format.
    print(
        f"recorded the ranking of {len(ranked)} tests for {commit[:12]} "
        f"(ranking {prediction_id}); `testhunch shadow` compares it with the results",
        file=sys.stderr,
    )


def _shadow(args: argparse.Namespace) -> int:
    store, repo = _store(args), _repo(args)
    runs = store.shadow_runs(repo, args.last)
    points = evaluate(runs)
    failing_runs = points[0].failing_runs if points else 0

    if args.format == "json":
        payload = {
            "repo": repo,
            "runs": len(runs),
            "failing_runs": failing_runs,
            "budgets": [asdict(p) for p in points],
        }
        print(json.dumps(payload, indent=2))
        return 0

    title = f"testhunch shadow report for {repo}"
    if not runs:
        advice = "run `testhunch prioritize --record` before the tests and `testhunch ingest` after"
        if args.format == "markdown":
            print(f"### {title}\n\nNo run with a recorded ranking yet: {advice}.")
        else:
            print(f"{title}: no run with a recorded ranking yet; {advice}")
        return 0

    plural = "" if len(runs) == 1 else "s"
    counts = f"{len(runs)} run{plural} with a recorded ranking, {failing_runs} with failures"
    unconfirmed = _unconfirmed_note(points[0])
    if args.format == "markdown":
        print(f"### {title}\n\n{counts}.")
        _print_markdown_table(
            None,
            (
                "Budget",
                "Failing runs caught",
                "Failures caught",
                "Confirmed failures caught",
                "Tests run",
                "Test time",
            ),
            [
                (
                    f"{p.fraction:.0%}",
                    f"{p.caught_runs} of {p.failing_runs}",
                    f"{p.caught_failures} of {p.failures}",
                    f"{p.caught_confirmed_failures} of {p.confirmed_failures}",
                    f"{p.tests_run} of {p.tests_total} ({_percent(p.tests_run, p.tests_total)})",
                    _time_share(p),
                )
                for p in points
            ],
            numeric_columns=6,
        )
        if unconfirmed:
            print(f"\n{unconfirmed}")
        return 0

    print(f"{title}\n{counts}\n")
    for p in points:
        caught = (
            f"caught {p.caught_runs} of {p.failing_runs} failing runs, "
            f"{p.caught_failures} of {p.failures} failures"
            if p.failing_runs
            else "no failing run to catch"
        )
        if p.confirmed_failures:
            caught += (
                f" (confirmed by retries: {p.caught_confirmed_runs} of "
                f"{p.confirmed_failing_runs} runs, {p.caught_confirmed_failures} of "
                f"{p.confirmed_failures} failures)"
            )
        time = f"{_time_share(p)} of test time" if p.time_total_ms else "test time unknown"
        print(
            f"  top {p.fraction:.0%} of ranked tests: {caught}; "
            f"ran {p.tests_run} of {p.tests_total} tests ({_percent(p.tests_run, p.tests_total)}) "
            f"and {time}"
        )
    if unconfirmed:
        print(f"\n{unconfirmed}")
    return 0


def _unconfirmed_note(point: ShadowPoint) -> str | None:
    """Failures do not depend on the budget, so any point tells how many were confirmed."""
    unconfirmed = point.failures - point.confirmed_failures
    if not unconfirmed:
        return None
    return (
        f"{unconfirmed} of {point.failures} failures ran only once, so some may be flaky and the "
        "counts above can look better than the truth. Turn retries on in the test runner to "
        "confirm failures (docs/adr/0008)."
    )


def _percent(part: int, total: int) -> str:
    return f"{100 * part / total:.0f}%" if total else "n/a"


def _time_share(point: ShadowPoint) -> str:
    """Share of the known test time run, e.g. "25% of 1200 ms"."""
    if not point.time_total_ms:
        return "unknown"
    return f"{_percent(point.time_run_ms, point.time_total_ms)} of {point.time_total_ms} ms"


def _print_markdown_table(
    title: str | None,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    numeric_columns: int = 1,
) -> None:
    print(f"\n**{title}**\n" if title else "")
    if not rows:
        print("None.")
        return
    print("| " + " | ".join(header) + " |")
    print(
        "|" + "|".join("---:" if i < numeric_columns else "---" for i in range(len(header))) + "|"
    )
    for row in rows:
        print("| " + " | ".join(row) + " |")


def markdown_code(text: str) -> str:
    """`text` as a code span that stays inside one Markdown table cell."""
    # The fence must be longer than any run of backticks inside, and padded when there is one.
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence, pad = "`" * (longest + 1), " " if longest else ""
    return f"{fence}{pad}{_markdown_cell(text)}{pad}{fence}"


def _markdown_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _prioritize(args: argparse.Namespace) -> int:
    store, repo = _store(args), _repo(args)
    history = store.history(repo, args.last)
    if not history:
        print(
            f"no history for {repo} yet: run `testhunch ingest` after your test job first",
            file=sys.stderr,
        )
        # Machine-readable formats still get well-formed, empty output.
        if args.format == "json":
            print("[]")
        elif args.format == "markdown":
            print(f"### testhunch ranking for {repo}\n")
            print("No history yet: run `testhunch ingest` after your test job first.")
        return 0
    paths = _changed_paths(args)
    ranked = rank(history, paths)
    total = len(ranked)
    if args.record:
        _record(args, store, repo, ranked)
    if args.limit:
        ranked = ranked[: args.limit]

    if args.format == "json":
        print(json.dumps([asdict(r) for r in ranked], indent=2))
    elif args.format == "keys":
        print("\n".join(r.key for r in ranked))
    elif args.format == "markdown":
        print(f"### testhunch ranking for {repo}\n")
        print(f"Top {len(ranked)} of {total} tests for {len(paths)} changed file(s).")
        rows = [
            (
                str(position),
                f"{r.score:.3f}",
                markdown_code(r.key),
                _markdown_cell("; ".join(r.reasons) if r.reasons else "no signal"),
            )
            for position, r in enumerate(ranked, start=1)
        ]
        _print_markdown_table(None, ("#", "Score", "Test", "Why"), rows, numeric_columns=2)
    else:
        for position, r in enumerate(ranked, start=1):
            why = "; ".join(r.reasons) if r.reasons else "no signal"
            print(f"{position:>4}. {r.score:6.3f}  {r.key}  ({why})")
    return 0
