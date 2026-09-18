from __future__ import annotations

from pathlib import Path

import pytest

from testhunch.junit import (
    LONGEST_DURATION_MS,
    MAX_MESSAGE_CHARS,
    ReportError,
    collapse,
    digest_reports,
    parse_report,
    parse_reports,
)
from testhunch.models import SEVERITY, CaseResult, Status

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

    def test_gotestsum(self) -> None:
        cases = by_key(parse_report((FIXTURES / "gotestsum.xml").read_bytes()))
        cart = "example.com/shop/cart::"

        assert len(cases) == 9
        assert cases[cart + "TestTotalSumsPrices"].status is Status.PASSED
        assert cases[cart + "TestTotalFailsOnPurpose"].status is Status.FAILED
        assert cases[cart + "TestSkipped"].status is Status.SKIPPED
        assert cases["example.com/shop/pricing::TestDiscount"].status is Status.PASSED

    def test_gotestsum_subtests_are_cases_and_fail_their_parents(self) -> None:
        cases = by_key(parse_report((FIXTURES / "gotestsum.xml").read_bytes()))
        cart = "example.com/shop/cart::"

        # t.Run("single item") is reported as "TestQuantities/single_item".
        assert cases[cart + "TestQuantities/single_item"].status is Status.PASSED
        assert cases[cart + "TestQuantities/nested/zero_quantity"].status is Status.FAILED
        assert cases[cart + "TestQuantities/nested"].status is Status.FAILED
        assert cases[cart + "TestQuantities"].status is Status.FAILED

    def test_gotestsum_import_path_is_not_a_file_path(self) -> None:
        # classname is the package import path, "example.com/shop/cart": a directory at best,
        # and the report never says which file a test is in.
        cases = parse_report((FIXTURES / "gotestsum.xml").read_bytes())
        assert {case.file for case in cases} == {None}

    def test_gotestsum_rerun_fails_repeats_the_testcase(self) -> None:
        report = (FIXTURES / "gotestsum-rerun-fails.xml").read_bytes()
        cases = by_key(list(collapse(parse_report(report))))

        # Failed, then passed when rerun. Nothing marks the second entry as a rerun except the
        # repetition itself, so collapsing keeps the worst attempt and marks the result flaky.
        flaky = cases["example.com/shop/pricing::TestFlakyFirstAttempt"]
        assert (flaky.status, flaky.attempts, flaky.flaky) == (Status.FAILED, 2, True)
        always = cases["example.com/shop/cart::TestTotalFailsOnPurpose"]
        assert (always.status, always.attempts, always.flaky) == (Status.FAILED, 3, False)
        assert cases["example.com/shop/pricing::TestDiscount"].attempts == 1

    def surefire_run(self) -> dict[str, CaseResult]:
        # Surefire writes one report per test class; together they are one run.
        reports = sorted((FIXTURES / "surefire").glob("TEST-*.xml"))
        assert len(reports) == 2
        cases, _ = parse_reports(path.read_bytes() for path in reports)
        return by_key(list(cases))

    def test_surefire(self) -> None:
        cases = self.surefire_run()
        cart = "com.example.shop.CartTest::"

        assert len(cases) == 9
        assert cases[cart + "sumsPrices"].status is Status.PASSED
        assert cases[cart + "failsOnPurpose"].status is Status.FAILED
        assert cases[cart + "throwsUnexpectedly"].status is Status.ERROR
        assert cases[cart + "skippedCase"].status is Status.SKIPPED
        assert cases[cart + "priceIsOdd(int)[1]"].status is Status.PASSED
        assert cases[cart + "priceIsOdd(int)[2]"].status is Status.FAILED
        nested = cases["com.example.shop.CartTest$Discounts::keepsTotalWithoutDiscount"]
        assert nested.status is Status.PASSED
        assert {case.file for case in cases.values()} == {None}

    def test_surefire_reruns_stay_inside_one_testcase(self) -> None:
        cases = self.surefire_run()

        # Failed, then passed when rerun: no <failure>, only a <flakyFailure>. It passed, flakily.
        flaky = cases["com.example.shop.FlakyTest::failsOnFirstAttempt"]
        assert (flaky.status, flaky.flaky, flaky.message) == (Status.PASSED, True, None)
        assert flaky.attempts == 2
        # Same with an unexpected exception on the first attempt: <flakyError>.
        errored = cases["com.example.shop.FlakyTest::throwsOnFirstAttempt"]
        assert (errored.status, errored.flaky, errored.message) == (Status.PASSED, True, None)
        assert errored.attempts == 2

        # Failed every attempt (rerunFailingTestsCount=2): <failure>, then two <rerunFailure>.
        failing = cases["com.example.shop.CartTest::failsOnPurpose"]
        assert (failing.status, failing.occurrences, failing.flaky) == (Status.FAILED, 1, False)
        assert failing.attempts == 3
        throwing = cases["com.example.shop.CartTest::throwsUnexpectedly"]  # <rerunError> twice
        assert (throwing.status, throwing.flaky, throwing.attempts) == (Status.ERROR, False, 3)
        assert cases["com.example.shop.CartTest::sumsPrices"].attempts == 1
        assert failing.message == "empty cart on purpose ==> expected: <1> but was: <0>"

    def test_nextest(self) -> None:
        cases = by_key(parse_report((FIXTURES / "nextest.xml").read_bytes()))

        # The #[ignore] test is not in the report at all, although nextest counts it as skipped.
        assert len(cases) == 6
        assert cases["shop::tests::sums_prices"].status is Status.PASSED
        assert cases["shop::tests::panics_as_expected"].status is Status.PASSED
        assert cases["shop::tests::nested::keeps_total_for_one_item"].status is Status.PASSED
        assert cases["shop::checkout::checkout_total"].status is Status.PASSED  # tests/checkout.rs
        assert {case.file for case in cases.values()} == {None}

    def test_nextest_retries_stay_inside_one_testcase(self) -> None:
        cases = by_key(parse_report((FIXTURES / "nextest.xml").read_bytes()))

        flaky = cases["shop::tests::flaky_first_attempt"]
        assert (flaky.status, flaky.flaky, flaky.message) == (Status.PASSED, True, None)
        assert flaky.attempts == 2  # nextest: "FLAKY 2/3"

        failing = cases["shop::tests::fails_on_purpose"]
        assert (failing.status, failing.occurrences, failing.flaky) == (Status.FAILED, 1, False)
        assert failing.attempts == 3  # nextest: "TRY 3 FAIL"
        assert failing.message is not None
        assert failing.message.startswith("thread 'tests::fails_on_purpose' (256) panicked at")
        passing = cases["shop::tests::sums_prices"]
        assert (passing.flaky, passing.attempts) == (False, 1)

    def test_pytest_rerunfailures_writes_rerun_attempts_as_empty_testcases(self) -> None:
        cases = by_key(parse_report((FIXTURES / "pytest-rerunfailures.xml").read_bytes()))

        # 9 <testcase> elements in a suite that declares tests="4": one result per test.
        assert len(cases) == 4
        failing = cases["tests.test_shop::test_fails_on_purpose"]
        assert (failing.status, failing.attempts, failing.flaky) == (Status.FAILED, 3, False)
        assert failing.message is not None
        assert failing.message.startswith("AssertionError: fails on every attempt")
        erroring = cases["tests.test_shop::test_errors_on_purpose"]
        assert (erroring.status, erroring.attempts, erroring.flaky) == (Status.FAILED, 3, False)
        # Failed once, passed when rerun: before ADR 0008 this read as two passes.
        flaky = cases["tests.test_shop::test_flaky_first_attempt"]
        assert (flaky.status, flaky.attempts, flaky.flaky) == (Status.PASSED, 2, True)
        passing = cases["tests.test_shop::test_passes"]
        assert (passing.status, passing.attempts, passing.flaky) == (Status.PASSED, 1, False)


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

    @pytest.mark.parametrize(
        ("classname", "file"),
        [
            ("src\\cart.test.mts", "src/cart.test.mts"),
            ("cart/total", None),  # a Jest describe block named with a slash
            ("github.com/acme/shop", None),  # a Go import path
        ],
    )
    def test_classname_is_a_file_only_with_a_source_extension(
        self, classname: str, file: str | None
    ) -> None:
        xml = f'<testsuite><testcase name="t" classname="{classname}"/></testsuite>'.encode()
        assert parse_report(xml)[0].file == file

    @pytest.mark.parametrize("raw", ["0,5", "abc", "-1", "nan", "inf", ""])
    def test_unusable_durations_are_unknown_not_guessed(self, raw: str) -> None:
        xml = f'<testsuite><testcase name="a" time="{raw}"/></testsuite>'.encode()
        assert parse_report(xml)[0].duration_ms is None

    def test_repeated_testcases_are_only_read_as_reruns_when_the_suite_declares_fewer_tests(
        self,
    ) -> None:
        entries = b"<testcase name='a'/><testcase name='a'><failure/></testcase></testsuite>"
        declared = b"<testsuite tests='1'>" + entries
        undeclared = b"<testsuite>" + entries
        counted = b"<testsuite tests='2'>" + entries

        (rerun,) = parse_report(declared)
        assert (rerun.status, rerun.attempts, rerun.flaky) == (Status.FAILED, 2, False)
        # Without the mismatch, the entries stay separate results, for collapse to merge.
        assert len(parse_report(undeclared)) == 2
        assert len(parse_report(counted)) == 2

    def test_earlier_entries_with_an_outcome_are_not_read_as_reruns(self) -> None:
        # e.g. a failed test body and an error in fixture teardown, reported as two entries
        xml = (
            b"<testsuite tests='1'><testcase name='a'><failure/></testcase>"
            b"<testcase name='a'><error/></testcase></testsuite>"
        )
        assert [c.status for c in parse_report(xml)] == [Status.FAILED, Status.ERROR]

    def test_a_flaky_marker_next_to_a_failure_does_not_make_it_flaky(self) -> None:
        # Not seen from any runner: an outcome element decides the status, and a failed result is
        # not a pass that flaked.
        xml = b"<testsuite><testcase name='a'><failure/><flakyFailure/></testcase></testsuite>"
        (case,) = parse_report(xml)
        assert (case.status, case.flaky) == (Status.FAILED, False)

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

    @pytest.mark.parametrize(
        "statuses",
        [
            (Status.FAILED, Status.PASSED),
            (Status.PASSED, Status.ERROR, Status.ERROR),
            (Status.ERROR, Status.FAILED, Status.PASSED),
        ],
    )
    def test_a_pass_and_a_failure_in_one_run_is_flaky_and_keeps_the_worst_status(
        self, statuses: tuple[Status, ...]
    ) -> None:
        (merged,) = collapse([self.case(status, 1) for status in statuses])
        assert merged.flaky
        assert merged.status is max(statuses, key=SEVERITY.__getitem__)

    @pytest.mark.parametrize(
        "statuses",
        [
            (Status.FAILED, Status.FAILED),
            (Status.FAILED, Status.ERROR),
            (Status.SKIPPED, Status.FAILED),
            (Status.SKIPPED, Status.PASSED),
            (Status.PASSED, Status.PASSED),
        ],
    )
    def test_without_both_a_pass_and_a_failure_it_is_not_flaky(
        self, statuses: tuple[Status, ...]
    ) -> None:
        (merged,) = collapse([self.case(status, 1) for status in statuses])
        assert not merged.flaky

    def test_attempts_add_up(self) -> None:
        retried = CaseResult("k", "k", None, None, Status.FAILED, 1, None, attempts=3)
        (merged,) = collapse([retried, self.case(Status.FAILED, 1)])
        assert merged.attempts == 4

    def test_a_flaky_entry_keeps_the_result_flaky(self) -> None:
        retried = CaseResult("k", "k", None, None, Status.PASSED, 1, None, flaky=True)
        (merged,) = collapse([retried, self.case(Status.PASSED, 1)])
        assert merged.flaky


class TestDigest:
    def test_order_of_reports_does_not_matter(self) -> None:
        assert digest_reports([b"a", b"b"]) == digest_reports([b"b", b"a"])

    def test_different_report_sets_differ(self) -> None:
        assert digest_reports([b"a"]) != digest_reports([b"a", b"b"])


def test_a_duration_no_store_can_hold_is_unknown_not_a_crash() -> None:
    """`time="1e300"` once became a 304-digit integer that neither database accepts, and failed
    the whole ingestion. Past Postgres' INTEGER it is not a duration anyone measured: unknown."""
    xml = (
        b"<testsuite name='s'>"
        b"<testcase classname='c' name='longest' time='2147483.647'/>"
        b"<testcase classname='c' name='absurd' time='1e300'/>"
        b"</testsuite>"
    )
    longest, absurd = parse_report(xml)

    assert longest.duration_ms == LONGEST_DURATION_MS
    assert absurd.duration_ms is None


def test_a_report_nested_thousands_of_suites_deep_is_read_like_any_other() -> None:
    depth = 5000
    xml = (
        b"<testsuites>"
        + b"<testsuite name='s'>" * depth
        + b"<testcase name='t'/>"
        + b"</testsuite>" * depth
        + b"</testsuites>"
    )
    (case,) = parse_report(xml)

    # Without a classname the case is grouped under its suite, carried down five thousand levels.
    assert case.key == "s::t"


def test_nested_suites_keep_their_order_and_their_own_names() -> None:
    xml = (
        b"<testsuites><testsuite name='outer'>"
        b"<testcase name='own'/>"
        b"<testsuite name='inner'><testcase name='nested'/></testsuite>"
        b"<testsuite><testcase name='unnamed'/></testsuite>"
        b"</testsuite></testsuites>"
    )

    cases = parse_report(xml)

    # A nested suite's cases come where it appears, a suite's own at its end, and a suite without
    # a name lends its cases the name of the one around it.
    assert [case.key for case in cases] == ["inner::nested", "outer::unnamed", "outer::own"]
