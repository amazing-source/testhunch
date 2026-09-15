"""What the front page tells a reader to install is the version this repository would publish.

testhunch 0.2.0 sat on PyPI for two days while `main` already carried a different ranking (ADR 0015)
and a different meaning for `--budget` (ADR 0017). The README measured the ranking nobody could
install and told the reader to pin `@v0.2.0`, the row its own tables used as the baseline to beat.
Nothing caught it, because no test compared the two. These do.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import testhunch

ROOT = Path(__file__).resolve().parents[1]


def declared_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def test_the_readme_pins_the_version_this_repository_publishes() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    # Every `@vX.Y.Z` of the README: the Action examples, and the sentence explaining the pin.
    pinned = set(re.findall(r"@v(\d+\.\d+\.\d+)", readme))

    assert pinned == {declared_version()}, (
        "the README pins a version this repository does not publish: bump one or the other"
    )


def test_the_documentation_site_pins_that_same_version() -> None:
    """The site tells readers what to install too, and it went stale for the same reason.

    The ADR pages are left out on purpose: they are dated records of what was true when they were
    written, and rewriting a number in one would be rewriting history.
    """
    pages = [p for p in (ROOT / "docs").rglob("*.mdx") if "adr" not in p.parts]
    assert pages, "no documentation page found: this test would pass by looking at nothing"

    pinned: dict[str, set[str]] = {}
    for page in pages:
        text = page.read_text(encoding="utf-8")
        found = set(re.findall(r"@v(\d+\.\d+\.\d+)", text))
        found |= set(re.findall(r"testhunch:(\d+\.\d+\.\d+)", text))
        if found:
            pinned[str(page.relative_to(ROOT))] = found

    stale = {page: found for page, found in pinned.items() if found != {declared_version()}}
    assert not stale, f"pages pinning a version this repository does not publish: {stale}"


def test_the_installed_version_is_the_declared_one() -> None:
    """The results and the ledger record `__version__` as provenance, so it has to be the real one.

    It comes from the installed package metadata: after a version bump, `uv sync` has to run before
    a benchmark writes that field into a file someone will read later.
    """
    assert testhunch.__version__ == declared_version()
