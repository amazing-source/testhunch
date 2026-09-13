"""The Vitest form of a selection, checked against real Vitest runs (tests/fixtures/select)."""

from __future__ import annotations

from pathlib import Path

import pytest

from testhunch.junit import parse_report
from testhunch.models import Status
from testhunch.runners import parse_vitest_list, vitest_skip

SAMPLE = Path(__file__).parent / "fixtures" / "select" / "vitest"
CART = "src/cart.test.js::cart total > "


def lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line]


def test_the_pattern_filters_out_exactly_what_it_says_in_a_real_vitest_run() -> None:
    # full.xml and vitest-list.json: every test (Vitest 5.0.0). selected.xml: `-t "$(cat ...)"`.
    left_out = lines(SAMPLE / "left-out.txt")
    skip = vitest_skip(left_out, parse_vitest_list((SAMPLE / "vitest-list.json").read_text()))

    assert skip.pattern == (SAMPLE / "test-name-pattern.txt").read_text().strip()
    full = {case.key: case.status for case in parse_report((SAMPLE / "full.xml").read_bytes())}
    selected = parse_report((SAMPLE / "selected.xml").read_bytes())
    # Vitest reports the tests -t filters out as skipped, so compare statuses, not keys.
    assert {case.key for case in selected} == set(full)
    assert {case.key for case in selected if case.status is Status.SKIPPED} == set(skip.left_out)
    # "cart total > sums prices" also exists in billing.test.js, so it ran in both files.
    assert f"{CART}sums prices" in set(left_out) - set(skip.left_out)
    assert all(s is not Status.SKIPPED for k, s in full.items())


def test_list_entries_carry_the_file_and_the_full_name() -> None:
    listed = parse_vitest_list('[{"name": "a > b", "file": "C:\\\\work\\\\src\\\\x.test.ts"}]')
    assert listed == [("C:/work/src/x.test.ts", "a > b")]


def test_something_else_than_the_list_json_is_refused() -> None:
    with pytest.raises(ValueError, match="vitest list --json"):
        parse_vitest_list('{"name": "a"}')


def test_a_test_missing_from_the_current_code_is_not_aimed_at() -> None:
    skip = vitest_skip([f"{CART}removed"], [("/work/src/cart.test.js", "cart total > kept")])
    assert (skip.pattern, skip.left_out) == (".*", ())


def test_a_duplicate_full_name_in_the_same_file_keeps_both_running() -> None:
    listed = [("/work/src/cart.test.js", "cart total > twice")] * 2
    assert vitest_skip([f"{CART}twice"], listed).left_out == ()


def test_names_are_escaped_for_javascript_regexps() -> None:
    name = "cart total > costs $5 (a/b) [x]?"
    skip = vitest_skip([f"src/cart.test.js::{name}"], [("/w/src/cart.test.js", name)])
    assert skip.pattern == r"^(?!(?:cart total > costs \$5 \(a\/b\) \[x\]\?)$)"
