"""Sending a run to a hosted testhunch, with nothing but the standard library.

The package depends on defusedxml and nothing else, and `testhunch ingest --api` is no reason to
put an HTTP client in every install: a multipart body is a few lines of bytes.

The reports are sent as they are, unparsed. The server parses them, so a runner dialect it does not
know fails there rather than silently locally, and the digest that makes ingestion idempotent is
computed once, on the bytes that arrived (docs/adr/0021).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from secrets import token_hex
from typing import Any
from urllib.parse import urlencode, urlparse

from testhunch.models import FileChange, RankedTest

TIMEOUT_SECONDS = 30.0
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class UploadError(RuntimeError):
    """The run did not reach the server, or the server refused it."""


def metadata_json(
    repo: str,
    commit_sha: str,
    branch: str | None,
    base_sha: str | None,
    changes: Sequence[FileChange],
) -> str:
    """The `metadata` field the API expects, as JSON."""
    return json.dumps(
        {
            "repo": repo,
            "commit_sha": commit_sha,
            "branch": branch,
            "base_sha": base_sha,
            "changes": [
                {"path": c.path, "change_type": c.change_type, "old_path": c.old_path}
                for c in changes
            ],
        }
    )


def endpoint(api_url: str, path: str) -> str:
    """One of the API's addresses, and a refusal to send a token over a cleartext connection.

    A bearer token in an `http://` request is readable by anything on the path, and the whole point
    of the token is that it is not. Only a loopback address is allowed to skip TLS, because nothing
    on a path that short can read it.
    """
    parsed = urlparse(api_url)
    if parsed.scheme not in {"http", "https"}:
        raise UploadError(f"the API URL must be http or https, not {parsed.scheme!r}")
    if parsed.scheme == "http" and (parsed.hostname or "") not in LOCAL_HOSTS:
        raise UploadError(
            f"refusing to send the token in the clear to {parsed.hostname}: use https://"
        )
    return f"{api_url.rstrip('/')}{path}"


def _multipart(metadata: str, reports: Sequence[Path]) -> tuple[bytes, str]:
    boundary = token_hex(16)
    marker = f"--{boundary}".encode()
    body = bytearray()

    body += marker + b"\r\n"
    body += b'Content-Disposition: form-data; name="metadata"\r\n'
    body += b"Content-Type: application/json\r\n\r\n"
    body += metadata.encode() + b"\r\n"

    for path in reports:
        name = path.name.replace('"', "").replace("\r", "").replace("\n", "")
        body += marker + b"\r\n"
        body += f'Content-Disposition: form-data; name="reports"; filename="{name}"\r\n'.encode()
        body += b"Content-Type: application/xml\r\n\r\n"
        body += path.read_bytes() + b"\r\n"

    body += marker + b"--\r\n"
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def upload_run(
    api_url: str,
    token: str,
    metadata: str,
    reports: Sequence[Path],
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Post one run and its reports, and return what the API answered."""
    url = endpoint(api_url, "/v1/runs")
    body, content_type = _multipart(metadata, reports)
    return _post(url, token, body, content_type, timeout)


def fetch_ranking(
    api_url: str,
    token: str,
    payload: dict[str, Any],
    timeout: float = TIMEOUT_SECONDS,
) -> tuple[list[RankedTest], int, int | None]:
    """Ask the hosted testhunch to rank, and to keep the ranking when `record` is set.

    The server ranks from its own history and records what it served, so the ranking and the run
    that follows meet in the same database. Ranking here and shipping the result up would let a
    client record a ranking the server never made (docs/adr/0023).
    """
    answer = _post_json(endpoint(api_url, "/v1/prioritize"), token, payload, timeout)
    ranked = [
        RankedTest(
            key=str(r["key"]),
            score=float(r["score"]),
            reasons=tuple(str(x) for x in r.get("reasons", ())),
            expected_ms=float(r.get("expected_ms") or 0.0),
        )
        for r in answer.get("ranked", [])
    ]
    prediction = answer.get("prediction_id")
    total = int(answer.get("total", len(ranked)))
    return ranked, total, None if prediction is None else int(prediction)


def fetch_shadow(
    api_url: str, token: str, repo: str, last_runs: int, timeout: float = TIMEOUT_SECONDS
) -> dict[str, Any]:
    """The shadow report a hosted testhunch computes, in the shape `shadow --format json` prints.

    The server evaluates it, because the rankings and the results it compares are both its own; the
    client would have to download every recorded ranking to do the same arithmetic.
    """
    query = urlencode({"repo": repo, "last_runs": last_runs})
    return _request(endpoint(api_url, f"/v1/shadow?{query}"), token, None, None, timeout)


def _post_json(
    url: str, token: str, payload: dict[str, Any], timeout: float = TIMEOUT_SECONDS
) -> dict[str, Any]:
    return _post(url, token, json.dumps(payload).encode(), "application/json", timeout)


def _post(url: str, token: str, body: bytes, content_type: str, timeout: float) -> dict[str, Any]:
    return _request(url, token, body, content_type, timeout)


def _request(
    url: str, token: str, body: bytes | None, content_type: str | None, timeout: float
) -> dict[str, Any]:
    """One request, one JSON object back. A body means POST, no body means GET."""
    request = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    if content_type is not None:
        request.add_header("Content-Type", content_type)
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # Closed explicitly: an HTTPError holds an open response, and letting the garbage
        # collector find it raises from a deallocator, where nothing can handle it.
        with exc:
            detail = exc.read().decode(errors="replace").strip()
        raise UploadError(f"{url} answered {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"could not reach {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UploadError(f"{url} answered something that is not JSON") from exc

    if not isinstance(answer, dict):
        raise UploadError(f"{url} answered {type(answer).__name__}, not an object")
    return answer
