"""Collect and evaluate the harness projects (docs/adr/0011).

uv run python -m benchmarks.harness collect pallets/click
uv run python -m benchmarks.harness evaluate pallets/click
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from benchmarks.harness.collect import (
    PROJECTS,
    build_image,
    clone,
    read_run,
    run_commit,
    window,
)
from benchmarks.harness.evaluate import markdown, run_project

DEFAULT_CACHE = Path(".benchmark-cache") / "harness"
DEFAULT_OUT = Path("benchmarks") / "results" / "harness"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.harness")
    parser.add_argument("action", choices=("collect", "evaluate"))
    parser.add_argument("projects", nargs="+", choices=sorted(PROJECTS))
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, help="collect at most this many new commits")
    args = parser.parse_args(argv)

    for name in args.projects:
        project = PROJECTS[name]
        repository = clone(project, args.cache)
        shas = window(repository, project.end, project.window)
        runs_directory = args.cache / project.slug / "runs"
        if args.action == "collect":
            image_id = build_image(project)
            new = 0
            for number, sha in enumerate(shas, start=1):
                if args.limit is not None and new >= args.limit:
                    break
                new += not (runs_directory / sha / "run.json").exists()
                run = run_commit(project, repository, sha, runs_directory, image_id)
                status = "built" if run.built else f"not built (setup exit {run.setup_exit})"
                print(f"{name} {number}/{len(shas)} {sha[:12]} {status}, {run.seconds:.0f}s")
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
