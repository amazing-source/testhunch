from __future__ import annotations

from pathlib import Path

import pytest

from testhunch.junit import (
    MAX_MESSAGE_CHARS,
    ReportError,
    collapse,
    digest_reports,
    parse_report,
    parse_reports,
)
from testhunch.models import CaseResult, Status

FIXTURES = Path(__file__).parent / "fixtures" / "junit"


def by_key(cases: list[CaseResult]) -> dict[str, CaseResult]:
    return {case.key: case for case in cases}


class TestRealReports:
    """Reports produced by the real frameworks (see tests/fixtures/junit)."""

    def test_pytest(self) -> None:
        cases = by_key(parse_report((FIXTURES / "pytest.xml").read_bytes()))

        assert len(cases) == 9
        assert cases["tests.test_sample::test_passes"].status is Status.PASSED
        assert cases["tests.test_sample::test_fails"].status is Status.FAILED
        assert cases["tests.test_sample::test_skipped"].status is Status.SKIPPED
        assert cases["tests.test_sample::test_parametrized[2]"].status is Status.FAILED
        assert cases["tests.test_sample::test_parametrized[3]"].status is Status.PASSED
        assert cases["tests.test_sample::test_errors_in_setup"].status is Status.ERROR
        assert cases["tests.test_sample::test_errors_in_teardown"].status is Status.ERROR
        assert cases["tests.test_sample.TestGrouped::test_in_class"].status is Status.PASSED

    def test_pytest_messages_lose_ansi_colour_codes(self) -> None:
        cases = by_key(parse_report((FIXTURES / "pytest.xml").read_bytes()))
        message = cases["tests.test_sample::test_fails"].message

        assert message is not None
        assert message.startswith("AssertionError: strings differ")
        assert "#x1B" not in message

    def test_pytest_has_no_file_path(self) -> None:
        # A dotted module path is not a file path; guessing "tests/test_sample.py" could be wrong.
        cases = parse_report((FIXTURES / "pytest.xml").read_bytes())
        assert {case.file for case in cases} == {None}

    def test_vitest(self) -> None:
        cases = by_key(parse_report((FIXTURES / "vitest.xml").read_bytes()))
        prefix = "src/cart.vitest.test.js::cart total > "

        assert len(cases) == 4
        assert cases[prefix + "sums prices"].status is Status.PASSED
        assert cases[prefix + "fails on purpose"].status is Status.FAILED
        assert cases[prefix + "skipped case"].status is Status.SKIPPED
        assert cases[prefix + "nested > handles quantities"].status is Status.PASSED
        assert cases[prefix + "sums prices"].file == "src/cart.vitest.test.js"
        assert cases[prefix + "fails on purpose"].duration_ms == 6  # time="0.005506"

    def test_jest_junit_repeats_the_name_as_classname(self) -> None:
        cases = by_key(parse_report((FIXTURES / "jest.xml").read_bytes()))

        assert len(cases) == 4
        failing = cases["cart total::cart total fails on purpose"]
        assert failing.status is Status.FAILED
        assert failing.file is None
        assert failing.message is not None
        assert failing.message.startswith("Error: expect(received).toBe(expected)")


class TestDialectEdges:
    def test_root_can_be_a_single_testsuite(self) -> None:
        xml = b'<testsuite name="suite"><testcase name="a" time="1.5"/></testsuite>'
        (case,) = parse_report(xml)
        assert (case.key, case.suite, case.duration_ms) == ("suite::a", "suite", 1500)

    def test_nested_suites_use_the_nearest_name(self) -> None:
        xml = (
            b"<testsuites><testsuite name='outer'><testsuite name='inner'>"
            b"<testcase name='a'/></testsuite><testcase name='b'/></testsuite></testsuites>"
        )
        assert [case.key for case in parse_report(xml)] == ["inner::a", "outer::b"]

    def test_error_wins_over_failure_on_the_same_testcase(self) -> None:
        xml = (
            b"<testsuite><testcase name='a'>"
            b"<failure/><error message='boom'/>"
            b"</testcase></testsuite>"
        )
        (case,) = parse_report(xml)
        assert (case.status, case.message) == (Status.ERROR, "boom")

    def test_explicit_file_attribute_is_used(self) -> None:
        xml = b'<testsuite><testcase name="t" classname="t" file="spec\\cart.test.ts"/></testsuite>'
        (case,) = parse_report(xml)
        assert (case.file, case.key) == ("spec/cart.test.ts", "spec/cart.test.ts::t")

    @pytest.mark.parametrize("raw", ["0,5", "abc", "-1", "nan", "inf", ""])
    def test_unusable_durations_are_unknown_not_guessed(self, raw: str) -> None:
        xml = f'<testsuite><testcase name="a" time="{raw}"/></testsuite>'.encode()
        assert parse_report(xml)[0].duration_ms is None

    def test_long_messages_are_truncated(self) -> None:
        failure = f'<failure message="{"x" * 5000}"/>'
        xml = f'<testsuite><testcase name="a">{failure}</testcase></testsuite>'
        message = parse_report(xml.encode())[0].message
        assert message is not None and len(message) == MAX_MESSAGE_CHARS


class TestRejectedInput:
    def test_not_xml(self) -> None:
        with pytest.raises(ReportError, match="not well-formed"):
            parse_report(b"this is not xml")

    def test_wrong_root(self) -> None:
        with pytest.raises(ReportError, match="expected <testsuites>"):
            parse_report(b"<html><body/></html>")

    def test_testcase_without_name(self) -> None:
        with pytest.raises(ReportError, match="without a name"):
            parse_report(b"<testsuite><testcase classname='x'/></testsuite>")

    def test_entity_expansion_is_refused(self) -> None:
        billion_laughs = b"""<?xml version="1.0"?>
        <!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>
        <testsuite><testcase name="&lol2;"/></testsuite>"""
        with pytest.raises(ReportError, match="unsafe"):
            parse_report(billion_laughs)

    def test_no_reports(self) -> None:
        with pytest.raises(ReportError, match="no reports"):
            parse_reports([])


class TestCollapse:
    def case(self, status: Status, duration: int | None, message: str | None = None) -> CaseResult:
        return CaseResult("k", "k", None, None, status, duration, message)

    def test_keeps_worst_status_and_its_message_and_sums_time(self) -> None:
        (merged,) = collapse(
            [self.case(Status.FAILED, 10, "first try"), self.case(Status.PASSED, 5)]
        )
        assert merged.status is Status.FAILED
        assert merged.message == "first try"
        assert merged.duration_ms == 15
        assert merged.occurrences == 2

    def test_unknown_durations_do_not_become_zero(self) -> None:
        (merged,) = collapse([self.case(Status.PASSED, None), self.case(Status.PASSED, None)])
        assert merged.duration_ms is None


class TestDigest:
    def test_order_of_reports_does_not_matter(self) -> None:
        assert digest_reports([b"a", b"b"]) == digest_reports([b"b", b"a"])

    def test_different_report_sets_differ(self) -> None:
        assert digest_reports([b"a"]) != digest_reports([b"a", b"b"])
