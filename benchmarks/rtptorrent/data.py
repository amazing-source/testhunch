"""Fetch one RTPTorrent project and read it as testhunch runs (docs/adr/0010).

The archive is 5 GB, most of it git repositories the benchmark does not need. Only a project's CSV
files are read, through HTTP range requests; `zipfile` checks each file's CRC-32 as it reads it.
"""

from __future__ import annotations

import csv
import io
import json
import math
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from testhunch.models import CaseResult, Status

ARCHIVE_URL = "https://zenodo.org/api/records/4046180/files/rtp-torrent-v11.zip/content"
ROOT = "rtp-torrent"
STRATEGIES = (
    "untreated",
    "random",
    "recently-failed",
    "matrix-naive",
    "matrix-conditional-prob",
    "optimal-failure",
)


class HttpRangeFile(io.RawIOBase):
    """A read-only, seekable remote file, read with HTTP range requests."""

    def __init__(self, url: str, timeout: float = 120) -> None:
        self._timeout = timeout
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            self.url = response.geturl()  # after redirects, so reads do not repeat them
            self.size = int(response.headers["Content-Length"])
        self._position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._position, io.SEEK_END: self.size}[whence]
        if base + offset < 0:
            raise ValueError("negative seek position")
        self._position = base + offset
        return self._position

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        if self._position >= self.size or not len(buffer):
            return 0
        last = min(self._position + len(buffer), self.size) - 1
        request = urllib.request.Request(
            self.url, headers={"Range": f"bytes={self._position}-{last}"}
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            if response.status != 206:
                raise OSError(f"the server ignored the range request (HTTP {response.status})")
            data = response.read()
        memoryview(buffer)[: len(data)] = data
        self._position += len(data)
        return len(data)


def open_archive(url: str = ARCHIVE_URL) -> zipfile.ZipFile:
    remote = io.BufferedReader(HttpRangeFile(url), buffer_size=8 * 1024 * 1024)
    return zipfile.ZipFile(remote)


def fetch_project(project: str, cache: Path, url: str = ARCHIVE_URL) -> Path:
    """Copy one project's files from the archive into `cache/<project>`, unless already there.

    `commits.csv` keeps only the rows of `tr_all_built_commits.csv` for the project's jobs.
    """
    target = cache / project
    if (target / "source.json").exists():
        return target
    short = project.split("@", 1)[1]
    required = {
        "results.csv": f"{ROOT}/{project}/{project}.csv",
        "patches.csv": f"{ROOT}/{project}/{project}-patches.csv",
    }
    optional = {
        "offenders.csv": f"{ROOT}/{project}/{project}-offenders.csv",
        **{
            f"baseline/{strategy}.csv": f"{ROOT}/{project}/baseline/{short}@{strategy}.csv"
            for strategy in STRATEGIES
        },
    }
    (target / "baseline").mkdir(parents=True, exist_ok=True)
    crcs: dict[str, str] = {}
    missing: list[str] = []
    with open_archive(url) as archive:
        present = set(archive.namelist())
        for local, member in {**required, **optional}.items():
            if member not in present:
                if local in required:
                    raise FileNotFoundError(f"{member} is not in the RTPTorrent archive")
                missing.append(member)
                continue
            (target / local).write_bytes(archive.read(member))  # raises on a bad CRC-32
            crcs[member] = f"{archive.getinfo(member).CRC:08x}"
        with (target / "results.csv").open(newline="", encoding="utf-8") as results:
            jobs = {row["travisJobId"] for row in csv.DictReader(results)}
        commits_member = f"{ROOT}/tr_all_built_commits.csv"
        with (
            archive.open(commits_member) as raw,
            (target / "commits.csv").open("w", newline="", encoding="utf-8") as out,
        ):
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(["tr_job_id", "git_commit_id"])
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
                if row["tr_job_id"] in jobs:
                    writer.writerow([row["tr_job_id"], row["git_commit_id"]])
        crcs[commits_member] = f"{archive.getinfo(commits_member).CRC:08x}"
    source = {"archive": url, "project": project, "members_crc32": crcs, "missing": missing}
    (target / "source.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    return target


@dataclass(frozen=True, slots=True)
class Job:
    job_id: int
    commits: frozenset[str]  # empty when the dataset maps the job to no commit
    changed_files: tuple[str, ...] | None  # None when unknown: no commit mapping
    results: tuple[CaseResult, ...]


def load_jobs(directory: Path) -> list[Job]:
    """The project's jobs in job id order, which follows build numbers (docs/adr/0010)."""
    results: dict[int, list[CaseResult]] = defaultdict(list)
    for row in _rows(directory / "results.csv"):
        results[int(row["travisJobId"])].append(class_result(row))
    commits: dict[int, set[str]] = defaultdict(set)
    for row in _rows(directory / "commits.csv"):
        commits[int(row["tr_job_id"])].add(row["git_commit_id"])
    patches: dict[str, set[str]] = defaultdict(set)
    for row in _rows(directory / "patches.csv"):
        patches[row["sha"]].add(row["name"])

    jobs = []
    for job_id in sorted(results):
        job_commits = frozenset(commits.get(job_id, ()))
        changed = (
            tuple(sorted(set().union(*(patches.get(sha, set()) for sha in job_commits))))
            if job_commits
            else None
        )
        jobs.append(Job(job_id, job_commits, changed, tuple(results[job_id])))
    return jobs


def class_result(row: dict[str, str]) -> CaseResult:
    """One test class's result in one job (docs/adr/0010)."""
    count, failures = int(row["count"]), int(row["failures"])
    errors, skipped = int(row["errors"]), int(row["skipped"])
    if failures:
        status = Status.FAILED
    elif errors:
        status = Status.ERROR
    elif count and skipped == count:
        status = Status.SKIPPED
    else:
        status = Status.PASSED
    seconds = float(row["duration"])
    duration_ms = round(seconds * 1000) if math.isfinite(seconds) and seconds >= 0 else None
    name = row["testName"]
    return CaseResult(name, name, None, None, status, duration_ms, None)


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        yield from csv.DictReader(file)
