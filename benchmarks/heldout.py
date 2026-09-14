"""Every look at the held-out projects leaves a trace (docs/adr/0013, 0016).

The `--held-out` flags stop a tuning run from reading held-out projects by accident. They cannot
stop someone from replaying them, reading the result and tuning anyway. What they can do is make
the look impossible to hide: each one is written to a ledger in the repository, before the replay
starts, and only from a commit that is already frozen and pushed.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

# Anchored to this file, not to the working directory: a run started from a worktree or another
# directory must still write to the repository's own ledger, or it would leave no trace at all.
LEDGER = Path(__file__).resolve().parents[1] / "benchmarks" / "results" / "held-out-log.md"

_HEADER = """# Looks at the held-out projects

Written by the benchmark commands themselves (`benchmarks/heldout.py`), one row per run that reads
a held-out project, appended before the replay starts. A version is tuned on the development
projects; the held-out projects only measure it (docs/adr/0013). Counting these rows is how a
reader checks that the rule was followed: many rows for the same version, with the ranking changing
in between, would mean the held-out projects had become a tuning set (docs/adr/0016).

| Date (UTC) | Commit | Version | Command | Replayed | Projects |
|---|---|---|---|---|---|
"""


class NotFrozen(RuntimeError):
    """The checkout is not a commit that others can look at: the run must not happen."""


def _git(*args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, encoding="utf-8", check=False
        )
    except FileNotFoundError as exc:
        raise NotFrozen(
            "git is not installed: a held-out replay must name a frozen commit"
        ) from exc
    if done.returncode != 0:
        raise NotFrozen(f"`git {' '.join(args)}` failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _uncommitted(ledger: Path) -> str:
    """Uncommitted changes, except the ledger's own rows.

    A campaign is often two commands: the second would refuse because the first appended its row.
    The ledger is the one file a held-out run is meant to change, and what protects it is git
    history, not this check, so a row of its own never blocks the next look.
    """
    try:
        allowed = (
            ledger.resolve().relative_to(Path(_git("rev-parse", "--show-toplevel"))).as_posix()
        )
    except ValueError:  # a ledger outside the repository, as the tests use
        allowed = None
    lines = [
        line
        for line in _git("status", "--porcelain").splitlines()
        if line[3:].strip().strip('"') != allowed
    ]
    return "\n".join(lines)


def frozen_commit(ledger: Path | None = None) -> str:
    """The commit being replayed, once it is certain that it is public and unmodified.

    ADR 0013 asks for a version committed and listed before a held-out replay. Checking it here
    turns that promise into a refusal: nothing uncommitted, and the commit already on a remote, so
    the code that produced a held-out number cannot be edited afterwards.
    """
    dirty = _uncommitted(LEDGER if ledger is None else ledger)
    if dirty:
        raise NotFrozen(
            "the working tree has uncommitted changes, so the version replayed could not be "
            "checked afterwards. Commit them first (docs/adr/0016):\n" + dirty
        )
    commit = _git("rev-parse", "HEAD")
    if not _git("branch", "--remotes", "--contains", commit):
        raise NotFrozen(
            f"commit {commit[:12]} is on no remote branch: push it before replaying held-out "
            "projects, so that the version measured stays readable by anyone (docs/adr/0016)"
        )
    return commit


def record_peek(
    command: str,
    projects: Sequence[str],
    replayed: str,
    version: str,
    ledger: Path | None = None,
) -> str:
    """Append this run to the ledger and return the frozen commit it replays.

    Called before the replay: a run that is interrupted, or whose numbers are thrown away, still
    leaves its row. Hiding a look then means deleting a line someone can find in git history.
    """
    ledger = LEDGER if ledger is None else ledger
    commit = frozen_commit(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.write_text(_HEADER, encoding="utf-8")
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    row = (
        f"| {day} | `{commit[:12]}` | {version} | `{command}` | {replayed} | "
        f"{', '.join(projects)} |\n"
    )
    with ledger.open("a", encoding="utf-8") as out:
        out.write(row)
    return commit
