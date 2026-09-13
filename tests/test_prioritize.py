from __future__ import annotations

from testhunch.models import CaseHistory
from testhunch.prioritize import rank, stem


def history(
    key: str,
    file: str | None = None,
    failures: int = 0,
    executions: int = 10,
    runs_since_failure: int | None = None,
) -> CaseHistory:
    return CaseHistory(key, file, failures, executions, runs_since_failure)


def test_stem_drops_directories_and_every_extension() -> None:
    assert stem("src/lib/carte-grise.test.ts") == "carte-grise"
    assert stem("C:\\repo\\Cart.py") == "cart"


def test_tests_for_a_changed_file_come_first() -> None:
    ranked = rank(
        [history("tests/test_payment.py::test_ok"), history("tests/test_cart.py::test_total")],
        changed_paths=["src/shop/cart.py"],
    )
    assert ranked[0].key == "tests/test_cart.py::test_total"
    assert ranked[0].reasons == ("matches changed file cart",)


def test_recent_failures_outrank_old_ones() -> None:
    ranked = rank(
        [
            history("old", failures=1, runs_since_failure=5),
            history("recent", failures=1, runs_since_failure=0),
        ]
    )
    assert [r.key for r in ranked] == ["recent", "old"]
    assert ranked[0].reasons == ("failed in the latest run", "failed 1 of 10 runs")


def test_generic_and_tiny_stems_do_not_match_everything() -> None:
    ranked = rank(
        [history("tests/test_io.py::test_index")], ["pkg/__init__.py", "io.py", "index.ts"]
    )
    assert ranked[0].score == 0
    assert ranked[0].reasons == ()


def test_ties_are_broken_by_key_so_output_is_stable() -> None:
    ranked = rank([history("b"), history("a"), history("c")])
    assert [r.key for r in ranked] == ["a", "b", "c"]
