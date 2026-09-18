"""The candidate rankings of the study (docs/adr/0014).

A ranking orders a trial's tests: the ones its history does not know first, in the job's order,
then the known ones. Ties are broken by a hash of the job and the test, shared by every ranking.
"""

from __future__ import annotations

import hashlib
import random
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from rapidfuzz.distance import Levenshtein

from benchmarks.study.history import BuildHistory, CaseRecord
from benchmarks.study.metrics import EPSILON_MS, Trial
from benchmarks.study.release_020 import CaseHistory, changed_stems, rank


@dataclass(frozen=True, slots=True)
class Context:
    """What is known when a trial is ranked: the builds before its build."""

    builds: BuildHistory
    window: Callable[[], list[CaseHistory]]  # the 0.2.0 store's history, computed on demand


class Ranking(Protocol):
    @property
    def name(self) -> str: ...

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        """The trial's tests in the order they would run, and how many of them are known."""
        ...


def tie(job_id: int, key: str) -> bytes:
    return hashlib.sha256(f"{job_id}\0{key}".encode()).digest()


def split_known(trial: Trial, builds: BuildHistory) -> tuple[list[str], list[str]]:
    unknown = [test for test in trial.tests if test not in builds.records]
    known = [test for test in trial.tests if test in builds.records]
    return unknown, known


@dataclass(frozen=True, slots=True)
class LatestFailure:
    """The tests that failed most recently first: RTPTorrent's priority, alpha = 0.8.

    With alpha > 0.5 the newest failure outweighs all older ones together, so sorting by the newest
    failure, then by the priority at that build, gives the priority's order without its underflow.
    """

    name: str = "latest-failure"

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        unknown, known = split_known(trial, context.builds)
        records = context.builds.records
        known.sort(key=lambda test: _latest_failure_key(records[test], trial.job_id, test))
        return unknown + known, len(known)


def _latest_failure_key(record: CaseRecord, job_id: int, test: str) -> tuple[int, float, bytes]:
    return (-record.last_failure, -record.priority, tie(job_id, test))


@dataclass(frozen=True, slots=True)
class Shuffled:
    """The guardrail's bar: the trial's tests in a random order (docs/adr/0018).

    Not a candidate. A ranking must not be worse than shuffling at finding a test that has never
    failed, and that bar needs no data to justify, so it cannot be bent to fit a candidate. Seeded
    once per replay, so rerunning this scores the same orders for anyone.
    """

    seed: random.Random
    name: str = "random"

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        order = list(trial.tests)
        self.seed.shuffle(order)
        # Everything counts as unknown: a shuffle knows nothing, which is the whole point of it.
        return order, 0


@dataclass(frozen=True, slots=True)
class ProductRanking:
    """testhunch 0.2.0's own ranking, from the store's window of runs (ADR 0010)."""

    name: str = "testhunch-0.2.0"

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        return product_order(trial.tests, context.window(), trial.changed_files)


def product_order(
    tests: Sequence[str], history: list[CaseHistory], changed_files: Sequence[str]
) -> tuple[list[str], int]:
    """The order `benchmarks.replay` gives a job: unknown tests first, then by rank."""
    positions = {test.key: index for index, test in enumerate(rank(history, changed_files), 1)}
    order = sorted(tests, key=lambda key: (key in positions, positions.get(key, 0)))
    return order, sum(1 for test in tests if test in positions)


# Signals of steps 1 and 2: the test's history, and the name matching of testhunch 0.2.0.
HISTORY_SIGNALS = ("failure_rate", "transitions", "file_failures", "name")
# Signals of the extension step (ADR 0014): how close a test is to the files the change touched.
PROXIMITY_SIGNALS = (
    "test_file_changed",
    "subject_file_changed",
    "path_similarity",
    "token_similarity",
    "name_similarity",
)
SIGNALS = (*HISTORY_SIGNALS, *PROXIMITY_SIGNALS)
# What decides between two tests of equal score (docs/adr/0035).
TIE_BREAKS = ("cost", "hash", "name", "cost-if-scored", "cost-if-risk")
# A candidate's sort key: minus its score, then what decides between equal scores.
SortKey = tuple[float, float, int, float, bytes]
_TEST_AFFIXES = re.compile(r"^(?:test_|Test(?=[A-Z]))|(?:_test|Tests?|IT|TestCase)$")
_TOKENS = re.compile(r"[/\._$\-]+|(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True, slots=True)
class Candidate:
    """The latest failure with signals added, as a step of the study commits them (ADR 0014).

    A known test scores its failure priority plus each signal times its weight. With a time
    exponent the score is divided by the expected duration to that power, and shorter tests go
    first among equal scores. With a window, a test that has not run in that many builds counts as
    unknown, and runs first like a new one. Without signals it orders as `LatestFailure`.
    """

    name: str
    weights: tuple[tuple[str, float], ...] = ()
    time_exponent: float | None = None
    window: int | None = None
    # Signals added only to a test whose failure priority is 0: they speak where the history says
    # nothing, and leave the rest of the ranking untouched (docs/adr/0018). `weights` above are
    # added to every test, as the study's steps did.
    # A priority of 0 is *nearly* the same thing as "never failed", not quite: it decays by a factor
    # of five per build, so it underflows to exactly 0.0 after 463 builds without a failure, and a
    # long-lived test that failed once, long ago, falls in here too (`test_cold_start_underflows`).
    # The rule is applied to the letter, as ADR 0018 fixed it before any candidate ran.
    cold_weights: tuple[tuple[str, float], ...] = ()
    # The time exponent to use on a test whose failure priority is 0; None keeps `time_exponent`.
    # 0.0 means the score is not divided by the duration at all there: dividing by a cost only
    # arbitrates between tests whose risk is estimated, and there is none to estimate (ADR 0018).
    cold_time_exponent: float | None = None
    # What decides between two tests of equal score (docs/adr/0035). On the first-failure slice
    # every candidate scores zero, so this is not a detail there, it is the whole order.
    #   cost: the duration, cheapest first, then a hash. What testhunch ships.
    #   hash: the hash alone, so a slow test is not placed last for being slow.
    #   name: the test's own name, which is what 0.2.0 does.
    #   cost-if-scored: the duration between equal scores above zero, the hash between zeros; the
    #     cost is kept where the score says something and dropped where it says nothing.
    #   cost-if-risk: the duration only for tests whose failure priority is above zero, the hash
    #     for the others, including a test whose score is only a signal (docs/adr/0036).
    # `cold_time_exponent=0` does **not** remove the cost ordering: it only takes the divisor out of
    # the score, and the duration stays in this key. That is why ADR 0018's `cold-free` step could
    # not measure what it was aimed at.
    tie_break: str = "cost"

    def __post_init__(self) -> None:
        both = (*self.weights, *self.cold_weights)
        unknown = {signal for signal, _ in both} - set(SIGNALS)
        if unknown:
            raise ValueError(f"unknown signals: {sorted(unknown)}")
        if self.tie_break not in TIE_BREAKS:
            raise ValueError(f"unknown tie break {self.tie_break!r}, expected one of {TIE_BREAKS}")

    def order(self, trial: Trial, context: Context) -> tuple[list[str], int]:
        unknown, keys = self.keys(trial, context)
        known = sorted(keys, key=keys.__getitem__)
        return unknown + known, len(known)

    def keys(self, trial: Trial, context: Context) -> tuple[list[str], dict[str, SortKey]]:
        """The tests that run first, in the job's order, and the sort key of every other one.

        Split from `order` so that a benchmark can read what decided an order, and not only the
        order (benchmarks/costorder.py).
        """
        builds = context.builds
        records = builds.records
        now = builds.builds
        unknown: list[str] = []
        known: list[str] = []
        for test in trial.tests:
            record = records.get(test)
            stale = (
                self.window is not None
                and record is not None
                and record.last_run < now - self.window
            )
            (unknown if record is None or stale else known).append(test)
        signals = {
            name: _signal(name, trial, context) for name, _ in (*self.weights, *self.cold_weights)
        }
        durations = _expected_durations(known, records) if self.time_exponent is not None else {}

        def key(test: str) -> SortKey:
            record = records[test]
            score = priority = record.priority_at(now)
            exponent = self.time_exponent
            if not priority:
                # Nothing in the history: the cold-start signals are all this test has, and the
                # cost may weigh differently when there is no risk estimate to weigh it against.
                for name, weight in self.cold_weights:
                    score += weight * signals[name](test)
                if self.cold_time_exponent is not None:
                    exponent = self.cold_time_exponent
            for name, weight in self.weights:
                score += weight * signals[name](test)
            duration = durations.get(test, 1.0)
            if exponent:
                score /= duration**exponent
            by_cost = (
                self.tie_break == "cost"
                or (self.tie_break == "cost-if-scored" and score > 0)
                or (self.tie_break == "cost-if-risk" and priority > 0)
            )
            return (
                -score,
                duration if by_cost else 0.0,
                -record.last_failure,
                -record.priority,
                test.encode() if self.tie_break == "name" else tie(trial.job_id, test),
            )

        return unknown, {test: key(test) for test in known}


def _signal(name: str, trial: Trial, context: Context) -> Callable[[str], float]:
    builds = context.builds
    records = builds.records
    if name == "failure_rate":
        return lambda test: records[test].failures / records[test].runs
    if name == "transitions":
        return lambda test: records[test].transition_priority_at(builds.builds)
    if name == "file_failures":
        changed = [path for path in set(trial.changed_files) if builds.file_changes.get(path)]

        def file_failures(test: str) -> float:
            # The highest share of a changed file's past changes that this test failed after.
            return max(
                (
                    builds.file_failures.get(path, {}).get(test, 0) / builds.file_changes[path]
                    for path in changed
                ),
                default=0.0,
            )

        return file_failures
    if name == "name":
        stems = changed_stems(trial.changed_files)

        def name_match(test: str) -> float:
            haystack = f"{records[test].file or ''} {test}".lower()
            return float(any(s in haystack for s in stems))

        return name_match
    if name in PROXIMITY_SIGNALS:
        return _proximity(name, trial, records)
    raise ValueError(f"unknown signal: {name}")


def location(key: str, file: str | None) -> str:
    """Where a test lives: its reported file, else its class as a path (`org.a.B` -> `org/a/B`)."""
    if file:
        return file.replace("\\", "/")
    group = key.split("::", 1)[0].split("$", 1)[0]
    return group if "/" in group else group.replace(".", "/")


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _without_extension(path: str) -> str:
    head, _, name = path.rpartition("/")
    return f"{head}/{_stem(name)}" if head else _stem(name)


def _tokens(path: str) -> set[str]:
    return {token.lower() for token in _TOKENS.split(path) if len(token) > 1}


def _proximity(name: str, trial: Trial, records: dict[str, CaseRecord]) -> Callable[[str], float]:
    """A signal of how close a test is to the change, from 0 to 1 (Elsner et al., ISSTA 2021).

    - test_file_changed: the change touches the test's own file;
    - subject_file_changed: the change touches a file named like the test without its test
      affixes (`BarTest` -> `Bar`, `test_bar` -> `bar`);
    - path_similarity: 1 minus the smallest normalized Levenshtein distance between the test's
      path and a changed path (their minimum file path distance);
    - token_similarity: the largest share of the test path's tokens found in a changed path
      (their common path tokens, divided by the test's tokens to stay within 0 and 1);
    - name_similarity: the same as path_similarity between the test's name and a changed file's.
    """
    changed = sorted({path.replace("\\", "/") for path in trial.changed_files})
    if not changed:
        return lambda test: 0.0
    stripped = [_without_extension(path) for path in changed]
    stems = [_stem(path).lower() for path in changed]
    tokens = [_tokens(path) for path in changed]

    def value(test: str) -> float:
        path = location(test, records[test].file)
        if name == "test_file_changed":
            own = _without_extension(path)
            return float(any(s == own or s.endswith("/" + own) for s in stripped))
        if name == "subject_file_changed":
            subject = _TEST_AFFIXES.sub("", _stem(path)).lower()
            own = _stem(path).lower()
            return float(len(subject) >= 3 and any(s == subject != own for s in stems))
        if name == "path_similarity":
            return max(Levenshtein.normalized_similarity(path, other) for other in changed)
        if name == "token_similarity":
            mine = _tokens(path)
            return max(len(mine & theirs) for theirs in tokens) / len(mine) if mine else 0.0
        own = _stem(path).lower()
        return max(Levenshtein.normalized_similarity(own, stem) for stem in stems)

    return value


def _expected_durations(known: Sequence[str], records: dict[str, CaseRecord]) -> dict[str, float]:
    """Each known test's mean past duration, plus the epsilon of ADR 0014.

    A test with no known past duration gets the median of the others in the job: a ranking needs
    some cost to order it by, and the median neither favours nor buries it.
    """
    means = {test: records[test].mean_duration_ms() for test in known}
    measured = [mean for mean in means.values() if mean is not None]
    fallback = statistics.median(measured) if measured else 0.0
    return {
        test: (mean if mean is not None else fallback) + EPSILON_MS for test, mean in means.items()
    }
