"""The Surefire form of a selection, checked against real Maven runs (tests/fixtures/select)."""

from __future__ import annotations

from pathlib import Path

from testhunch.junit import parse_reports
from testhunch.runners import surefire_exclusions

SAMPLE = Path(__file__).parent / "fixtures" / "select" / "surefire"
SHOP = "com.example.shop.CartTest"


def keys_in(reports: Path) -> set[str]:
    cases, _ = parse_reports(path.read_bytes() for path in sorted(reports.glob("TEST-*.xml")))
    return {case.key for case in cases}


def test_the_exclusions_leave_out_exactly_what_they_say_in_a_real_maven_run() -> None:
    # full/: every test ran (Surefire 3.6.0, JUnit 6.1.3). selected/: `mvn test -Dtest=...` with
    # exclusions.txt, run by run.sh.
    known = keys_in(SAMPLE / "full")
    left_out = set((SAMPLE / "left-out.txt").read_text().split())

    skip = surefire_exclusions(left_out, known - left_out)

    assert skip.value == (SAMPLE / "exclusions.txt").read_text().strip()
    assert keys_in(SAMPLE / "selected") == known - set(skip.left_out)
    # priceIsOdd(int)[2] is kept, and Surefire can only leave out every invocation at once.
    assert f"{SHOP}::priceIsOdd(int)[1]" in left_out - set(skip.left_out)
    # The same method name in com.example.billing.CartTest, and sumsPricesTwice, still ran.
    assert "com.example.billing.CartTest::sumsPrices" in keys_in(SAMPLE / "selected")
    assert f"{SHOP}::sumsPricesTwice" in keys_in(SAMPLE / "selected")


def test_a_parameterized_method_is_left_out_when_all_its_invocations_are() -> None:
    left_out = [f"{SHOP}::priceIsOdd(int)[1]", f"{SHOP}::priceIsOdd(int)[2]"]
    skip = surefire_exclusions(left_out, [f"{SHOP}::sumsPrices"])
    assert skip.value == f"!{SHOP}#priceIsOdd"
    assert set(skip.left_out) == set(left_out)


def test_an_overload_that_is_kept_keeps_the_method_name_running() -> None:
    skip = surefire_exclusions([f"{SHOP}::total(int)"], [f"{SHOP}::total(String)"])
    assert (skip.value, skip.left_out) == ("", ())


def test_nothing_is_left_out_in_a_class_whose_source_changed() -> None:
    left_out = [f"{SHOP}::sumsPrices", f"{SHOP}$Discounts::keepsTotal", "com.example.shop.Other::a"]
    changed = ["src/test/java/com/example/shop/CartTest.java"]
    skip = surefire_exclusions(left_out, [], changed)
    assert skip.value == "!com.example.shop.Other#a"


def test_a_same_named_class_file_in_another_package_does_not_count_as_changed() -> None:
    changed = ["src/test/java/com/example/billing/CartTest.java", "CartTest.java.orig"]
    skip = surefire_exclusions([f"{SHOP}::sumsPrices"], [], changed)
    assert skip.value == f"!{SHOP}#sumsPrices"


def test_report_names_that_are_not_java_method_names_are_not_aimed_at() -> None:
    # e.g. a JUnit 5 @DisplayName written into the report by a phrased reporter
    skip = surefire_exclusions([f"{SHOP}::sums prices", f"{SHOP}::"], [])
    assert (skip.value, skip.left_out) == ("", ())
