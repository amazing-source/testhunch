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
  <flakyError> children (so it passed), and one that failed every attempt has <failure> or
  <error> followed by one <rerunFailure> or <rerunError> per rerun.
- cargo-nextest: classname is the test binary ("shop" for unit tests, "shop::checkout" for
  tests/checkout.rs) and name is the module path ("tests::nested::keeps_total"). Ignored tests
  are left out of the report entirely. Retries use Surefire's <flakyFailure> and <rerunFailure>.

Reports are untrusted input when they arrive through the API, so XML is parsed with
defusedxml, which refuses entity expansion and external references.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Iterator
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

from testhunch.models import SEVERITY, CaseResult, Status

MAX_MESSAGE_CHARS = 2000

# pytest writes ANSI colour codes into messages, escaping ESC as the literal text "#x1B".
_ANSI = re.compile(r"(?:\x1b|#x1B)\[[0-9;]*m")

_SOURCE_EXTENSIONS = (
    ".c", ".cc", ".cjs", ".cpp", ".cs", ".cts", ".go", ".java", ".js", ".jsx", ".kt", ".mjs",
    ".mts", ".php", ".py", ".rb", ".rs", ".swift", ".ts", ".tsx",
)  # fmt: skip


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
    """
    merged: dict[str, CaseResult] = {}
    for case in cases:
        seen = merged.get(case.key)
        if seen is None:
            merged[case.key] = case
            continue
        worst = case if SEVERITY[case.status] > SEVERITY[seen.status] else seen
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
        )
    return tuple(merged.values())


def digest_reports(blobs: Iterable[bytes]) -> str:
    """A digest of the run's reports that does not depend on the order they were given in."""
    outer = hashlib.sha256()
    for inner in sorted(hashlib.sha256(blob).digest() for blob in blobs):
        outer.update(inner)
    return outer.hexdigest()


def _walk(element: Element, suite: str | None) -> Iterator[CaseResult]:
    for child in element:
        if child.tag == "testsuite":
            yield from _walk(child, child.get("name") or suite)
        elif child.tag == "testsuites":
            yield from _walk(child, suite)
        elif child.tag == "testcase":
            yield _case(child, suite)


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
    return round(seconds * 1000)
