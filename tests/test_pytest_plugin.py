"""The pytest plugin, checked with real pytest sessions (pytester) and real JUnit XML reports."""

from __future__ import annotations

from pathlib import Path

import pytest

from testhunch.junit import parse_report

SHOP_TESTS = """
import pytest

def test_total():
    pass

@pytest.mark.parametrize("n", [1, 2])
def test_quantity(n):
    pass

class TestDiscounts:
    def test_ten_percent(self):
        pass
"""


def keys_in(report: Path) -> set[str]:
    return {case.key for case in parse_report(report.read_bytes())}


@pytest.fixture
def shop(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makepyfile(**{"tests/test_shop": SHOP_TESTS})
    return pytester


def test_without_the_option_nothing_is_deselected(shop: pytest.Pytester) -> None:
    shop.runpytest("-p", "testhunch.pytest_plugin").assert_outcomes(passed=4)


def test_listed_keys_are_deselected_and_every_other_test_runs(shop: pytest.Pytester) -> None:
    full = shop.path / "full.xml"
    shop.runpytest(f"--junitxml={full}").assert_outcomes(passed=4)
    recorded = keys_in(full)
    assert "tests.test_shop::test_quantity[2]" in recorded
    assert "tests.test_shop.TestDiscounts::test_ten_percent" in recorded

    skip = shop.path / "skip.txt"
    skip.write_text(
        "tests.test_shop::test_quantity[2]\n"
        "\n"
        "tests.test_shop.TestDiscounts::test_ten_percent\n"
        "tests.test_gone::test_deleted_long_ago\n"  # listed but no longer exists: ignored
    )
    selected = shop.path / "selected.xml"
    result = shop.runpytest(
        "-p", "testhunch.pytest_plugin", f"--testhunch-skip={skip}", f"--junitxml={selected}"
    )

    result.assert_outcomes(passed=2, deselected=2)
    assert keys_in(selected) == {"tests.test_shop::test_total", "tests.test_shop::test_quantity[1]"}


def test_keys_follow_the_junit_prefix(shop: pytest.Pytester) -> None:
    full = shop.path / "full.xml"
    shop.runpytest(f"--junitxml={full}", "--junitprefix=py312").assert_outcomes(passed=4)
    assert "py312.tests.test_shop::test_total" in keys_in(full)

    skip = shop.path / "skip.txt"
    skip.write_text("py312.tests.test_shop::test_total\n")
    result = shop.runpytest(
        "-p", "testhunch.pytest_plugin", f"--testhunch-skip={skip}", "--junitprefix=py312"
    )
    result.assert_outcomes(passed=3, deselected=1)


def test_a_missing_skip_file_is_a_usage_error(shop: pytest.Pytester) -> None:
    result = shop.runpytest("-p", "testhunch.pytest_plugin", "--testhunch-skip=nope.txt")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*testhunch: cannot read the skip list nope.txt*"])
