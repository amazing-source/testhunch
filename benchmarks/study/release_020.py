"""testhunch 0.2.0's ranking, frozen so that the study keeps reproducing (docs/adr/0015).

Copied from `testhunch.prioritize` and `testhunch.models.CaseHistory` as they were in release
0.2.0; testhunch itself now ranks with the study's final version. A test holds this copy to the
orders 0.2.0 gave the RTPTorrent extract, recorded before the change.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from testhunch.models import RankedTest

AFFINITY_WEIGHT = 2.0
_MIN_STEM_LENGTH = 3
_GENERIC_STEMS = frozenset({"__init__", "conftest", "index", "main", "mod", "setup", "utils"})


@dataclass(frozen=True, slots=True)
class CaseHistory:
    """What 0.2.0 knew about a test over the recent window of runs."""

    key: str
    file: str | None
    failures: int
    executions: int
    runs_since_failure: int | None  # 0 = failed in the newest run; None = no failure in window
    suite: str | None = None


def stem(path: str) -> str:
    """`src/lib/carte-grise.test.ts` -> `carte-grise`."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.split(".", 1)[0].lower()


def changed_stems(changed_paths: Iterable[str]) -> set[str]:
    """The stems of changed files specific enough to look for in test names."""
    return {
        s
        for s in (stem(path) for path in changed_paths)
        if len(s) >= _MIN_STEM_LENGTH and s not in _GENERIC_STEMS
    }


def rank(history: Sequence[CaseHistory], changed_paths: Sequence[str] = ()) -> list[RankedTest]:
    stems = changed_stems(changed_paths)
    ranked: list[RankedTest] = []
    for case in history:
        score = 0.0
        reasons: list[str] = []

        haystack = f"{case.file or ''} {case.key}".lower()
        matched = sorted(s for s in stems if s in haystack)
        if matched:
            score += AFFINITY_WEIGHT
            reasons.append("matches changed file " + ", ".join(matched))

        if case.runs_since_failure is not None:
            score += 0.5**case.runs_since_failure
            reasons.append(
                "failed in the latest run"
                if case.runs_since_failure == 0
                else f"last failed {case.runs_since_failure} run(s) ago"
            )

        if case.failures and case.executions:
            rate = case.failures / case.executions
            score += rate
            reasons.append(f"failed {case.failures} of {case.executions} runs")

        ranked.append(RankedTest(case.key, round(score, 6), tuple(reasons)))

    ranked.sort(key=lambda r: (-r.score, r.key))
    return ranked
