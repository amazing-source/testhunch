"""Collect and evaluate the harness projects (docs/adr/0011).

uv run python -m benchmarks.harness collect pallets/click
uv run python -m benchmarks.harness evaluate pallets/click
uv run python -m benchmarks.harness evaluate fastapi/fastapi --held-out  # frozen versions only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from benchmarks.harness.collect import (
    PROJECTS,
    NotBuiltInARow,
    build_image,
    clone,
    collect,
    read_run,
    window,
)
from benchmarks.harness.evaluate import markdown, run_project
from benchmarks.heldout import NotFrozen, record_peek
from benchmarks.split import HARNESS_HELD_OUT
from testhunch import __version__

DEFAULT_CACHE = Path(".benchmark-cache") / "harness"
DEFAULT_OUT = Path("benchmarks") / "results" / "harness"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.harness")
    parser.add_argument("action", choices=("collect", "evaluate"))
    parser.add_argument("projects", nargs="+", choices=sorted(PROJECTS))
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, help="collect at most this many new commits")
    parser.add_argument(
        "--allow-not-built",
        action="store_true",
        help="keep collecting after several commits in a row were not built",
    )
    parser.add_argument(
        "--held-out",
        action="store_true",
        help="allow evaluating held-out projects: only for versions frozen before the replay "
        "(docs/adr/0013); collecting them ranks nothing and needs no flag",
    )
    args = parser.parse_args(argv)
    held_out = [name for name in args.projects if name in HARNESS_HELD_OUT]
    if args.action == "evaluate" and held_out and not args.held_out:
        parser.error(
            f"held out, evaluated only with --held-out (docs/adr/0013): {', '.join(held_out)}"
        )
    if args.action == "evaluate" and held_out:
        # Written before the replay, from a frozen commit, so the look cannot be hidden (ADR 0016).
        try:
            record_peek(
                "benchmarks.harness evaluate", held_out, "the product's ranking", __version__
            )
        except NotFrozen as exc:
            parser.error(str(exc))

    for name in args.projects:
        project = PROJECTS[name]
        repository = clone(project, args.cache)
        shas = window(repository, project.end, project.window)
        runs_directory = args.cache / project.slug / "runs"
        if args.action == "collect":
            image_id = build_image(project)
            try:
                collect(
                    project,
                    repository,
                    shas,
                    runs_directory,
                    image_id,
                    args.limit,
                    args.allow_not_built,
                )
            except NotBuiltInARow as stop:
                sys.stderr.write(f"{stop}\n")
                return 1
        else:
            runs = [
                read_run(runs_directory / sha)
                for sha in shas
                if (runs_directory / sha / "run.json").exists()
            ]
            result = run_project(project, repository, runs)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f"{project.slug}.json").write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
            (args.out / f"{project.slug}.md").write_text(markdown(result), encoding="utf-8")
            sys.stdout.write(markdown(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
