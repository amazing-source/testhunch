"""Reading LRTS, under the rule written in docs/adr/0033 before any score was computed.

Cheng, Wang, Jabbarvand and Marinov, *Revisiting Test-Case Prioritization on Long-Running Test
Suites*, ISSTA 2024. Ten projects, 2020 to 2024, 108 366 suite runs over 34 645 builds.

**Read straight out of the distributed zip**, one member at a time. Extracting it costs about 21 GB
and buys nothing: the archive holds one small table per suite run, and this replays one project at
a time. The archive carries no licence of its own, so it is read where it lies and never vendored
into this repository (ADR 0033).

**Only `testclass`, `duration` and `outcome` are read** from a class table. `last_outcome` sits in
the same file and is not read: it is precomputed per project and stage by start timestamp, without
protecting ties or overlapping builds, and a class never seen before is given the same `0` as one
that passed. Every history this benchmark uses is rebuilt backwards by the replay itself.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from testhunch.models import CaseResult, Status

ROOT = "ML_TCSP/long_running_test_suites"
ARTIFACT = f"{ROOT}/artifact"

# GitHub's compare response carries at most 300 files for the whole comparison, and says nothing
# about how many it left out. A list of exactly this length is a lower bound, not a fact, so the
# build's changed files are unknown rather than wrong (ADR 0033).
COMPARE_FILE_CAP = 300


@dataclass(frozen=True, slots=True)
class SuiteRun:
    """One stage of one build: the tests it ran and what they did."""

    stage_id: str
    results: tuple[CaseResult, ...]


@dataclass(frozen=True, slots=True)
class Build:
    """One CI build, with every stage that ran under it.

    `started` and `duration` are seconds, as the dataset writes them. `changed_files` is None when
    the comparison is missing or truncated, which is not the same as a build that changed nothing.
    """

    project: str
    pr_name: str
    build_id: str
    started: int
    duration: int
    head_sha: str
    trunk_sha: str
    changed_files: tuple[str, ...] | None
    stages: tuple[SuiteRun, ...]

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.project, self.pr_name, self.build_id)

    @property
    def ended(self) -> int:
        return self.started + self.duration

    def overlaps(self, other: Build) -> bool:
        """Whether the two ran at the same time, so neither could have seen the other's results."""
        return self.started < other.ended and other.started < self.ended


@dataclass(frozen=True, slots=True)
class BuildMeta:
    """A row of `dataset.csv`, before the class tables are read."""

    project: str
    pr_name: str
    build_id: str
    started: int
    duration: int
    head_sha: str
    trunk_sha: str
    stage_ids: tuple[str, ...]


class Archive:
    """The distributed zip, read in place."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._zip = zipfile.ZipFile(path)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> Archive:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @cached_property
    def _names(self) -> frozenset[str]:
        return frozenset(self._zip.namelist())

    @cached_property
    def _compare_pages(self) -> dict[tuple[str, str], list[str]]:
        """Comparison pages indexed by (project, `<PR>_build<ID>`).

        Built once. Scanning 417 906 member names per build instead would be a linear search
        inside a loop over 34 645 builds.
        """
        index: dict[tuple[str, str], list[str]] = defaultdict(list)
        marker = "/compare_commits/"
        for name in self._names:
            if not name.endswith(".json") or marker not in name:
                continue
            head, _, rest = name.partition(marker)
            project = head.rsplit("/", 1)[-1]
            build_directory = rest.split("/", 1)[0]
            index[(project, build_directory)].append(name)
        return {key: sorted(pages) for key, pages in index.items()}

    def projects(self) -> list[str]:
        return sorted({meta.project for meta in self.metadata()})

    @cached_property
    def _metadata(self) -> tuple[BuildMeta, ...]:
        """Every build of `dataset.csv`, its stages gathered, in the file's own order.

        The dataset counts a *suite run* per row, so a build with several stages has several rows.
        Start from this file and never from the directory listing: the archive holds class tables
        that no row references, 115 528 files against 108 366 rows.
        """
        stages: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        rows: dict[tuple[str, str, str], dict[str, str]] = {}
        with self._zip.open(f"{ROOT}/dataset.csv") as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
                key = (row["project"], row["pr_name"], row["build_id"])
                rows.setdefault(key, row)
                stages[key].append(row["stage_id"])
        return tuple(
            BuildMeta(
                project=key[0],
                pr_name=key[1],
                build_id=key[2],
                started=int(float(row["build_timestamp"])),
                duration=int(float(row["build_duration"])),
                head_sha=row["build_head_sha"],
                trunk_sha=row["trunk_sha"],
                stage_ids=tuple(stages[key]),
            )
            for key, row in rows.items()
        )

    def metadata(self, project: str | None = None) -> tuple[BuildMeta, ...]:
        if project is None:
            return self._metadata
        return tuple(meta for meta in self._metadata if meta.project == project)

    def class_table(self, meta: BuildMeta, stage_id: str) -> tuple[CaseResult, ...]:
        """One stage's results. The inner zip holds a single CSV, small enough to read whole."""
        name = (
            f"{ARTIFACT}/processed_test_result/{meta.project}/"
            f"{meta.pr_name}_build{meta.build_id}/stage_{stage_id}/test_class.csv.zip"
        )
        if name not in self._names:
            return ()
        inner = zipfile.ZipFile(io.BytesIO(self._zip.read(name)))
        member = inner.namelist()[0]
        text = io.StringIO(inner.read(member).decode("utf-8"), newline="")
        return tuple(_case(row) for row in csv.DictReader(text))

    def changed_files(self, meta: BuildMeta) -> tuple[str, ...] | None:
        """The paths the build changed, or None when they are unknown.

        One comparison per build, `trunk_sha...head_sha`, shared by every stage. Unknown means
        unknown: a missing comparison and a truncated one both return None rather than an empty
        change, because a build that changed nothing is a different thing (ADR 0033).
        """
        pages = self._compare_pages.get((meta.project, f"{meta.pr_name}_build{meta.build_id}"), [])
        if not pages:
            return None
        paths: set[str] = set()
        for page in pages:
            files = json.loads(self._zip.read(page)).get("files") or []
            if len(files) >= COMPARE_FILE_CAP:
                return None
            for entry in files:
                paths.add(entry["filename"])
                # A rename changes two paths, and the old one is what a test file used to be called.
                if entry.get("previous_filename"):
                    paths.add(entry["previous_filename"])
        return tuple(sorted(paths))

    def build(self, meta: BuildMeta) -> Build:
        return Build(
            project=meta.project,
            pr_name=meta.pr_name,
            build_id=meta.build_id,
            started=meta.started,
            duration=meta.duration,
            head_sha=meta.head_sha,
            trunk_sha=meta.trunk_sha,
            changed_files=self.changed_files(meta),
            stages=tuple(
                SuiteRun(stage_id, self.class_table(meta, stage_id)) for stage_id in meta.stage_ids
            ),
        )


def iter_builds(archive: Archive, project: str) -> Iterator[Build]:
    """One project's builds, oldest first, read one at a time.

    Ordered by start time, and by build id within a tie: the archive holds 211 groups of tied
    timestamps, and a stable order matters because the replay decides what a build may know from
    the times, not from this order (ADR 0033).
    """
    for meta in sorted(archive.metadata(project), key=lambda m: (m.started, m.build_id)):
        yield archive.build(meta)


def concurrent(builds: Sequence[Build]) -> list[list[Build]]:
    """Builds grouped by sharing a head commit and running at the same time.

    Two builds of the same project, on the same `build_head_sha`, whose execution intervals
    intersect, are one event: a re-run and its original, or two stages started together.
    """
    groups: list[list[Build]] = []
    # Swept in start order, so a group whose last build ended before this one started can never
    # match again and leaves the active set. Without that this is quadratic, and Kafka alone brings
    # about fifteen thousand builds.
    active: list[tuple[int, list[Build]]] = []  # (the group's latest end, the group)
    for build in sorted(builds, key=lambda b: (b.started, b.build_id)):
        active = [(end, group) for end, group in active if end > build.started]
        for index, (end, group) in enumerate(active):
            if group[0].head_sha == build.head_sha and any(build.overlaps(o) for o in group):
                group.append(build)
                active[index] = (max(end, build.ended), group)
                break
        else:
            group = [build]
            groups.append(group)
            active.append((build.ended, group))
    return groups


def _case(row: dict[str, str]) -> CaseResult:
    """One class in one stage. `outcome` is 1 for a failure and 0 for a pass; skipped are gone.

    The duration is seconds in the file and milliseconds everywhere in testhunch. It is kept as
    None when the field is empty rather than turned into a zero: an unknown cost is not a free test
    (CLAUDE.md, and docs/adr/0017 which divides by it).
    """
    name = row["testclass"]
    raw = row.get("duration", "").strip()
    duration_ms = round(float(raw) * 1000) if raw else None
    outcome = row["outcome"].strip()
    if outcome not in ("0", "1"):
        # Jenkins' FAILED and REGRESSION became 1, PASSED and FIXED became 0, and SKIPPED was
        # dropped. Anything else means this file is not what this reader was written against.
        raise ValueError(f"{name}: unexpected outcome {outcome!r}, expected 0 or 1")
    status = Status.FAILED if outcome == "1" else Status.PASSED
    return CaseResult(
        key=name,
        name=name,
        suite=None,
        file=None,
        status=status,
        duration_ms=duration_ms,
        message=None,
    )
