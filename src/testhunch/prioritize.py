"""Order tests so the ones most likely to fail for this change run first.

This is the baseline every later model has to beat, so it is deliberately simple and every
score comes with the reasons behind it:

- affinity: the test's file or key contains the stem of a changed file
  (changing `src/lib/cart.ts` pulls up `src/lib/cart.test.ts`),
- recency: the test failed recently; the bonus halves with every run since,
- failure rate: how often the test failed across the window.

Known weaknesses, kept on purpose until the benchmark can measure fixes for them: substring
matching over-matches ("store" in "restore"), and a flaky test's failures count as signal.
"""

from __future__ import annotations

from collections.abc import Sequence

from testhunch.models import CaseHistory, RankedTest

AFFINITY_WEIGHT = 2.0
_MIN_STEM_LENGTH = 3
_GENERIC_STEMS = frozenset({"__init__", "conftest", "index", "main", "mod", "setup", "utils"})


def stem(path: str) -> str:
    """`src/lib/carte-grise.test.ts` -> `carte-grise`."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.split(".", 1)[0].lower()


def rank(history: Sequence[CaseHistory], changed_paths: Sequence[str] = ()) -> list[RankedTest]:
    stems = {
        s
        for s in (stem(path) for path in changed_paths)
        if len(s) >= _MIN_STEM_LENGTH and s not in _GENERIC_STEMS
    }
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
