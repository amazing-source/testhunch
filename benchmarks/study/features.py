"""What the learned model sees about one test at one build (docs/adr/0030).

Every number here is computed from the builds **before** the one being ranked, from the same
`BuildHistory` the heuristics read. Nothing looks at the build's own results: a feature that did
would make the model unbeatable on paper and useless in CI.

The feature set follows Machalica et al. (ICSE-SEIP 2019, table I) as far as this dataset allows.
Three of their families do not survive the move to RTPTorrent and are named here rather than
quietly dropped:

- **Windows in days become windows in builds.** RTPTorrent's jobs carry no timestamp this replay
  can trust, so "failures in the last 14 days" becomes "failures in the last 14 builds".
- **No author, no reviewer, no distributed-build history.** The dataset has none of it.
- **File extensions become one comparison, not a vocabulary.** A one-hot over every extension in
  twenty Java projects would mostly encode which project a row came from, and the model is meant
  to carry across projects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from benchmarks.study.history import BuildHistory, CaseRecord
from benchmarks.study.metrics import Trial
from benchmarks.study.release_020 import changed_stems

# The windows, in builds. The longest one is what CaseRecord.recent is sized for.
WINDOWS = (7, 14, 28, 56)

# What a feature says when the thing it measures never happened. Large rather than -1, because the
# feature means "how long ago", and a test that never failed is further back than any that did.
NEVER = 10_000.0

NAMES: tuple[str, ...] = (
    "runs",
    "failures",
    "failure_rate",
    "never_failed",
    "builds_since_failure",
    "builds_since_run",
    "failed_last_build",
    "transitions",
    "transition_rate",
    "builds_since_transition",
    "recurrence",
    "duration_ms",
    "duration_share",
    *(f"failure_rate_{size}" for size in WINDOWS),
    *(f"runs_{size}" for size in WINDOWS),
    "test_file_changed",
    "stem_match",
    "path_overlap",
    "same_extension",
    "cochange_failures",
    "cochange_rate",
    "changed_files",
    "tests_in_build",
)


@dataclass(frozen=True, slots=True)
class Change:
    """What is the same for every test of one build, computed once instead of per test."""

    paths: tuple[str, ...]
    stems: frozenset[str]
    extensions: frozenset[str]
    changes_seen: int  # how many builds ever changed one of these paths
    tests: int
    total_duration_ms: float

    @classmethod
    def of(cls, trial: Trial, builds: BuildHistory) -> Change:
        paths = trial.changed_files
        durations = [
            record.mean_duration_ms() or 0.0
            for test in trial.tests
            if (record := builds.records.get(test)) is not None
        ]
        return cls(
            paths=paths,
            stems=frozenset(changed_stems(paths)),
            extensions=frozenset(_extension(path) for path in paths),
            changes_seen=sum(builds.file_changes.get(path, 0) for path in paths),
            tests=len(trial.tests),
            total_duration_ms=sum(durations),
        )


def features(
    test: str, record: CaseRecord, build: int, change: Change, builds: BuildHistory
) -> list[float]:
    """One row, in the order of `NAMES`."""
    runs = float(record.runs)
    row = [
        runs,
        float(record.failures),
        record.failures / runs if runs else 0.0,
        float(record.last_failure < 0),
        float(build - record.last_failure) if record.last_failure >= 0 else NEVER,
        float(build - record.last_run) if record.last_run >= 0 else NEVER,
        float(record.last_failed),
        float(record.transitions),
        record.transitions / runs if runs else 0.0,
        float(build - record.last_transition) if record.last_transition >= 0 else NEVER,
        record.priority_at(build),
        record.mean_duration_ms() or 0.0,
        (record.mean_duration_ms() or 0.0) / change.total_duration_ms
        if change.total_duration_ms
        else 0.0,
    ]
    windows = [record.window(build, size) for size in WINDOWS]
    row += [failures / runs_ if runs_ else 0.0 for runs_, failures in windows]
    row += [float(runs_) for runs_, _ in windows]

    file = record.file
    cochange = sum(builds.file_failures.get(path, {}).get(test, 0) for path in change.paths)
    row += [
        float(file is not None and file in change.paths),
        float(_stem(file) in change.stems) if file else 0.0,
        _path_overlap(file, change.paths),
        float(_extension(file) in change.extensions) if file else 0.0,
        float(cochange),
        cochange / change.changes_seen if change.changes_seen else 0.0,
        float(len(change.paths)),
        float(change.tests),
    ]
    return row


def _stem(path: str | None) -> str:
    if not path:
        return ""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0]


def _extension(path: str | None) -> str:
    if not path:
        return ""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1] if "." in name else ""


def _path_overlap(file: str | None, paths: Sequence[str]) -> float:
    """The longest shared directory prefix with any changed file, as a share of its own depth.

    A test beside the file that changed scores 1, one in another tree scores 0. It is the
    "distance between paths" of the roadmap, normalized so that deep and shallow trees compare.
    """
    if not file or not paths:
        return 0.0
    own = file.replace("\\", "/").split("/")[:-1]
    if not own:
        return 0.0
    best = 0
    for path in paths:
        other = path.replace("\\", "/").split("/")[:-1]
        shared = 0
        for mine, theirs in zip(own, other, strict=False):
            if mine != theirs:
                break
            shared += 1
        best = max(best, shared)
    return best / len(own)
