"""Order tests so the ones most likely to fail for this change run first (docs/adr/0015).

The ranking the study kept (docs/adr/0014), over every earlier build:

- the latest failure: RTPTorrent's priority, which gives the newest failure more weight than all
  older ones together (Mattis et al., MSR 2020, section 4);
- the test's own file changed: a bonus, since a change often breaks the test it edits;
- per unit of time: the score is divided by the test's usual duration, so a quick test that may
  fail runs before a slow one that may fail as much.

Every score comes with the reasons behind it. The arithmetic is the study engine's, step for step,
so that the product replay gives the study's numbers.
"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Sequence

from testhunch.models import CaseHistory, History, RankedTest

# RTPTorrent's weight of the newest build in a test's failure priority.
ALPHA = 0.8
FILE_CHANGED_WEIGHT = 0.5
# Added to every duration, as Cheng et al. (ISSTA 2024) add 0.001 s: a 0 ms test still takes time.
EPSILON_MS = 1


def add_failure(last_failure: int | None, priority: float, build: int) -> tuple[int, float]:
    """The last failure and priority once the test also failed in `build`.

    The priority at the last failure L is the sum of alpha (1 - alpha)^(L - b) over the builds b the
    test failed in; a failure in a build before L, from a run that arrived late, adds its term.
    """
    if last_failure is None:
        return build, ALPHA + (1 - ALPHA) * 0.0
    if build > last_failure:
        return build, ALPHA + (1 - ALPHA) * priority_at(last_failure, priority, build)
    if build < last_failure:
        return last_failure, priority + ALPHA * (1 - ALPHA) ** (last_failure - build)
    return last_failure, priority


def priority_at(last_failure: int | None, priority: float, builds: int) -> float:
    """The priority once `builds` builds are recorded: decayed by 1 - alpha per build since."""
    if last_failure is None:
        return 0.0
    return float(priority * (1 - ALPHA) ** (builds - 1 - last_failure))


def location(key: str, file: str | None) -> str:
    """Where a test lives: its reported file, else its class as a path (`org.a.B` -> `org/a/B`)."""
    if file:
        return file.replace("\\", "/")
    group = key.split("::", 1)[0].split("$", 1)[0]
    return group if "/" in group else group.replace(".", "/")


def _without_extension(path: str) -> str:
    head, _, name = path.rpartition("/")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return f"{head}/{stem}" if head else stem


def rank(history: History, changed_paths: Sequence[str] = (), seed: str = "") -> list[RankedTest]:
    """Every known test, most likely to fail per unit of time first.

    Ties go to the shorter test, the newer failure, the higher priority, then a hash of `seed` and
    the key: the CLI seeds with the commit being ranked, so that ties do not follow the alphabet.
    """
    changed = [
        _without_extension(path) for path in sorted({p.replace("\\", "/") for p in changed_paths})
    ]
    measured = [c.mean_duration_ms for c in history.cases if c.mean_duration_ms is not None]
    # A test with no known duration gets the median of the others: it is neither buried nor rushed.
    fallback = statistics.median(measured) if measured else 0.0
    entries: list[tuple[tuple[float, float, int, float, bytes], RankedTest]] = []
    for case in history.cases:
        mean = case.mean_duration_ms
        duration = (mean if mean is not None else fallback) + EPSILON_MS
        own = _without_extension(location(case.key, case.file))
        file_changed = any(path == own or path.endswith("/" + own) for path in changed)
        score = priority_at(case.last_failure, case.priority, history.builds)
        score += FILE_CHANGED_WEIGHT * float(file_changed)
        score /= duration
        last = -1 if case.last_failure is None else case.last_failure
        tie = hashlib.sha256(f"{seed}\0{case.key}".encode()).digest()
        order = (-score, duration, -last, -case.priority, tie)
        # `duration` is what a time budget spends on this test: the same number the score used.
        ranked = RankedTest(case.key, score, _reasons(case, history, file_changed), duration)
        entries.append((order, ranked))
    entries.sort(key=lambda entry: entry[0])
    return [ranked for _, ranked in entries]


def _reasons(case: CaseHistory, history: History, file_changed: bool) -> tuple[str, ...]:
    reasons: list[str] = []
    if case.last_failure is not None:
        ago = history.builds - 1 - case.last_failure
        reasons.append(
            "failed in the latest build" if ago == 0 else f"last failed {ago} build(s) ago"
        )
    if file_changed:
        reasons.append("its file changed")
    if case.mean_duration_ms is None:
        reasons.append("duration unknown")
    else:
        reasons.append(f"takes about {case.mean_duration_ms:.0f} ms")
    return tuple(reasons)
