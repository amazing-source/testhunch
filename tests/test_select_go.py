"""The Go form of a selection, checked against real go test runs (tests/fixtures/select/go)."""

from __future__ import annotations

from pathlib import Path

from testhunch.junit import parse_report
from testhunch.runners import go_skip, parse_go_test_list

SAMPLE = Path(__file__).parent / "fixtures" / "select" / "go"
CART = "example.com/shop/cart"


def keys_in(report: Path) -> set[str]:
    return {case.key for case in parse_report(report.read_bytes())}


def test_the_pattern_leaves_out_exactly_what_it_says_in_a_real_go_run() -> None:
    # full.xml: every test ran. go-test-list.txt: `go test -list '.*' ./...` on the same code.
    # selected.xml: `go test ./... -skip "$(cat skip-pattern.txt)"`, run by run.sh.
    known = keys_in(SAMPLE / "full.xml")
    left_out = set((SAMPLE / "left-out.txt").read_text().split())
    test_list = parse_go_test_list((SAMPLE / "go-test-list.txt").read_text())

    skip = go_skip(left_out, known - left_out, test_list)

    assert skip.pattern == (SAMPLE / "skip-pattern.txt").read_text().strip()
    assert keys_in(SAMPLE / "selected.xml") == known - set(skip.left_out)
    # TestTotalSumsPrices also exists in package billing: -skip would leave both out, so it runs.
    assert f"{CART}::TestTotalSumsPrices" in left_out - set(skip.left_out)
    # Everything else asked for was left out, including TestInvoice and both its subtests.
    assert set(skip.left_out) == left_out - {f"{CART}::TestTotalSumsPrices"}


def test_go_test_list_output_is_read_per_package() -> None:
    text = (
        "TestA\nTestB\nok  \texample.com/shop/cart\t0.008s\n"
        "?   \texample.com/shop/docs\t[no test files]\n"
        "TestC\nok  \texample.com/shop/pricing\t(cached)\n"
        "TestOrphan\n"  # no package line after it
    )
    assert parse_go_test_list(text) == {
        "example.com/shop/cart": {"TestA", "TestB"},
        "example.com/shop/docs": set(),
        "example.com/shop/pricing": {"TestC"},
    }


def listing(**packages: str) -> dict[str, set[str]]:
    return {f"example.com/shop/{name}": set(tests.split()) for name, tests in packages.items()}


def test_a_test_missing_from_the_current_code_is_not_aimed_at() -> None:
    skip = go_skip([f"{CART}::TestRemoved"], [], listing(cart="TestTotal"))
    assert (skip.pattern, skip.left_out) == ("", ())


def test_a_parent_with_a_kept_subtest_runs_and_only_its_left_out_subtests_are_skipped() -> None:
    skip = go_skip(
        [f"{CART}::TestQuantities", f"{CART}::TestQuantities/one"],
        [f"{CART}::TestQuantities/two"],
        listing(cart="TestQuantities"),
    )
    assert skip.pattern == "^TestQuantities$/^one$"
    assert skip.left_out == (f"{CART}::TestQuantities/one",)


def test_no_test_is_left_out_in_a_package_whose_test_files_changed() -> None:
    # A subtest added to a left-out test in this change would be skipped with its parent.
    left_out = [f"{CART}::TestTotal", "example.com/shop/pricing::TestDiscount"]
    changed = ["cart/cart_test.go", "cart/cart.go", "README.md"]
    skip = go_skip(left_out, [], listing(cart="TestTotal", pricing="TestDiscount"), changed)
    assert skip.pattern == "^TestDiscount$"


def test_a_changed_test_file_at_the_module_root_turns_go_skipping_off() -> None:
    skip = go_skip([f"{CART}::TestTotal"], [], listing(cart="TestTotal"), ["shop_test.go"])
    assert (skip.pattern, skip.left_out) == ("", ())


def test_names_are_quoted_like_regexp_quotemeta() -> None:
    key = f"{CART}::TestPrices/case_(1).a+b"
    skip = go_skip([key], [], listing(cart="TestPrices"))
    assert skip.pattern == r"^TestPrices$/^case_\(1\)\.a\+b$"
