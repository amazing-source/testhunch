"""The hosted service: CI jobs upload reports here instead of keeping a local database.

Run it with: uvicorn testhunch.api.app:create_app --factory
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import asdict, dataclass
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
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field, ValidationError

from testhunch import __version__
from testhunch.junit import ReportError, parse_reports
from testhunch.models import FileChange, RunInput
from testhunch.prioritize import rank
from testhunch.shadow import evaluate
from testhunch.store import DEFAULT_DATABASE_URL, StoreError, open_store

MAX_REPORT_BYTES = 10 * 1024 * 1024
MAX_REPORTS = 50

_SHA = r"^[0-9a-f]{7,64}$"
_BEARER = "Bearer "


@dataclass(frozen=True, slots=True)
class Caller:
    """Who is asking. `repo` is None for the operator token, which opens every repository."""

    repo: str | None

    def may(self, repo: str) -> bool:
        return self.repo is None or self.repo == repo


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate(request: Request, authorization: Annotated[str | None, Header()] = None) -> Caller:
    """Who is asking (docs/adr/0022).

    The operator token opens every repository. A token minted for one repository opens that one.
    Anything else is a 401, and so is a revoked token, because `repo_for_api_token` does not
    return revoked ones.

    At module level, not inside `create_app`: with postponed annotations, a dependency named in an
    `Annotated[...]` must be resolvable from the module's globals, and a closure is not.
    """
    token: str = request.app.state.api_token
    if not token:
        return Caller(repo=None)  # no token configured: local development only

    presented = None
    if authorization is not None and authorization.startswith(_BEARER):
        presented = authorization[len(_BEARER) :]
    if presented is None:
        raise _unauthorized()
    if secrets.compare_digest(presented, token):
        return Caller(repo=None)

    digest = hashlib.sha256(presented.encode()).hexdigest()
    try:
        repo = request.app.state.store.repo_for_api_token(digest)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if repo is None:
        raise _unauthorized()
    return Caller(repo=repo)


def _refuse_other_repos(caller: Caller, repo: str) -> None:
    """A token minted for one repository cannot read or write another one (docs/adr/0022)."""
    if not caller.may(repo):
        raise HTTPException(status_code=403, detail="this token does not open that repository")


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
    # Keep this ranking, so that shadow mode can measure it against the run that follows. The
    # server records what it served, and knows which run its history stopped at (docs/adr/0023).
    record: bool = False
    base_sha: str | None = Field(default=None, pattern=_SHA)


class PrioritizeResponse(BaseModel):
    ranked: list[dict[str, Any]]
    total: int
    prediction_id: int | None = None


def create_app(database_url: str | None = None, api_token: str | None = None) -> FastAPI:
    url = database_url or os.environ.get("TESTHUNCH_DATABASE_URL", DEFAULT_DATABASE_URL)
    token = api_token if api_token is not None else os.environ.get("TESTHUNCH_API_TOKEN", "")
    store = open_store(url)

    app = FastAPI(title="testhunch", version=__version__)
    app.state.store = store
    app.state.api_token = token

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

    # Authenticated at the router, so a route added later is closed even if its author forgets;
    # each route then says which repository it touches, and that is what scoping checks.
    v1 = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])

    @v1.post("/runs", status_code=201)
    def upload_run(
        response: Response,
        caller: Annotated[Caller, Depends(authenticate)],
        metadata: Annotated[str, Form(description="RunMetadata as JSON")],
        reports: Annotated[list[UploadFile], File(description="JUnit XML files")],
    ) -> IngestResponse:
        try:
            meta = RunMetadata.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
        _refuse_other_repos(caller, meta.repo)
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
        caller: Annotated[Caller, Depends(authenticate)],
        repo: Annotated[str, Query(min_length=1, max_length=200)],
        last_runs: Annotated[int, Query(ge=1, le=1000)] = 50,
        limit: Annotated[int, Query(ge=1, le=1000)] = 10,
    ) -> dict[str, Any]:
        _refuse_other_repos(caller, repo)
        return {
            "repo": repo,
            "runs": store.run_count(repo),
            "flaky": [asdict(t) for t in store.flaky_tests(repo, limit)],
            "slowest": [asdict(t) for t in store.slowest_tests(repo, last_runs, limit)],
            "failing": [asdict(t) for t in store.failing_tests(repo, last_runs, limit)],
        }

    @v1.get("/shadow")
    def shadow(
        caller: Annotated[Caller, Depends(authenticate)],
        repo: Annotated[str, Query(min_length=1, max_length=200)],
        last_runs: Annotated[int, Query(ge=1, le=1000)] = 50,
    ) -> dict[str, Any]:
        """What skipping tests would have missed, evaluated where both halves live.

        The rankings and the results it compares are both the server's, so it does the arithmetic;
        a client would have to download every recorded ranking to do the same (docs/adr/0023).
        """
        _refuse_other_repos(caller, repo)
        runs = store.shadow_runs(repo, last_runs)
        points = evaluate(runs)
        return {
            "repo": repo,
            "runs": len(runs),
            "failing_runs": points[0].failing_runs if points else 0,
            "budgets": [asdict(p) for p in points],
        }

    @v1.post("/prioritize")
    def prioritize(
        caller: Annotated[Caller, Depends(authenticate)], body: PrioritizeRequest
    ) -> PrioritizeResponse:
        _refuse_other_repos(caller, body.repo)
        try:
            ranked = rank(store.history(body.repo), body.changed_paths, seed=body.commit_sha or "")
        except StoreError as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc

        prediction_id = None
        if body.record and ranked:
            if body.commit_sha is None:
                raise HTTPException(
                    status_code=422, detail="recording a ranking needs the commit it is for"
                )
            # Read after the history the ranking came from, so it can only be newer than what the
            # ranking saw: at worst a run is left out of the shadow report, never judged by a
            # ranking that had already seen it.
            last_run_id = store.latest_run_id(body.repo)
            if last_run_id is not None:
                prediction_id = store.record_prediction(
                    body.repo,
                    body.commit_sha,
                    ranked,
                    last_run_id=last_run_id,
                    base_sha=body.base_sha,
                )

        return PrioritizeResponse(
            ranked=[asdict(r) for r in ranked[: body.limit]],
            total=len(ranked),
            prediction_id=prediction_id,
        )

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
