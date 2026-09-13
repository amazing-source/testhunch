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
from testhunch.shadow import ShadowPoint, evaluate
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

    prioritize = commands.add_parser(
        "prioritize", parents=[common], help="order tests by how likely they are to fail"
    )
    changed = prioritize.add_mutually_exclusive_group()
    changed.add_argument("--base", help="rank for the files changed since this ref")
    changed.add_argument("--changed", nargs="+", default=[], help="rank for these changed paths")
    prioritize.add_argument("--last", type=_positive, default=50, help="runs to look back over")
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
    if args.format == "markdown":
        print(f"### {title}\n\n{counts}.")
        _print_markdown_table(
            None,
            ("Budget", "Failing runs caught", "Failures caught", "Tests run", "Test time"),
            [
                (
                    f"{p.fraction:.0%}",
                    f"{p.caught_runs} of {p.failing_runs}",
                    f"{p.caught_failures} of {p.failures}",
                    f"{p.tests_run} of {p.tests_total} ({_percent(p.tests_run, p.tests_total)})",
                    _time_share(p),
                )
                for p in points
            ],
            numeric_columns=5,
        )
        return 0

    print(f"{title}\n{counts}\n")
    for p in points:
        caught = (
            f"caught {p.caught_runs} of {p.failing_runs} failing runs, "
            f"{p.caught_failures} of {p.failures} failures"
            if p.failing_runs
            else "no failing run to catch"
        )
        time = f"{_time_share(p)} of test time" if p.time_total_ms else "test time unknown"
        print(
            f"  top {p.fraction:.0%} of ranked tests: {caught}; "
            f"ran {p.tests_run} of {p.tests_total} tests ({_percent(p.tests_run, p.tests_total)}) "
            f"and {time}"
        )
    return 0


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
    paths = [c.path for c in changed_files(args.base)] if args.base else list(args.changed)
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
