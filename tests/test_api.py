from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from testhunch.api import app as api
from testhunch.store import open_store

FIXTURES = Path(__file__).parent / "fixtures" / "junit"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SHA = "3f9c2b1" + "0" * 33


@pytest.fixture
def client(sqlite_url: str) -> TestClient:
    open_store(sqlite_url).migrate()
    return TestClient(api.create_app(database_url=sqlite_url, api_token=TOKEN))


def upload(
    client: TestClient,
    metadata: Mapping[str, object],
    report: bytes,
    headers: Mapping[str, str] | None = None,
) -> Any:
    return client.post(
        "/v1/runs",
        data={"metadata": json.dumps(metadata)},
        files=[("reports", ("junit.xml", report, "application/xml"))],
        headers=dict(headers or {}),
    )


def test_health_endpoints_need_no_token(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_readyz_reports_an_unreachable_database(tmp_path: Path) -> None:
    # A directory where the database file should be makes SQLite fail to open it.
    blocked = tmp_path / "history.db"
    blocked.mkdir()
    app = api.create_app(database_url=f"sqlite:///{blocked.as_posix()}", api_token=TOKEN)
    assert TestClient(app).get("/readyz").status_code == 503


def test_upload_requires_the_token(client: TestClient) -> None:
    report = (FIXTURES / "pytest.xml").read_bytes()
    response = upload(client, {"repo": "acme/shop", "commit_sha": SHA}, report)
    assert response.status_code == 401
    wrong = upload(
        client,
        {"repo": "acme/shop", "commit_sha": SHA},
        report,
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 401


def test_upload_is_idempotent_and_feeds_the_report(client: TestClient) -> None:
    report = (FIXTURES / "vitest.xml").read_bytes()
    metadata = {
        "repo": "acme/shop",
        "commit_sha": SHA,
        "branch": "main",
        "changes": [{"path": "src/cart.js", "change_type": "M"}],
    }

    first = upload(client, metadata, report, headers=AUTH)
    assert first.status_code == 201
    assert first.json() == {"run_id": 1, "created": True, "results": 4}

    again = upload(client, metadata, report, headers=AUTH)
    assert again.status_code == 200
    assert again.json()["created"] is False

    body = client.get("/v1/report", params={"repo": "acme/shop"}, headers=AUTH).json()
    assert body["runs"] == 1
    assert [row["key"] for row in body["failing"]] == [
        "src/cart.vitest.test.js::cart total > fails on purpose"
    ]

    ranked = client.post(
        "/v1/prioritize",
        json={"repo": "acme/shop", "changed_paths": ["src/cart.js"], "limit": 2},
        headers=AUTH,
    ).json()
    assert len(ranked) == 2
    assert ranked[0]["key"] == "src/cart.vitest.test.js::cart total > fails on purpose"


@pytest.mark.parametrize(
    "metadata",
    [
        {"repo": "acme/shop", "commit_sha": "not-a-sha"},
        {"commit_sha": SHA},
        {"repo": "acme/shop", "commit_sha": SHA, "changes": [{"path": "a", "change_type": "Z"}]},
    ],
)
def test_invalid_metadata_is_422(client: TestClient, metadata: Mapping[str, object]) -> None:
    report = (FIXTURES / "pytest.xml").read_bytes()
    assert upload(client, metadata, report, headers=AUTH).status_code == 422


def test_invalid_report_is_400(client: TestClient) -> None:
    response = upload(client, {"repo": "acme/shop", "commit_sha": SHA}, b"<nope", headers=AUTH)
    assert response.status_code == 400
    assert "not well-formed" in response.json()["detail"]


def test_oversized_report_is_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "MAX_REPORT_BYTES", 100)
    report = (FIXTURES / "pytest.xml").read_bytes()
    response = upload(client, {"repo": "acme/shop", "commit_sha": SHA}, report, headers=AUTH)
    assert response.status_code == 413
