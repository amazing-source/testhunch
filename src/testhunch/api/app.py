"""The hosted service: CI jobs upload reports here instead of keeping a local database.

Run it with: uvicorn testhunch.api.app:create_app --factory
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field, ValidationError

from testhunch import __version__
from testhunch.junit import ReportError, parse_reports
from testhunch.models import FileChange, RunInput
from testhunch.prioritize import rank
from testhunch.store import DEFAULT_DATABASE_URL, StoreError, open_store

MAX_REPORT_BYTES = 10 * 1024 * 1024
MAX_REPORTS = 50

_SHA = r"^[0-9a-f]{7,64}$"


class ChangeIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    change_type: Literal["A", "C", "D", "M", "R", "T", "U", "X"] = "M"
    old_path: str | None = Field(default=None, max_length=4096)


class RunMetadata(BaseModel):
    repo: str = Field(min_length=1, max_length=200)
    commit_sha: str = Field(pattern=_SHA)
    branch: str | None = Field(default=None, max_length=255)
    base_sha: str | None = Field(default=None, pattern=_SHA)
    changes: list[ChangeIn] = Field(default_factory=list, max_length=100_000)


class IngestResponse(BaseModel):
    run_id: int
    created: bool
    results: int


class PrioritizeRequest(BaseModel):
    repo: str = Field(min_length=1, max_length=200)
    changed_paths: list[str] = Field(default_factory=list, max_length=100_000)
    # The commit about to be tested, which orders equal scores as `testhunch prioritize` does.
    commit_sha: str | None = Field(default=None, pattern=_SHA)
    limit: int | None = Field(default=None, ge=1)


def create_app(database_url: str | None = None, api_token: str | None = None) -> FastAPI:
    url = database_url or os.environ.get("TESTHUNCH_DATABASE_URL", DEFAULT_DATABASE_URL)
    token = api_token if api_token is not None else os.environ.get("TESTHUNCH_API_TOKEN", "")
    store = open_store(url)

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if not token:
            return  # no token configured: local development only
        expected = f"Bearer {token}".encode()
        if authorization is None or not secrets.compare_digest(authorization.encode(), expected):
            raise HTTPException(
                status_code=401,
                detail="missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    app = FastAPI(title="testhunch", version=__version__)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness: the process is up. Says nothing about the database."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        """Readiness: the database answers."""
        try:
            store.ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {"status": "ready"}

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])

    @v1.post("/runs", status_code=201)
    def upload_run(
        response: Response,
        metadata: Annotated[str, Form(description="RunMetadata as JSON")],
        reports: Annotated[list[UploadFile], File(description="JUnit XML files")],
    ) -> IngestResponse:
        try:
            meta = RunMetadata.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
        if len(reports) > MAX_REPORTS:
            raise HTTPException(status_code=413, detail=f"at most {MAX_REPORTS} reports per run")

        blobs = [_read_limited(upload) for upload in reports]
        try:
            results, digest = parse_reports(blobs)
        except ReportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            outcome = store.ingest(
                RunInput(
                    repo=meta.repo,
                    commit_sha=meta.commit_sha,
                    report_digest=digest,
                    results=results,
                    branch=meta.branch,
                    base_sha=meta.base_sha,
                    changes=tuple(
                        FileChange(c.path, c.change_type, c.old_path) for c in meta.changes
                    ),
                )
            )
        except StoreError as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc

        if not outcome.created:
            response.status_code = 200
        return IngestResponse(**asdict(outcome))

    @v1.get("/report")
    def report(
        repo: Annotated[str, Query(min_length=1, max_length=200)],
        last_runs: Annotated[int, Query(ge=1, le=1000)] = 50,
        limit: Annotated[int, Query(ge=1, le=1000)] = 10,
    ) -> dict[str, Any]:
        return {
            "repo": repo,
            "runs": store.run_count(repo),
            "flaky": [asdict(t) for t in store.flaky_tests(repo, limit)],
            "slowest": [asdict(t) for t in store.slowest_tests(repo, last_runs, limit)],
            "failing": [asdict(t) for t in store.failing_tests(repo, last_runs, limit)],
        }

    @v1.post("/prioritize")
    def prioritize(body: PrioritizeRequest) -> list[dict[str, Any]]:
        ranked = rank(store.history(body.repo), body.changed_paths, seed=body.commit_sha or "")
        return [asdict(r) for r in ranked[: body.limit]]

    app.include_router(v1)
    return app


def _read_limited(upload: UploadFile) -> bytes:
    data = upload.file.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{upload.filename or 'report'} is larger than {MAX_REPORT_BYTES} bytes",
        )
    return data
