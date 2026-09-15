from __future__ import annotations

import hashlib
import json
import secrets
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

    answer = client.post(
        "/v1/prioritize",
        json={"repo": "acme/shop", "changed_paths": ["src/cart.js"], "limit": 2},
        headers=AUTH,
    ).json()
    # `total` is every ranked test, `ranked` only the ones the limit kept: a caller asking for two
    # still learns how many there were, which is what the job summary says (docs/adr/0023).
    assert (len(answer["ranked"]), answer["total"]) == (2, 3)
    assert answer["prediction_id"] is None
    assert answer["ranked"][0]["key"] == "src/cart.vitest.test.js::cart total > fails on purpose"


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


# -- tokens that open one repository (docs/adr/0022) ---------------------------------------


def scoped(sqlite_url: str, repo: str) -> dict[str, str]:
    """Mint a token for `repo` the way the CLI does, and return the header that presents it."""
    secret = secrets.token_urlsafe(32)
    digest = hashlib.sha256(secret.encode()).hexdigest()
    open_store(sqlite_url).create_api_token(repo, digest, "test")
    return {"Authorization": f"Bearer {secret}"}


def test_a_scoped_token_uploads_to_its_own_repository(client: TestClient, sqlite_url: str) -> None:
    report = (FIXTURES / "pytest.xml").read_bytes()

    response = upload(
        client, {"repo": "acme/shop", "commit_sha": SHA}, report, scoped(sqlite_url, "acme/shop")
    )

    assert response.status_code == 201


def test_a_scoped_token_cannot_upload_to_another_repository(
    client: TestClient, sqlite_url: str
) -> None:
    report = (FIXTURES / "pytest.xml").read_bytes()

    response = upload(
        client, {"repo": "acme/other", "commit_sha": SHA}, report, scoped(sqlite_url, "acme/shop")
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "this token does not open that repository"


def test_a_scoped_token_cannot_read_another_repository(client: TestClient, sqlite_url: str) -> None:
    headers = scoped(sqlite_url, "acme/shop")

    assert (
        client.get("/v1/report", params={"repo": "acme/shop"}, headers=headers).status_code == 200
    )
    assert (
        client.get("/v1/report", params={"repo": "acme/other"}, headers=headers).status_code == 403
    )


def test_a_scoped_token_cannot_rank_another_repository(client: TestClient, sqlite_url: str) -> None:
    headers = scoped(sqlite_url, "acme/shop")

    mine = client.post("/v1/prioritize", json={"repo": "acme/shop"}, headers=headers)
    theirs = client.post("/v1/prioritize", json={"repo": "acme/other"}, headers=headers)

    assert mine.status_code == 200
    assert theirs.status_code == 403


def test_the_operator_token_still_opens_every_repository(client: TestClient) -> None:
    for repo in ("acme/shop", "acme/other"):
        assert client.get("/v1/report", params={"repo": repo}, headers=AUTH).status_code == 200


def test_a_revoked_token_is_refused_like_an_unknown_one(
    client: TestClient, sqlite_url: str
) -> None:
    headers = scoped(sqlite_url, "acme/shop")
    store = open_store(sqlite_url)
    store.revoke_api_token(store.api_tokens("acme/shop")[0].token_id)

    response = client.get("/v1/report", params={"repo": "acme/shop"}, headers=headers)

    assert response.status_code == 401


# -- the server keeps the ranking it served (docs/adr/0023) --------------------------------


def a_run_exists(client: TestClient) -> None:
    upload(
        client,
        {"repo": "acme/shop", "commit_sha": SHA, "changes": [{"path": "src/cart.js"}]},
        (FIXTURES / "vitest.xml").read_bytes(),
        AUTH,
    )


def test_recording_keeps_the_ranking_the_server_just_made(
    client: TestClient, sqlite_url: str
) -> None:
    a_run_exists(client)
    other = "b" * 40

    answer = client.post(
        "/v1/prioritize",
        json={"repo": "acme/shop", "commit_sha": other, "record": True, "limit": 1},
        headers=AUTH,
    ).json()

    assert answer["prediction_id"] is not None
    assert (len(answer["ranked"]), answer["total"]) == (1, 3)

    # The proof is not that a row exists: it is that the run which follows pairs with it, which is
    # the whole point of recording. Shadow mode only sees runs newer than the ranking.
    upload(
        client,
        {"repo": "acme/shop", "commit_sha": other},
        (FIXTURES / "vitest.xml").read_bytes() + b"<!-- a later build -->",
        AUTH,
    )
    paired = open_store(sqlite_url).shadow_runs("acme/shop", last_runs=10)
    assert len(paired) == 1
    # The whole ranking was kept, not the single row the limit returned.
    assert len(paired[0].positions) == 3


def test_a_ranking_is_kept_only_when_asked(client: TestClient, sqlite_url: str) -> None:
    a_run_exists(client)

    answer = client.post(
        "/v1/prioritize", json={"repo": "acme/shop", "commit_sha": "b" * 40}, headers=AUTH
    ).json()

    assert answer["prediction_id"] is None


def test_recording_without_a_commit_is_refused(client: TestClient) -> None:
    a_run_exists(client)

    response = client.post(
        "/v1/prioritize", json={"repo": "acme/shop", "record": True}, headers=AUTH
    )

    assert response.status_code == 422
    assert "commit" in response.json()["detail"]


def test_an_empty_history_records_nothing_and_says_so_plainly(client: TestClient) -> None:
    answer = client.post(
        "/v1/prioritize",
        json={"repo": "acme/never-seen", "commit_sha": SHA, "record": True},
        headers=AUTH,
    ).json()

    assert (answer["ranked"], answer["total"], answer["prediction_id"]) == ([], 0, None)


def test_a_scoped_token_cannot_record_for_another_repository(
    client: TestClient, sqlite_url: str
) -> None:
    a_run_exists(client)

    response = client.post(
        "/v1/prioritize",
        json={"repo": "acme/shop", "commit_sha": "b" * 40, "record": True},
        headers=scoped(sqlite_url, "acme/other"),
    )

    assert response.status_code == 403


def test_the_shadow_report_is_read_from_the_server(client: TestClient) -> None:
    """The whole hosted loop, through HTTP only: rank, keep, run, and read what it would miss."""
    report = (FIXTURES / "vitest.xml").read_bytes()
    upload(client, {"repo": "acme/shop", "commit_sha": SHA}, report, AUTH)
    later = "b" * 40

    kept = client.post(
        "/v1/prioritize",
        json={"repo": "acme/shop", "commit_sha": later, "record": True},
        headers=AUTH,
    ).json()
    upload(client, {"repo": "acme/shop", "commit_sha": later}, report + b"<!-- later -->", AUTH)

    shadow = client.get("/v1/shadow", params={"repo": "acme/shop"}, headers=AUTH).json()

    assert kept["prediction_id"] is not None
    assert (shadow["runs"], shadow["failing_runs"]) == (1, 1)
    # The failing test was ranked first, so even the smallest budget turns the build red.
    assert shadow["budgets"][0]["caught_runs"] == 1


def test_a_scoped_token_cannot_read_another_repositorys_shadow_report(
    client: TestClient, sqlite_url: str
) -> None:
    headers = scoped(sqlite_url, "acme/shop")

    assert (
        client.get("/v1/shadow", params={"repo": "acme/shop"}, headers=headers).status_code == 200
    )
    assert (
        client.get("/v1/shadow", params={"repo": "acme/other"}, headers=headers).status_code == 403
    )
