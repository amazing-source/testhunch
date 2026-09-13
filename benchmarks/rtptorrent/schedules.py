"""The dataset authors' test schedules, to compare testhunch's ranking with (docs/adr/0010)."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


def read_schedules(path: Path) -> dict[int, tuple[list[str], set[str]]]:
    """One of the authors' schedules: per job, its distinct test classes in order, and the failing.

    A class listed twice in a job keeps its first position, and fails if any of its rows failed.
    """
    rows: dict[int, list[tuple[int, str, bool]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            failed = int(row["failures"]) + int(row["errors"]) > 0
            rows[int(row["travisJobId"])].append((int(row["index"]), row["testName"], failed))
    schedules: dict[int, tuple[list[str], set[str]]] = {}
    for job_id, entries in rows.items():
        order: list[str] = []
        for _, test, _ in sorted(entries):
            if test not in order:
                order.append(test)
        schedules[job_id] = (order, {test for _, test, failed in entries if failed})
    return schedules
