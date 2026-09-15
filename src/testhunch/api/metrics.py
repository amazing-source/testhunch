"""What the service says about itself, in the Prometheus text format (docs/adr/0027).

Written by hand rather than with a client library: the exposition format is a few lines of text,
and a library's process-wide registry would have to be reset between tests that each build their
own app.

Two kinds of number live here. What this process has served since it started is counted in memory
and is lost on restart, which is what counters are for. Everything else is read from the database
at scrape time, briefly cached, because the database is the only thing that survives a deployment.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Lock

from testhunch.shadow import evaluate
from testhunch.store.base import SqlStore

# Wide buckets: this is an API whose slowest route parses XML, not a latency-critical service.
BUCKETS = (0.01, 0.05, 0.25, 1.0, 5.0, 30.0)

# The database is read on scrape. Prometheus scrapes far more often than these numbers move, and
# a scrape must never be the reason the database is busy.
CACHE_SECONDS = 30.0

# Enough runs that a rate means something. Below it the numbers are still reported, and an alert
# that divides by them is expected to guard on the count itself (docs/adr/0018).
SHADOW_RUNS = 200


def escape(value: str) -> str:
    """Escape a label value: backslash, double quote and newline, in that order."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class Requests:
    """What this process has served. Reset by a restart, like every counter in a single process."""

    _lock: Lock = field(default_factory=Lock)
    _total: dict[tuple[str, str], int] = field(default_factory=dict)
    _sum: dict[str, float] = field(default_factory=dict)
    _count: dict[str, int] = field(default_factory=dict)
    _buckets: dict[tuple[str, float], int] = field(default_factory=dict)

    def observe(self, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self._total[(route, str(status))] = self._total.get((route, str(status)), 0) + 1
            self._sum[route] = self._sum.get(route, 0.0) + seconds
            self._count[route] = self._count.get(route, 0) + 1
            for bucket in BUCKETS:
                if seconds <= bucket:
                    self._buckets[(route, bucket)] = self._buckets.get((route, bucket), 0) + 1

    def render(self) -> list[str]:
        with self._lock:
            total = dict(self._total)
            sums, counts, buckets = dict(self._sum), dict(self._count), dict(self._buckets)

        lines = [
            "# HELP testhunch_requests_total Requests served, by route and status.",
            "# TYPE testhunch_requests_total counter",
        ]
        for (route, status), value in sorted(total.items()):
            lines.append(
                f'testhunch_requests_total{{route="{escape(route)}",status="{status}"}} {value}'
            )

        lines += [
            "# HELP testhunch_request_duration_seconds How long those requests took.",
            "# TYPE testhunch_request_duration_seconds histogram",
        ]
        for route in sorted(counts):
            label = escape(route)
            for bucket in BUCKETS:
                count = buckets.get((route, bucket), 0)
                lines.append(
                    "testhunch_request_duration_seconds_bucket"
                    f'{{route="{label}",le="{bucket}"}} {count}'
                )
            lines.append(
                f'testhunch_request_duration_seconds_bucket{{route="{label}",le="+Inf"}} '
                f"{counts[route]}"
            )
            lines.append(
                f'testhunch_request_duration_seconds_sum{{route="{label}"}} {sums[route]:.6f}'
            )
            lines.append(
                f'testhunch_request_duration_seconds_count{{route="{label}"}} {counts[route]}'
            )
        return lines


@dataclass
class Metrics:
    """The whole exposition: in-memory counters, plus a cached read of the database."""

    store: SqlStore
    version: str
    # What the server was told to run (docs/adr/0026). The version alone cannot tell two builds of
    # the same development version apart, which is every deployment between two releases.
    image: str = field(default_factory=lambda: os.environ.get("TESTHUNCH_IMAGE", ""))
    requests: Requests = field(default_factory=Requests)
    cache_seconds: float = CACHE_SECONDS
    _lock: Lock = field(default_factory=Lock)
    _cached: tuple[float, list[str]] | None = None

    def render(self, now: float | None = None) -> str:
        moment = time.monotonic() if now is None else now
        with self._lock:
            fresh = self._cached is not None and moment - self._cached[0] < self.cache_seconds
            stored = self._cached[1] if fresh and self._cached else None
        if stored is None:
            stored = self._from_database()
            with self._lock:
                self._cached = (moment, stored)

        lines = [
            "# HELP testhunch_build_info The running version and image, as labels on a constant 1.",
            "# TYPE testhunch_build_info gauge",
            f'testhunch_build_info{{version="{escape(self.version)}"'
            f',image="{escape(self.image)}"}} 1',
        ]
        return "\n".join(lines + self.requests.render() + stored) + "\n"

    def _from_database(self) -> list[str]:
        try:
            self.store.ping()
        except Exception:
            # An unreachable database is itself the measurement: say so and report nothing else,
            # rather than fail the scrape and leave the alert with no series to fire on.
            return [
                "# HELP testhunch_database_up Whether the database answered at scrape time.",
                "# TYPE testhunch_database_up gauge",
                "testhunch_database_up 0",
            ]

        lines = [
            "# HELP testhunch_database_up Whether the database answered at scrape time.",
            "# TYPE testhunch_database_up gauge",
            "testhunch_database_up 1",
            "# HELP testhunch_runs Runs recorded, by repository.",
            "# TYPE testhunch_runs gauge",
        ]
        repos = self.store.repos()
        for repo in repos:
            lines.append(f'testhunch_runs{{repo="{escape(repo)}"}} {self.store.run_count(repo)}')

        # The service level objective (docs/adr/0027): of the runs that went red, how many a
        # budget would still have caught. Counts, not a rate, so an alert can refuse to divide
        # by a handful of runs.
        lines += [
            "# HELP testhunch_shadow_failing_runs Evaluated runs that had a failure, by budget.",
            "# TYPE testhunch_shadow_failing_runs gauge",
            "# HELP testhunch_shadow_caught_runs Of those, the ones the budget would have caught.",
            "# TYPE testhunch_shadow_caught_runs gauge",
        ]
        for repo in repos:
            label = escape(repo)
            for point in evaluate(self.store.shadow_runs(repo, SHADOW_RUNS)):
                budget = f'{{repo="{label}",budget="{point.fraction}"}}'
                lines.append(f"testhunch_shadow_failing_runs{budget} {point.failing_runs}")
                lines.append(f"testhunch_shadow_caught_runs{budget} {point.caught_runs}")
        return lines
