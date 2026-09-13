from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from testhunch.gitinfo import (
    GitError,
    changed_files,
    parse_name_status_z,
    repo_slug_from_remote,
    rev_parse,
)
from testhunch.models import FileChange

Git = Callable[..., str]


def test_changed_files_since_merge_base(git_repo: Path, git: Git) -> None:
    (git_repo / "kept.py").write_text("x = 3\n")
    (git_repo / "removed.py").unlink()
    git(git_repo, "mv", "dir with space/old name.py", "dir with space/new name.py")
    (git_repo / "added.py").write_text("z = 4\n")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "--quiet", "-m", "change")

    changes = set(changed_files("base", "HEAD", cwd=git_repo))

    assert changes == {
        FileChange("kept.py", "M"),
        FileChange("removed.py", "D"),
        FileChange("added.py", "A"),
        FileChange("dir with space/new name.py", "R", old_path="dir with space/old name.py"),
    }


def test_rev_parse_resolves_full_sha(git_repo: Path, git: Git) -> None:
    assert rev_parse("HEAD", cwd=git_repo) == git(git_repo, "rev-parse", "HEAD")


def test_unknown_ref_is_a_git_error(git_repo: Path) -> None:
    with pytest.raises(GitError, match="cannot resolve 'does-not-exist' to a commit"):
        rev_parse("does-not-exist", cwd=git_repo)


def test_option_like_refs_are_refused() -> None:
    with pytest.raises(GitError, match="invalid revision"):
        changed_files("--output=/tmp/pwned")


def test_truncated_diff_output_is_an_error() -> None:
    with pytest.raises(GitError):
        parse_name_status_z("R100\0only-one-path\0")


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://github.com/amazing-source/testhunch.git", "amazing-source/testhunch"),
        ("https://github.com/amazing-source/testhunch", "amazing-source/testhunch"),
        ("git@github.com:amazing-source/testhunch.git", "amazing-source/testhunch"),
        ("ssh://git@gitlab.example.com/group/project.git\n", "group/project"),
    ],
)
def test_repo_slug_from_remote(url: str, slug: str) -> None:
    assert repo_slug_from_remote(url) == slug
