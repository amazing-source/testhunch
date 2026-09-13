"""The cargo-nextest form of a selection, checked against real runs (tests/fixtures/select)."""

from __future__ import annotations

from pathlib import Path

from testhunch.junit import parse_report
from testhunch.runners import nextest_filterset

SAMPLE = Path(__file__).parent / "fixtures" / "select" / "nextest"


def test_the_filterset_leaves_out_exactly_what_it_says_in_a_real_nextest_run() -> None:
    # full.xml: every test ran (cargo-nextest 0.9.144). selected.xml: `-E "$(cat filterset.txt)"`.
    cases = parse_report((SAMPLE / "full.xml").read_bytes())
    known = {case.key for case in cases}
    left_out = set((SAMPLE / "left-out.txt").read_text().split())

    skip = nextest_filterset(left_out, {case.key: case.suite for case in cases})

    assert skip.expression == (SAMPLE / "filterset.txt").read_text().strip()
    assert set(skip.left_out) == left_out
    selected = {case.key for case in parse_report((SAMPLE / "selected.xml").read_bytes())}
    assert selected == known - left_out
    # The same test names in the binary shop::billing still ran.
    assert {"shop::billing::checkout_total", "shop::billing::tests::sums_prices"} <= selected


def test_the_binary_id_comes_from_the_suite_not_from_splitting_the_key() -> None:
    # "shop::checkout::checkout_total" could be binary "shop" and test "checkout::checkout_total".
    skip = nextest_filterset(
        ["shop::checkout::checkout_total"], {"shop::checkout::checkout_total": "shop::checkout"}
    )
    assert skip.expression == "not ((binary_id(=shop::checkout) & test(=checkout_total)))"


def test_a_test_whose_suite_is_unknown_or_inconsistent_is_not_aimed_at() -> None:
    skip = nextest_filterset(
        ["shop::tests::a", "shop::tests::b"], {"shop::tests::a": None, "shop::tests::b": "other"}
    )
    assert (skip.expression, skip.left_out) == ("all()", ())


def test_equality_matcher_escapes_are_applied() -> None:
    # Custom test harnesses can name tests freely; the DSL reference lists these escapes.
    key = "crate::case(a,b)/c\\d"
    skip = nextest_filterset([key], {key: "crate"})
    assert skip.expression == r"not ((binary_id(=crate) & test(=case(a\,b\)\/c\\d)))"
