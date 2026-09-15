from __future__ import annotations

import pytest

from testhunch.api.metrics import Metrics, Requests, escape
from testhunch.models import CaseResult, RunInput, Status
from testhunch.store import SqlStore


def families(exposition: str) -> dict[str, list[str]]:
    """The exposition split by metric name, comments dropped."""
    out: dict[str, list[str]] = {}
    for line in exposition.splitlines():
        if line.startswith("#") or not line:
            continue
        out.setdefault(line.split("{")[0].split(" ")[0], []).append(line)
    return out


def test_a_label_value_cannot_break_out_of_its_quotes() -> None:
    assert escape('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_every_sample_belongs_to_a_declared_metric(store: SqlStore, one_run: object) -> None:
    """Prometheus drops a sample whose family was never declared, silently."""
    metrics = Metrics(store=store, version="1.2.3")
    metrics.requests.observe("/v1/report", 200, 0.02)

    exposition = metrics.render()
    declared = {
        line.split(" ")[2] for line in exposition.splitlines() if line.startswith("# TYPE ")
    }
    allowed = {name for one in declared for name in _samples_of(one)}
    assert families(exposition).keys() <= allowed, families(exposition).keys() - allowed


def _samples_of(name: str) -> set[str]:
    """The sample names a metric family may produce, histograms included."""
    return {name, f"{name}_bucket", f"{name}_sum", f"{name}_count"}


def test_the_version_and_the_image_are_reported_as_labels(store: SqlStore) -> None:
    """Two deployments of the same development version differ only by the image."""
    exposition = Metrics(store=store, version="9.9.9", image="ghcr.io/x/y:sha-abc").render()

    assert 'testhunch_build_info{version="9.9.9",image="ghcr.io/x/y:sha-abc"} 1' in exposition


def test_the_image_label_is_empty_when_nothing_named_one(
    store: SqlStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TESTHUNCH_IMAGE", raising=False)

    assert 'image=""' in Metrics(store=store, version="9.9.9").render()


def test_an_empty_database_still_answers(store: SqlStore) -> None:
    exposition = Metrics(store=store, version="1.0.0").render()

    assert "testhunch_database_up 1" in exposition
    assert "testhunch_runs{" not in exposition


def test_requests_are_counted_by_route_and_status() -> None:
    requests = Requests()
    requests.observe("/v1/report", 200, 0.02)
    requests.observe("/v1/report", 200, 0.30)
    requests.observe("/v1/report", 403, 0.01)

    rendered = "\n".join(requests.render())
    assert 'testhunch_requests_total{route="/v1/report",status="200"} 2' in rendered
    assert 'testhunch_requests_total{route="/v1/report",status="403"} 1' in rendered
    assert 'testhunch_request_duration_seconds_count{route="/v1/report"} 3' in rendered


def test_histogram_buckets_are_cumulative_and_end_at_the_count() -> None:
    requests = Requests()
    for seconds in (0.005, 0.02, 2.0):
        requests.observe("/v1/runs", 201, seconds)

    lines = {
        line.split(" ")[0]: int(line.split(" ")[1])
        for line in requests.render()
        if line.startswith("testhunch_request_duration_seconds_bucket")
    }
    counts = [lines[name] for name in sorted(lines, key=lambda n: _upper_bound(n))]
    assert counts == sorted(counts), counts
    assert counts[-1] == 3


def _upper_bound(sample: str) -> float:
    edge = sample.split('le="')[1].rstrip('"}')
    return float("inf") if edge == "+Inf" else float(edge)


def test_a_repository_with_runs_is_reported(store: SqlStore, one_run: object) -> None:
    exposition = Metrics(store=store, version="1.0.0").render()

    assert 'testhunch_runs{repo="acme/shop"} 1' in exposition


def test_the_database_read_is_cached_between_scrapes(store: SqlStore) -> None:
    metrics = Metrics(store=store, version="1.0.0", cache_seconds=60.0)
    reads = 0
    original = store.repos

    def counted() -> list[str]:
        nonlocal reads
        reads += 1
        return original()

    store.repos = counted  # type: ignore[method-assign]
    metrics.render(now=100.0)
    metrics.render(now=130.0)
    assert reads == 1

    metrics.render(now=200.0)
    assert reads == 2


def test_an_unreachable_database_is_reported_rather_than_raised(store: SqlStore) -> None:
    def refuse() -> None:
        raise RuntimeError("no database")

    store.ping = refuse  # type: ignore[method-assign]

    exposition = Metrics(store=store, version="1.0.0").render()

    assert "testhunch_database_up 0" in exposition
    assert "testhunch_build_info" in exposition


def _case(key: str, status: Status) -> CaseResult:
    return CaseResult(
        key=key,
        name=key.rsplit("::", 1)[-1],
        suite=None,
        file=None,
        status=status,
        duration_ms=10,
        message=None,
    )


@pytest.fixture
def one_run(store: SqlStore) -> None:
    store.ingest(
        RunInput(
            repo="acme/shop",
            commit_sha="a" * 40,
            report_digest="d" * 64,
            results=(
                _case("shop::test_a", Status.PASSED),
                _case("shop::test_b", Status.FAILED),
            ),
        )
    )
