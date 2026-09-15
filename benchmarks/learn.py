"""Build and fit the learned model of phase 6 (docs/adr/0030).

    uv run python -m benchmarks.learn collect   # replay the training projects into a dataset
    uv run python -m benchmarks.learn train     # fit the trees and report what they lean on

Then the study scores it like any other ranking, on the **validation** projects, which the model
has never seen:

    uv run python -m benchmarks.study learned --projects <the validation projects>

The split is the one of ADR 0013, applied once more to the development projects: this trains on
one half and is chosen on the other, so the held-out projects stay untouched until a version is
frozen.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from benchmarks.rtptorrent.data import fetch_project, iter_jobs
from benchmarks.split import RTPTORRENT_TRAINING
from benchmarks.study.learned import (
    Dataset,
    collect_project,
    fit,
    importances,
    merge,
    save_model,
    summary,
)
from benchmarks.study.projects import CACHE, MODEL

DEFAULT_CACHE = CACHE / "rtptorrent"
# Not under the study's own output: that directory holds one JSON per project, and
# anything else in it would be read back as a project result.
DEFAULT_OUT = CACHE / "learned"
DATASET = "dataset.npz"


def collect(projects: Sequence[str], cache: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    parts = []
    for project in projects:
        dataset = collect_project(iter_jobs(fetch_project(project, cache)), project)
        parts.append(dataset)
        print(f"{project}: {len(dataset.labels)} rows, {int(dataset.labels.sum())} failing")
    whole = merge(parts)
    whole.save(out / DATASET)
    (out / "dataset.json").write_text(summary(whole) + "\n", encoding="utf-8")
    print(summary(whole))
    return 0


def train(out: Path) -> int:
    dataset = Dataset.load(out / DATASET)
    model = fit(dataset)
    save_model(model, MODEL)
    weights = importances(model, dataset)
    (out / "importances.json").write_text(json.dumps(weights, indent=2) + "\n", encoding="utf-8")
    print(f"fitted on {len(dataset.labels)} rows, saved to {MODEL}")
    for name, value in list(weights.items())[:12]:
        print(f"  {value:+.4f}  {name}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.learn")
    parser.add_argument("action", choices=("collect", "train"))
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--projects",
        nargs="+",
        choices=sorted(RTPTORRENT_TRAINING),
        default=sorted(RTPTORRENT_TRAINING),
        help="the training half of the development projects, and only it (docs/adr/0013)",
    )
    args = parser.parse_args(argv)
    if args.action == "collect":
        return collect(args.projects, args.cache, args.out)
    return train(args.out)


if __name__ == "__main__":
    sys.exit(main())
