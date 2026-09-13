from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import quote

import pytest

from testhunch.store import SqlStore, open_store

# Real pytest sessions, for the pytest plugin.
pytest_plugins = ["pytester"]

Git = Callable[..., str]


def _postgres_url() -> str:
    url = os.environ.get("TESTHUNCH_TEST_POSTGRES_URL")
    if url:
        return url
    if os.environ.get("TESTHUNCH_REQUIRE_POSTGRES"):
        pytest.fail("TESTHUNCH_REQUIRE_POSTGRES is set but TESTHUNCH_TEST_POSTGRES_URL is not")
    pytest.skip("set TESTHUNCH_TEST_POSTGRES_URL to run the Postgres contract tests")


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path.as_posix()}/history.db"


@pytest.fixture(params=["sqlite", "postgres"])
def unmigrated_store(request: pytest.FixtureRequest, sqlite_url: str) -> Iterator[SqlStore]:
    """An empty store without any schema. Every contract test runs once per database."""
    if request.param == "sqlite":
        yield open_store(sqlite_url)
        return

    url = _postgres_url()
    psycopg = pytest.importorskip("psycopg")
    # Each test gets its own schema, so tests cannot see each other's rows.
    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    separator = "&" if "?" in url else "?"
    scoped = f"{url}{separator}options={quote(f'-c search_path={schema}')}"
    try:
        yield open_store(scoped)
    finally:
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def store(unmigrated_store: SqlStore) -> SqlStore:
    """A migrated, empty store."""
    unmigrated_store.migrate()
    return unmigrated_store


@pytest.fixture
def git() -> Git:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")

    def run(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return run


@pytest.fixture
def git_repo(tmp_path: Path, git: Git) -> Path:
    """A repository with one commit on main and a `base` branch pointing at it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet", "--initial-branch=main")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "kept.py").write_text("x = 1\n")
    (repo / "removed.py").write_text("y = 2\n")
    (repo / "dir with space").mkdir()
    (repo / "dir with space" / "old name.py").write_text("def f():\n    return 42\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "base")
    git(repo, "branch", "base")
    return repo
