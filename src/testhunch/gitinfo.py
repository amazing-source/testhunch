"""Read commits, branches and changed files through the git command line."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from testhunch.models import FileChange


class GitError(RuntimeError):
    """git is missing, or a git command failed."""


def _git(args: list[str], cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    if proc.returncode != 0:
        raise GitError(f"`git {' '.join(args)}` failed: {proc.stderr.strip()}")
    return proc.stdout


def rev_parse(ref: str, cwd: Path | None = None) -> str:
    """Resolve a ref such as HEAD or origin/main to a full commit SHA."""
    try:
        return _git(["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], cwd).strip()
    except GitError as exc:
        raise GitError(
            f"cannot resolve {ref!r} to a commit. Run this inside a git repository with at "
            "least one commit, or pass the tested commit with --commit. "
            "In CI, a shallow checkout can also hide older commits (use fetch-depth: 0)."
        ) from exc


def current_branch(cwd: Path | None = None) -> str | None:
    """The branch being tested. In GitHub Actions the checkout is detached, so ask the env."""
    for variable in ("GITHUB_HEAD_REF", "GITHUB_REF_NAME"):
        value = os.environ.get(variable)
        if value:
            return value
    try:
        return _git(["branch", "--show-current"], cwd).strip() or None
    except GitError:
        return None


def changed_files(base: str, head: str = "HEAD", cwd: Path | None = None) -> tuple[FileChange, ...]:
    """Files changed on `head` since it forked from `base` (three-dot diff, merge base).

    In CI this needs history: with actions/checkout, set `fetch-depth: 0`.
    """
    for ref in (base, head):
        if ref.startswith("-"):  # would be read as a git option, not a revision
            raise GitError(f"invalid revision {ref!r}")
    output = _git(["diff", "--name-status", "-z", "-M", "--no-color", f"{base}...{head}"], cwd)
    return parse_name_status_z(output)


def parse_name_status_z(output: str) -> tuple[FileChange, ...]:
    """Parse `git diff --name-status -z`: NUL-separated, renames and copies carry two paths."""
    fields = output.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    changes: list[FileChange] = []
    i = 0
    try:
        while i < len(fields):
            letter = fields[i][:1]
            if letter in ("R", "C"):
                changes.append(FileChange(fields[i + 2], letter, old_path=fields[i + 1]))
                i += 3
            else:
                changes.append(FileChange(fields[i + 1], letter))
                i += 2
    except IndexError as exc:
        raise GitError("unexpected output from git diff --name-status -z") from exc
    return tuple(changes)


_REMOTE = re.compile(r"(?:[:/])([^/:]+)/([^/]+?)(?:\.git)?/?$")


def repo_slug_from_remote(url: str) -> str | None:
    """owner/name from an https or ssh remote URL."""
    match = _REMOTE.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def detect_repo(cwd: Path | None = None) -> str:
    """A stable name for the repository whose tests are being recorded."""
    from_env = os.environ.get("GITHUB_REPOSITORY")
    if from_env:
        return from_env
    try:
        slug = repo_slug_from_remote(_git(["remote", "get-url", "origin"], cwd))
    except GitError:
        slug = None
    return slug or (cwd or Path.cwd()).resolve().name
