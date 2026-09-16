"""The learned model of phase 6 (docs/adr/0030).

    uv run python -m benchmarks.learn collect   # build the training set
    uv run python -m benchmarks.learn train     # fit the trees
    uv run python -m benchmarks.study learned --projects <the validation projects>

Gradient-boosted trees over the features of `benchmarks.study.features`, trained on the training
half of the development projects and chosen on the validation half, never on the held-out ones
(docs/adr/0013). The model is a ranking like any other in the study, so it is scored by the same
engine, on the same trials, against the same heuristic.
"""

from __future__ import annotations

import json
import pickle
import random
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from benchmarks.replay import Job, concurrent_groups
from benchmarks.study.features import NAMES, Change, features
from benchmarks.study.history import BuildHistory
from benchmarks.study.metrics import Trial
from benchmarks.study.rankings import Candidate, Context, split_known, tie
from testhunch.junit import collapse

# How many passing tests are kept per failing test of the same build. Every failure is kept; the
# passes are the cheap and repetitive half, and keeping all of them would make the training set
# hundreds of millions of rows for no signal the sample does not already carry.
NEGATIVES_PER_POSITIVE = 20

SEED = 0


@dataclass(frozen=True, slots=True)
class Dataset:
    rows: np.ndarray  # (n, len(NAMES))
    labels: np.ndarray  # (n,) 1 when the test failed in that build
    projects: list[str]  # one per row, so a project can be held out of a fit

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, rows=self.rows, labels=self.labels, projects=np.array(self.projects)
        )

    @classmethod
    def load(cls, path: Path) -> Dataset:
        with np.load(path, allow_pickle=False) as stored:
            return cls(
                rows=stored["rows"],
                labels=stored["labels"],
                projects=[str(name) for name in stored["projects"]],
            )


def collect_project(jobs: Iterable[Job], project: str, seed: int = SEED) -> Dataset:
    """Replay one project and emit a row per interesting (build, test) pair.

    Only builds that actually went red produce rows. At inference a ranking is consulted to decide
    what to run, and what it gets wrong is which test of a red build comes first; a green build
    teaches nothing about that, and there are a hundred times more of them.
    """
    rng = random.Random(f"{seed}:{project}")
    builds = BuildHistory()
    rows: list[list[float]] = []
    labels: list[int] = []
    for group in concurrent_groups(jobs):
        collapsed = [collapse(job.results) for job in group]
        if builds.builds:
            for job, results in zip(group, collapsed, strict=True):
                trial = Trial(
                    job_id=job.job_id,
                    tests=tuple(result.key for result in results),
                    failing=frozenset(
                        r.key for r in results if r.status.is_failure and not r.flaky
                    ),
                    durations={result.key: result.duration_ms for result in results},
                    changed_files=job.changed_files or (),
                )
                rows_of, labels_of = _rows(trial, builds, rng)
                rows += rows_of
                labels += labels_of
        changed = [path for job in group for path in job.changed_files or ()]
        builds.record(collapsed, changed)
    return Dataset(
        rows=np.array(rows, dtype=np.float32).reshape(-1, len(NAMES)),
        labels=np.array(labels, dtype=np.int8),
        projects=[project] * len(labels),
    )


def _rows(
    trial: Trial, builds: BuildHistory, rng: random.Random
) -> tuple[list[list[float]], list[int]]:
    known_failing = [test for test in trial.failing if test in builds.records]
    if not known_failing:
        return [], []
    change = Change.of(trial, builds)
    passing = [test for test in trial.tests if test not in trial.failing and test in builds.records]
    rng.shuffle(passing)
    chosen = known_failing + passing[: NEGATIVES_PER_POSITIVE * len(known_failing)]
    rows = [features(test, builds.records[test], builds.builds, change, builds) for test in chosen]
    labels = [1] * len(known_failing) + [0] * (len(chosen) - len(known_failing))
    return rows, labels


def merge(datasets: Sequence[Dataset]) -> Dataset:
    return Dataset(
        rows=np.concatenate([d.rows for d in datasets]) if datasets else np.empty((0, len(NAMES))),
        labels=np.concatenate([d.labels for d in datasets]) if datasets else np.empty(0),
        projects=[project for d in datasets for project in d.projects],
    )


def fit(dataset: Dataset, **parameters: Any) -> HistGradientBoostingClassifier:
    """Gradient-boosted trees, with the sample weighting that makes a rare positive count."""
    settings: dict[str, Any] = {
        "max_iter": 300,
        "learning_rate": 0.06,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 40,
        "l2_regularization": 1.0,
        "random_state": SEED,
    } | parameters
    model = HistGradientBoostingClassifier(**settings)
    positives = int(dataset.labels.sum())
    negatives = len(dataset.labels) - positives
    weight = np.where(dataset.labels == 1, negatives / max(positives, 1), 1.0)
    model.fit(dataset.rows, dataset.labels, sample_weight=weight)
    return model


@dataclass(frozen=True, slots=True)
class LearnedRanking:
    """A fitted model, as a ranking the study's engine can score like any other.

    `time_exponent` divides the predicted probability by the test's expected duration, the same
    cost arbitration the shipped heuristic makes (ADR 0015). Without it the comparison would ask
    two questions at once: whether the model estimates risk better, and whether dividing by cost
    helps, which the study already answered on its own.
    """

    model: HistGradientBoostingClassifier
    name: str = "learned"
    time_exponent: float | None = None

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        unknown, known = split_known(trial, context.builds)
        if not known:
            return unknown, 0
        builds = context.builds
        change = Change.of(trial, builds)
        rows = np.array(
            [features(test, builds.records[test], builds.builds, change, builds) for test in known],
            dtype=np.float32,
        )
        scores = self.model.predict_proba(rows)[:, 1]
        by_test = dict(zip(known, scores, strict=True))
        if self.time_exponent is not None:
            by_test = {
                test: score / _expected_ms(test, builds, known) ** self.time_exponent
                for test, score in by_test.items()
            }
        known.sort(key=lambda test: (-by_test[test], tie(trial.job_id, test)))
        return unknown + known, len(known)


def _expected_ms(test: str, builds: BuildHistory, known: Sequence[str]) -> float:
    """The test's mean duration, the median of the others when it has none, never below 1 ms.

    The same rule as the shipped ranking (ADR 0017), so the two divide by the same number.
    """
    own = builds.records[test].mean_duration_ms()
    if own is None:
        others = [
            duration
            for other in known
            if (duration := builds.records[other].mean_duration_ms()) is not None
        ]
        own = statistics.median(others) if others else 0.0
    return max(own, 1.0)


@dataclass(frozen=True, slots=True)
class ColdLearned:
    """The heuristic, with the model deciding only where the history says nothing (ADR 0031).

    A test whose failure priority is 0 has nothing in the history to be ranked by, and the
    heuristic falls back to cost and a tie hash ([ADR 0018](docs/adr/0018)). This keeps the
    heuristic's order for every other test and re-orders those among themselves by the model's
    predicted probability, in the positions they already occupied.

    It is the narrowest use of the model that the phase 6 result suggests: it cannot move a test
    the history does speak about, so whatever it does to the first-failure slice, it does almost
    nothing to the other one.
    """

    model: HistGradientBoostingClassifier
    heuristic: Candidate
    name: str = "cold-learned"

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        order, count = self.heuristic.order(trial, context)
        builds = context.builds
        records, now = builds.records, builds.builds
        known = order[len(order) - count :] if count else []
        cold = [index for index, test in enumerate(known) if not records[test].priority_at(now)]
        if len(cold) < 2:
            return order, count

        change = Change.of(trial, builds)
        rows = np.array(
            [features(known[i], records[known[i]], now, change, builds) for i in cold],
            dtype=np.float32,
        )
        scores = dict(zip(cold, self.model.predict_proba(rows)[:, 1], strict=True))
        by_score = sorted(cold, key=lambda i: (-scores[i], tie(trial.job_id, known[i])))
        rearranged = list(known)
        for position, source in zip(cold, by_score, strict=True):
            rearranged[position] = known[source]
        return order[: len(order) - count] + rearranged, count


def save_model(model: HistGradientBoostingClassifier, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(model))


def load_model(path: Path) -> HistGradientBoostingClassifier:
    # Loaded only from a file this repository's own commands wrote, never from anywhere else.
    return pickle.loads(path.read_bytes())


def importances(model: HistGradientBoostingClassifier, dataset: Dataset) -> dict[str, float]:
    """Which features the fitted model actually leans on, by permutation on its own training set.

    Tree importances by split count flatter correlated features; permuting the column and watching
    the score fall says what the model would lose without it.
    """
    from sklearn.inspection import permutation_importance

    sample = min(len(dataset.labels), 50_000)
    rng = np.random.default_rng(SEED)
    index = rng.choice(len(dataset.labels), size=sample, replace=False)
    result = permutation_importance(
        model,
        dataset.rows[index],
        dataset.labels[index],
        n_repeats=3,
        random_state=SEED,
        scoring="average_precision",
    )
    return dict(
        sorted(
            zip(NAMES, (float(value) for value in result.importances_mean), strict=True),
            key=lambda item: -item[1],
        )
    )


def summary(dataset: Dataset) -> str:
    positives = int(dataset.labels.sum())
    return json.dumps(
        {
            "rows": len(dataset.labels),
            "failing_rows": positives,
            "projects": sorted(set(dataset.projects)),
        },
        indent=2,
    )
