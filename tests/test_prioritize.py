"""The ranking the study kept (docs/adr/0014, 0015)."""

from __future__ import annotations

import random

import pytest

from testhunch.models import CaseHistory, History
from testhunch.prioritize import ALPHA, add_failure, location, priority_at, rank


def case(
    key: str,
    last_failure: int | None = None,
    mean_duration_ms: float | None = 10.0,
    file: str | None = None,
) -> CaseHistory:
    priority = 0.0 if last_failure is None else ALPHA
    failures = 0 if last_failure is None else 1
    return CaseHistory(key, file, 10, failures, last_failure, priority, mean_duration_ms)


def keys(history: History, changed: tuple[str, ...] = (), seed: str = "") -> list[str]:
    return [ranked.key for ranked in rank(history, changed, seed)]


def test_the_priority_follows_rtptorrents_recurrence_whatever_order_failures_arrive_in() -> None:
    rng = random.Random(5)
    builds = 12
    failed = [rng.random() < 0.4 for _ in range(builds)]
    naive = 0.0
    for build in range(builds):
        # P(n) = alpha F(n) + (1 - alpha) P(n - 1) (Mattis et al., section 4).
        naive = ALPHA * failed[build] + (1 - ALPHA) * naive
    last_failure: int | None = None
    priority = 0.0
    arrival = [build for build in range(builds) if failed[build]]
    rng.shuffle(arrival)  # runs of earlier builds may arrive after later ones
    for build in arrival:
        last_failure, priority = add_failure(last_failure, priority, build)

    assert last_failure == max(arrival)
    assert priority_at(last_failure, priority, builds) == pytest.approx(naive, abs=1e-12)


def test_a_second_failure_in_the_same_build_changes_nothing() -> None:
    once = add_failure(None, 0.0, 3)

    assert add_failure(*once, 3) == once == (3, ALPHA)


def test_a_test_never_failed_has_no_priority() -> None:
    assert priority_at(None, 0.0, 7) == 0.0


def test_the_newer_failure_runs_first() -> None:
    history = History(10, (case("old", last_failure=2), case("recent", last_failure=8)))

    assert keys(history) == ["recent", "old"]


def test_a_quick_test_runs_before_a_slow_one_that_failed_as_recently() -> None:
    history = History(
        10,
        (
            case("slow", last_failure=9, mean_duration_ms=999.0),
            case("quick", last_failure=9, mean_duration_ms=9.0),
        ),
    )

    ranked = rank(history)

    assert [r.key for r in ranked] == ["quick", "slow"]
    assert ranked[0].score == pytest.approx(ALPHA / 10)
    assert ranked[1].score == pytest.approx(ALPHA / 1000)


def test_a_test_whose_own_file_changed_runs_before_tests_that_never_failed() -> None:
    history = History(
        3,
        (
            case("org.shop.CartTest"),
            case("org.shop.UserTest"),
            case("tests/test_order.py::test_total", file="tests/test_order.py"),
        ),
    )

    java = keys(history, ("src/test/java/org/shop/UserTest.java",))
    python = keys(history, ("tests\\test_order.py",))

    assert java[0] == "org.shop.UserTest"
    assert python[0] == "tests/test_order.py::test_total"


def test_a_changed_file_is_worth_less_than_a_failure_in_the_latest_build() -> None:
    history = History(
        5, (case("tests/a.py::t", file="tests/a.py"), case("tests/b.py::t", last_failure=4))
    )

    assert keys(history, ("tests/a.py",)) == ["tests/b.py::t", "tests/a.py::t"]


def test_a_test_with_no_known_duration_costs_the_median_of_the_others() -> None:
    history = History(
        4,
        (
            case("fast", last_failure=3, mean_duration_ms=1.0),
            case("medium", last_failure=3, mean_duration_ms=50.0),
            case("slow", last_failure=3, mean_duration_ms=99.0),
            case("untimed", last_failure=3, mean_duration_ms=None),
        ),
    )

    ranked = {r.key: r for r in rank(history)}

    assert ranked["untimed"].score == ranked["medium"].score == pytest.approx(ALPHA / 51)
    assert "duration unknown" in ranked["untimed"].reasons


def test_equal_scores_go_to_the_shorter_test_then_follow_the_seed() -> None:
    never_failed = [case(f"t{index}", mean_duration_ms=float(index % 2)) for index in range(40)]
    history = History(2, tuple(never_failed))

    first = keys(history, seed="c1")

    # Every score is 0: the 0 ms tests come first, in an order the seed decides.
    assert {int(key[1:]) % 2 for key in first[:20]} == {0}
    assert first == keys(history, seed="c1")
    assert first != keys(history, seed="c2")
    assert first[:20] != sorted(first[:20])


def test_every_test_comes_with_its_reasons() -> None:
    history = History(
        6,
        (
            case("tests/a.py::t", last_failure=5, mean_duration_ms=12.4, file="tests/a.py"),
            case("tests/b.py::t", last_failure=2, mean_duration_ms=None),
            case("tests/c.py::t", mean_duration_ms=3.0),
        ),
    )

    reasons = {r.key: r.reasons for r in rank(history, ("tests/a.py",))}

    assert reasons == {
        "tests/a.py::t": ("failed in the latest build", "its file changed", "takes about 12 ms"),
        "tests/b.py::t": ("last failed 3 build(s) ago", "duration unknown"),
        "tests/c.py::t": ("takes about 3 ms",),
    }


def test_a_test_is_located_by_its_file_else_by_its_class() -> None:
    assert location("org.shop.CartTest$Nested", None) == "org/shop/CartTest"
    assert location("tests/test_x.py::test_y", None) == "tests/test_x.py"
    assert location("anything", "src\\cart.test.js") == "src/cart.test.js"


def test_an_empty_history_ranks_nothing() -> None:
    assert rank(History(0, ())) == []
