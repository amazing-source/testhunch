"""The Jest form of a selection, checked against real Jest runs (tests/fixtures/select/jest)."""

from __future__ import annotations

from pathlib import Path

from testhunch.junit import parse_report
from testhunch.runners import jest_ignore_pattern

SAMPLE = Path(__file__).parent / "fixtures" / "select" / "jest"


def lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line]


def test_the_pattern_leaves_out_exactly_what_it_says_in_a_real_jest_run() -> None:
    # full.xml: every test (Jest 30.5.1, jest-junit 17.0.0, JEST_JUNIT_ADD_FILE_ATTRIBUTE=true).
    # selected.xml: `--testPathIgnorePatterns "$(cat ignore-pattern.txt)"`, run by run.sh.
    cases = parse_report((SAMPLE / "full.xml").read_bytes())
    files = {case.key: case.file for case in cases}
    left_out = lines(SAMPLE / "left-out.txt")

    skip = jest_ignore_pattern(
        left_out, set(files) - set(left_out), files, lines(SAMPLE / "changed-paths.txt")
    )

    assert skip.pattern == (SAMPLE / "ignore-pattern.txt").read_text().strip()
    selected = {case.key for case in parse_report((SAMPLE / "selected.xml").read_bytes())}
    assert selected == set(files) - set(skip.left_out)
    assert set(skip.left_out) == {
        "src/billing/cart.test.js::cart total sums prices",
        "src/pricing.test.js:: discount",
    }
    # src/cart/cart.test.js has the same file name as src/billing/cart.test.js, and one of its
    # tests is kept; src/discounts.test.js changed. Both ran.
    assert "src/cart/cart.test.js::cart total sums prices" in selected
    assert "src/discounts.test.js::discounts none" in selected


def test_tests_without_a_known_file_cannot_be_left_out() -> None:
    # jest-junit writes no file attribute unless JEST_JUNIT_ADD_FILE_ATTRIBUTE=true.
    key = "cart total::cart total sums prices"
    assert jest_ignore_pattern([key], [], {key: None}) == jest_ignore_pattern([], [], {})


def test_absolute_paths_are_not_anchored_on_the_root_dir() -> None:
    files = {"a": "/work/src/a.test.js", "b": "C:\\work\\src\\b.test.js"}
    assert jest_ignore_pattern(["a", "b"], [], files).left_out == ()


def test_a_changed_file_under_a_package_directory_counts_as_changed() -> None:
    # Jest's rootDir can be a subdirectory of the repository, e.g. packages/shop.
    files = {"a": "src/a.test.js"}
    skip = jest_ignore_pattern(["a"], [], files, ["packages/shop/src/a.test.js"])
    assert (skip.pattern, skip.left_out) == ("/node_modules/", ())


def test_file_paths_are_escaped_for_javascript_regexps() -> None:
    files = {"a": "src/[id]/page (1).test.ts"}
    skip = jest_ignore_pattern(["a"], [], files)
    assert skip.pattern == r"<rootDir>/(?:src/\[id\]/page \(1\)\.test\.ts)$|/node_modules/"
