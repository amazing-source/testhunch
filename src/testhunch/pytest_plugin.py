"""pytest plugin: deselect the tests that `testhunch select` left out (docs/adr/0007).

    testhunch select --budget 25% --runner pytest > skip.txt
    pytest -p testhunch.pytest_plugin --testhunch-skip=skip.txt

Loaded explicitly with `-p`, never automatically: installing testhunch changes no test run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKIP = pytest.StashKey[frozenset[str]]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.getgroup("testhunch").addoption(
        "--testhunch-skip",
        metavar="FILE",
        default=None,
        help="deselect the tests whose testhunch keys FILE lists, one per line",
    )


def pytest_configure(config: pytest.Config) -> None:
    path = config.getoption("testhunch_skip")
    if path is None:
        return
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise pytest.UsageError(f"testhunch: cannot read the skip list {path}: {exc}") from exc
    config.stash[_SKIP] = frozenset(line.strip() for line in lines if line.strip())


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip = config.stash.get(_SKIP, frozenset())
    if not skip:
        return
    prefix = config.getoption("junitprefix", None)
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        (deselected if junit_key(item.nodeid, prefix) in skip else kept).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


def junit_key(nodeid: str, prefix: str | None = None) -> str:
    """The key testhunch gives this test when it reads pytest's JUnit XML report.

    Mirrors how pytest's junitxml turns a node id into a classname (mangle_test_address), so a
    listed key matches exactly the test it was recorded for.
    """
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    classname = ".".join([prefix, *names[:-1]] if prefix else names[:-1])
    return f"{classname}::{names[-1]}"
