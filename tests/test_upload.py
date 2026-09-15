"""`testhunch ingest --api` against a real HTTP server, not a stand-in for one.

The point of the multipart body is that another program parses it. A fake that records the call
would prove the arguments and nothing about the bytes, so these tests run a server from the
standard library and read what actually arrived on the wire.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from testhunch.models import FileChange
from testhunch.upload import UploadError, endpoint, metadata_json, upload_run


class Recorder(BaseHTTPRequestHandler):
    """Answers every POST with `answer`, and keeps the request for the test to look at."""

    answer: ClassVar[dict[str, Any]] = {"run_id": 7, "created": True, "results": 3}
    status = 201
    received: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:  # BaseHTTPRequestHandler's spelling, not ours
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        Recorder.received = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type", ""),
            "body": body,
        }
        payload = json.dumps(self.answer).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        """Quiet: the default handler writes every request to stderr."""


@pytest.fixture
def server() -> Iterator[str]:
    httpd = HTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def parts(received: dict[str, Any]) -> list[Any]:
    """The multipart body, parsed the way a server parses it."""
    raw = b"Content-Type: " + received["content_type"].encode() + b"\r\n\r\n" + received["body"]
    return list(BytesParser().parsebytes(raw).walk())[1:]


def test_the_run_arrives_as_the_api_expects_it(server: str, tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_bytes(b"<testsuite name='s'><testcase name='t'/></testsuite>")

    answer = upload_run(
        server,
        "sekret",
        metadata_json(
            "owner/repo", "a" * 40, "main", "b" * 40, [FileChange("src/a.py", "M", None)]
        ),
        [report],
    )

    assert answer == {"run_id": 7, "created": True, "results": 3}
    assert Recorder.received["path"] == "/v1/runs"
    assert Recorder.received["authorization"] == "Bearer sekret"

    metadata, sent = parts(Recorder.received)
    assert json.loads(metadata.get_payload()) == {
        "repo": "owner/repo",
        "commit_sha": "a" * 40,
        "branch": "main",
        "base_sha": "b" * 40,
        "changes": [{"path": "src/a.py", "change_type": "M", "old_path": None}],
    }
    assert sent.get_payload(decode=True) == report.read_bytes()
    assert sent.get_filename() == "junit.xml"


def test_every_report_is_sent_under_the_name_the_api_reads(server: str, tmp_path: Path) -> None:
    """The field is `reports`, plural: two files are two parts with the same name, not one list."""
    first, second = tmp_path / "a.xml", tmp_path / "b.xml"
    first.write_bytes(b"<testsuite/>")
    second.write_bytes(b"<testsuite/>")

    upload_run(server, "", metadata_json("owner/repo", "a" * 40, None, None, []), [first, second])

    names = [
        part.get_param("name", header="content-disposition") for part in parts(Recorder.received)
    ]
    assert names == ["metadata", "reports", "reports"]


def test_no_token_means_no_authorization_header(server: str, tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_bytes(b"<testsuite/>")

    upload_run(server, "", metadata_json("owner/repo", "a" * 40, None, None, []), [report])

    assert Recorder.received["authorization"] is None


def test_what_the_server_refused_is_repeated_to_the_user(server: str, tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_bytes(b"<testsuite/>")
    Recorder.status = 401
    Recorder.answer = {"detail": "missing or invalid bearer token"}
    try:
        with pytest.raises(UploadError, match=r"401.*missing or invalid bearer token"):
            upload_run(
                server, "wrong", metadata_json("owner/repo", "a" * 40, None, None, []), [report]
            )
    finally:
        Recorder.status = 201
        Recorder.answer = {"run_id": 7, "created": True, "results": 3}


def test_a_server_that_is_not_there_says_so(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_bytes(b"<testsuite/>")

    # Port 1 on the loopback: nothing listens there, and no packet leaves the machine.
    with pytest.raises(UploadError, match="could not reach"):
        upload_run(
            "http://127.0.0.1:1",
            "",
            metadata_json("owner/repo", "a" * 40, None, None, []),
            [report],
        )


def test_the_token_is_never_sent_in_the_clear_to_a_remote_host() -> None:
    with pytest.raises(UploadError, match="refusing to send the token in the clear"):
        endpoint("http://api.example.com", "/v1/runs")


def test_a_loopback_address_may_skip_tls() -> None:
    assert endpoint("http://127.0.0.1:8000", "/v1/runs") == "http://127.0.0.1:8000/v1/runs"
    assert endpoint("http://localhost:8000/", "/v1/runs") == "http://localhost:8000/v1/runs"


def test_https_anywhere_is_allowed() -> None:
    assert endpoint("https://api.example.com/", "/v1/runs") == "https://api.example.com/v1/runs"


def test_a_scheme_that_is_not_http_is_refused() -> None:
    with pytest.raises(UploadError, match="must be http or https"):
        endpoint("ftp://api.example.com", "/v1/runs")
