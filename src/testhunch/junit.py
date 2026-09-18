"""Parse JUnit XML from any test framework into normalized case results.

JUnit XML has no formal specification; every framework writes its own dialect. What this
parser relies on:

- <testcase> elements anywhere below the root, which is <testsuites> or <testsuite>.
- Outcome children <error>, <failure>, <skipped>. No outcome child means the test passed.
- A `time` attribute in seconds, and `classname`, `name` and an optional `file` attribute.

Dialect notes, each backed by a real report in tests/fixtures/junit:

- pytest: classname is the dotted module path ("tests.test_x", or "tests.test_x.TestClass").
  An error in fixture teardown is reported on the test's own <testcase> as <error>.
- Vitest: classname is the test file path, and name joins describe blocks with " > ".
- jest-junit (default options): classname and name are both "describe blocks + title", and
  there is no file attribute.
- gotestsum: classname is the package import path ("example.com/shop/cart"), which says nothing
  about the file. Subtests are separate cases named "TestParent/sub_name" (spaces become
  underscores), and a failing subtest also fails every parent. The failure message attribute is
  always "Failed". With --rerun-fails, each rerun repeats the <testcase> with no other marker.
- Maven Surefire: one report per test class, rooted at <testsuite>. classname is the fully
  qualified class ("com.example.shop.CartTest", "...CartTest$Discounts" for a @Nested class) and
  parameterized cases are named "priceIsOdd(int)[2]". With rerunFailingTestsCount, reruns stay
  inside the one <testcase>: a test that failed then passed has only <flakyFailure> or
  <flakyError> children (it passed, flakily), and one that failed every attempt has <failure> or
  <error> followed by one <rerunFailure> or <rerunError> per rerun.
- cargo-nextest: classname is the test binary ("shop" for unit tests, "shop::checkout" for
  tests/checkout.rs) and name is the module path ("tests::nested::keeps_total"). Ignored tests
  are left out of the report entirely. Retries use Surefire's <flakyFailure> and <rerunFailure>.
- pytest-rerunfailures: every attempt is its own <testcase>, but the attempts that were rerun are
  written empty, as if they had passed; only the last one has its outcome. The <testsuite>'s
  `tests` counts tests, not attempts, so it is smaller than the number of <testcase> elements,
  which no other runner's report does. See `_merge_reruns` and docs/adr/0008.

Reports are untrusted input when they arrive through the API, so XML is parsed with
defusedxml, which refuses entity expansion and external references.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import replace
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

from testhunch.models import SEVERITY, CaseResult, Status

MAX_MESSAGE_CHARS = 2000

# Surefire and nextest: attempts that failed before the test passed on a retry.
_FLAKY_TAGS = ("flakyFailure", "flakyError")
# ...and every extra attempt, whether it failed again (rerun*) or before a pass (flaky*).
_RETRY_TAGS = ("rerunFailure", "rerunError", *_FLAKY_TAGS)

# pytest writes ANSI colour codes into messages, escaping ESC as the literal text "#x1B".
_ANSI = re.compile(r"(?:\x1b|#x1B)\[[0-9;]*m")

_SOURCE_EXTENSIONS = (
    ".c", ".cc", ".cjs", ".cpp", ".cs", ".cts", ".go", ".java", ".js", ".jsx", ".kt", ".mjs",
    ".mts", ".php", ".py", ".rb", ".rs", ".swift", ".ts", ".tsx",
)  # fmt: skip


# The longest duration kept, in milliseconds: Postgres' INTEGER, the narrower of the two
# stores' columns, about 24.8 days.
LONGEST_DURATION_MS = 2**31 - 1


class ReportError(ValueError):
    """The input is not usable JUnit XML."""


def parse_report(data: bytes) -> list[CaseResult]:
    """Parse one JUnit XML document. Duplicates are kept; see `collapse`."""
    try:
        root = SafeET.fromstring(data)
    except SafeET.ParseError as exc:
        raise ReportError(f"not well-formed XML: {exc}") from exc
    except DefusedXmlException as exc:
        raise ReportError(f"refused unsafe XML: {exc}") from exc

    if root.tag == "testsuite":
        return list(_walk(root, root.get("name") or None))
    if root.tag == "testsuites":
        return list(_walk(root, None))
    raise ReportError(f"root element is <{root.tag}>, expected <testsuites> or <testsuite>")


def parse_reports(blobs: Iterable[bytes]) -> tuple[tuple[CaseResult, ...], str]:
    """Parse the report files of one run. Returns collapsed results and a content digest."""
    blobs = list(blobs)
    if not blobs:
        raise ReportError("no reports given")
    cases: list[CaseResult] = []
    for blob in blobs:
        cases.extend(parse_report(blob))
    return collapse(cases), digest_reports(blobs)


def collapse(cases: Iterable[CaseResult]) -> tuple[CaseResult, ...]:
    """Merge results that share a key into one result per test.

    A test can appear more than once in a run: retries, sharded reports that overlap, or a
    framework that reports setup and call separately. The merged result keeps the worst
    status (and that entry's message), the total time spent, and how many entries there were.
    It is flaky when the entries include both a pass and a failure: with no retry marker a
    repetition may not be a retry, so the worst status is kept rather than hidden (ADR 0005).
    """
    merged: dict[str, CaseResult] = {}
    for case in cases:
        seen = merged.get(case.key)
        if seen is None:
            merged[case.key] = case
            continue
        worst = case if SEVERITY[case.status] > SEVERITY[seen.status] else seen
        # `seen` already holds the worst of the earlier entries, so a pass among them that was
        # outranked by a failure has set `seen.flaky` at that point.
        statuses = (seen.status, case.status)
        passed_and_failed = Status.PASSED in statuses and any(s.is_failure for s in statuses)
        durations = [d for d in (seen.duration_ms, case.duration_ms) if d is not None]
        merged[case.key] = CaseResult(
            key=case.key,
            name=seen.name,
            suite=seen.suite,
            file=seen.file or case.file,
            status=worst.status,
            duration_ms=sum(durations) if durations else None,
            message=worst.message,
            occurrences=seen.occurrences + case.occurrences,
            flaky=seen.flaky or case.flaky or passed_and_failed,
            attempts=seen.attempts + case.attempts,
        )
    return tuple(merged.values())


def digest_reports(blobs: Iterable[bytes]) -> str:
    """A digest of the run's reports that does not depend on the order they were given in."""
    outer = hashlib.sha256()
    for inner in sorted(hashlib.sha256(blob).digest() for blob in blobs):
        outer.update(inner)
    return outer.hexdigest()


def _walk(root: Element, suite: str | None) -> Iterator[CaseResult]:
    """Every case under `root`: a nested suite's cases where it appears, a suite's own at its end.

    A loop over a stack rather than a recursion, so that a report nested a few thousand suites deep
    is read like any other instead of exhausting Python's recursion limit.
    """
    stack: list[tuple[Element, str | None, Iterator[Element], list[CaseResult]]] = [
        (root, suite, iter(root), [])
    ]
    while stack:
        element, name, children, cases = stack[-1]
        child = next(children, None)
        if child is None:
            stack.pop()
            declared = element.get("tests") if element.tag == "testsuite" else None
            if declared is not None and declared.isdigit() and int(declared) < len(cases):
                cases = _merge_reruns(cases)
            yield from cases
        elif child.tag == "testsuite":
            stack.append((child, child.get("name") or name, iter(child), []))
        elif child.tag == "testsuites":
            stack.append((child, name, iter(child), []))
        elif child.tag == "testcase":
            cases.append(_case(child, name))


def _merge_reruns(cases: list[CaseResult]) -> list[CaseResult]:
    """One result per rerun test, in a suite that counts tests rather than attempts (ADR 0008).

    A test is only rerun after a failed attempt, so the empty entries before its last one are
    failures, not the passes they look like. Entries that carry an outcome are left alone.
    """
    by_key: dict[str, list[CaseResult]] = {}
    for case in cases:
        by_key.setdefault(case.key, []).append(case)
    merged: list[CaseResult] = []
    for entries in by_key.values():
        *reruns, last = entries
        if not reruns or not all(_looks_empty(entry) for entry in reruns):
            merged.extend(entries)
            continue
        durations = [e.duration_ms for e in entries if e.duration_ms is not None]
        merged.append(
            replace(
                last,
                duration_ms=sum(durations) if durations else None,
                occurrences=len(entries),
                attempts=len(entries),
                flaky=last.status is Status.PASSED,
            )
        )
    return merged


def _looks_empty(case: CaseResult) -> bool:
    return case.status is Status.PASSED and case.message is None and case.attempts == 1


def _case(case: Element, suite: str | None) -> CaseResult:
    name = case.get("name")
    if not name:
        raise ReportError("found a <testcase> without a name attribute")
    classname = case.get("classname") or None
    file = _file(case, classname)

    # Prefer classname, which is the most specific grouping when it differs from the name.
    # jest-junit repeats the name as the classname, so fall back to the file, then the suite.
    if classname and classname != name:
        group: str | None = classname
    else:
        group = file or suite
    key = f"{group}::{name}" if group else name

    status, message = _outcome(case)
    return CaseResult(
        key=key,
        name=name,
        suite=group,
        file=file,
        status=status,
        duration_ms=_duration_ms(case.get("time")),
        message=message,
        flaky=status is Status.PASSED and any(case.find(tag) is not None for tag in _FLAKY_TAGS),
        attempts=1 + sum(1 for child in case if child.tag in _RETRY_TAGS),
    )


def _file(case: Element, classname: str | None) -> str | None:
    explicit = case.get("file")
    if explicit:
        return explicit.replace("\\", "/")
    # A slash alone does not make a file: Go import paths and Jest describe names contain them.
    if classname and classname.endswith(_SOURCE_EXTENSIONS):
        return classname.replace("\\", "/")
    return None


def _outcome(case: Element) -> tuple[Status, str | None]:
    for tag, status in (
        ("error", Status.ERROR),
        ("failure", Status.FAILED),
        ("skipped", Status.SKIPPED),
    ):
        child = case.find(tag)
        if child is not None:
            return status, _message(child)
    return Status.PASSED, None


def _message(outcome: Element) -> str | None:
    text = outcome.get("message") or (outcome.text or "").strip()
    if not text:
        return None
    text = _ANSI.sub("", text)
    return text if len(text) <= MAX_MESSAGE_CHARS else text[: MAX_MESSAGE_CHARS - 1] + "…"


def _duration_ms(raw: str | None) -> int | None:
    # Anything that is not a plain decimal number of seconds is recorded as unknown rather
    # than guessed at: "0,5" could be half a second or five, depending on the locale.
    if raw is None or not raw.strip():
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    milliseconds = round(seconds * 1000)
    # Beyond what both stores can hold, a duration is no longer a duration anyone measured.
    return milliseconds if milliseconds <= LONGEST_DURATION_MS else None
