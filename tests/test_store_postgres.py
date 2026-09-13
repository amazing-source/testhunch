"""Postgres-only behaviour that the shared contract in test_store.py cannot express.

These tests need psycopg but not a running Postgres server.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Iterator

import pytest

from testhunch.store import StoreError

pytest.importorskip("psycopg")

from testhunch.store import postgres


@pytest.fixture
def silent_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """URL of a port that accepts TCP connections and never answers, like a stuck database."""
    monkeypatch.delenv("PGCONNECT_TIMEOUT", raising=False)
    with socket.create_server(("127.0.0.1", 0)) as server:
        yield f"postgresql://nobody@127.0.0.1:{server.getsockname()[1]}/nothing"


def _seconds_to_fail(url: str) -> float:
    started = time.monotonic()
    with pytest.raises(StoreError, match="could not connect to Postgres"):
        postgres.PostgresStore(url).ping()
    return time.monotonic() - started


def test_unreachable_server_fails_after_the_default_timeout(
    silent_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # psycopg enforces at least 2 s; without a default it would wait 130 s.
    monkeypatch.setattr(postgres, "CONNECT_TIMEOUT_S", 2)
    assert _seconds_to_fail(silent_server) < 10


@pytest.mark.parametrize("source", ["url", "environment"])
def test_an_explicit_connect_timeout_wins_over_the_default(
    source: str, silent_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(postgres, "CONNECT_TIMEOUT_S", 600)
    url = silent_server
    if source == "url":
        url += "?connect_timeout=2"
    else:
        monkeypatch.setenv("PGCONNECT_TIMEOUT", "2")
    assert _seconds_to_fail(url) < 10
