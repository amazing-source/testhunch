"""Reading RTPTorrent (docs/adr/0010), on a real extract of the dataset in tests/fixtures."""

from __future__ import annotations

import io
import json
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from benchmarks.rtptorrent.data import HttpRangeFile, class_result, fetch_project, load_jobs
from testhunch.models import Status

EXTRACT = Path(__file__).parent / "fixtures" / "rtptorrent" / "adamfisk@LittleProxy"
PROJECT = "adamfisk@LittleProxy"


def row(**overrides: str) -> dict[str, str]:
    base = {
        "testName": "org.littleshoot.proxy.HttpFilterTest",
        "duration": "0.719",
        "count": "3",
        "failures": "0",
        "errors": "0",
        "skipped": "0",
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    ("counts", "status"),
    [
        ({"failures": "1", "errors": "1"}, Status.FAILED),
        ({"errors": "2"}, Status.ERROR),
        ({"skipped": "3"}, Status.SKIPPED),
        ({"skipped": "1"}, Status.PASSED),
        ({"count": "0"}, Status.PASSED),
    ],
)
def test_a_test_class_row_becomes_one_result(counts: dict[str, str], status: Status) -> None:
    assert class_result(row(**counts)).status is status


@pytest.mark.parametrize(("duration", "ms"), [("0.719", 719), ("0.0", 0), ("-1.5", None)])
def test_negative_durations_are_unknown(duration: str, ms: int | None) -> None:
    assert class_result(row(duration=duration)).duration_ms == ms


def test_a_class_is_its_own_key_and_its_file_is_not_guessed() -> None:
    result = class_result(row())
    assert (result.key, result.file) == ("org.littleshoot.proxy.HttpFilterTest", None)


def test_jobs_come_in_job_id_order_with_their_commits_and_changed_files() -> None:
    jobs = load_jobs(EXTRACT)

    assert len(jobs) == 80
    assert [j.job_id for j in jobs] == sorted(j.job_id for j in jobs)
    by_id = {job.job_id: job for job in jobs}
    # 1053609 builds several commits: its changed files are the union of their patches.
    assert len(by_id[1053609].commits) > 1
    assert by_id[1053609].changed_files
    # 2286063 has no row in tr_all_built_commits.csv: its changes are unknown, not empty.
    assert (by_id[2286063].commits, by_id[2286063].changed_files) == (frozenset(), None)
    failing = by_id[4628724]
    assert any(result.status is Status.FAILED for result in failing.results)
    assert len(failing.results) == 9


class _ArchiveHandler(BaseHTTPRequestHandler):
    payload = b""
    honour_ranges = True

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()

    def do_GET(self) -> None:
        requested = self.headers.get("Range")
        if requested and self.honour_ranges:
            first, last = (int(n) for n in requested.removeprefix("bytes=").split("-"))
            body = self.payload[first : last + 1]
            self.send_response(206)
        else:
            body = self.payload
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # quiet test output
        pass


def archive_bytes() -> bytes:
    """A zip laid out like RTPTorrent 1.1, holding the extract and one foreign commit row."""
    short = PROJECT.split("@", 1)[1]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        folder = f"rtp-torrent/{PROJECT}"
        archive.write(EXTRACT / "results.csv", f"{folder}/{PROJECT}.csv")
        archive.write(EXTRACT / "patches.csv", f"{folder}/{PROJECT}-patches.csv")
        archive.write(EXTRACT / "offenders.csv", f"{folder}/{PROJECT}-offenders.csv")
        for strategy in ("untreated", "recently-failed"):
            archive.write(
                EXTRACT / "baseline" / f"{strategy}.csv",
                f"{folder}/baseline/{short}@{strategy}.csv",
            )
        commits = (EXTRACT / "commits.csv").read_text(encoding="utf-8")
        archive.writestr("rtp-torrent/tr_all_built_commits.csv", commits + "999,deadbeef\n")
    return buffer.getvalue()


@pytest.fixture
def server() -> Iterator[tuple[str, type[_ArchiveHandler]]]:
    handler = type("Handler", (_ArchiveHandler,), {"payload": archive_bytes()})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/rtp-torrent-v11.zip", handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_a_project_is_fetched_with_range_requests_and_cached(
    server: tuple[str, type[_ArchiveHandler]], tmp_path: Path
) -> None:
    url, _ = server
    directory = fetch_project(PROJECT, tmp_path, url)

    assert (directory / "results.csv").read_bytes() == (EXTRACT / "results.csv").read_bytes()
    commits = (directory / "commits.csv").read_text(encoding="utf-8")
    assert commits == (EXTRACT / "commits.csv").read_text(encoding="utf-8")  # 999 is not ours
    source = json.loads((directory / "source.json").read_text(encoding="utf-8"))
    assert f"rtp-torrent/{PROJECT}/{PROJECT}.csv" in source["members_crc32"]
    # Strategies the archive does not hold are listed, not silently dropped.
    assert "rtp-torrent/adamfisk@LittleProxy/baseline/LittleProxy@random.csv" in source["missing"]
    assert len(load_jobs(directory)) == 80

    # A second call reads the cache and never contacts the server.
    fetch_project(PROJECT, tmp_path, "http://127.0.0.1:9/unreachable")


def test_a_server_that_ignores_ranges_is_refused(
    server: tuple[str, type[_ArchiveHandler]],
) -> None:
    url, handler = server
    handler.honour_ranges = False
    remote = HttpRangeFile(url)
    with pytest.raises(OSError, match="ignored the range request"):
        remote.read(10)
