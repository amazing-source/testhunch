"""Selections in the form each test runner accepts (docs/adr/0007).

A selection is the known tests to leave out. Each runner can only aim at some of them precisely;
a test the runner's filter cannot aim at alone is not left out, it runs.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

# The characters Go's regexp.QuoteMeta escapes.
_GO_REGEXP_META = re.compile(r"([\\.+*?()|\[\]{}^$])")
_GO_LIST_PACKAGE_LINE = re.compile(r"^(ok|FAIL|\?)\s+(\S+)")


@dataclass(frozen=True, slots=True)
class GoSkip:
    pattern: str  # for `go test -skip`; empty leaves nothing out
    left_out: tuple[str, ...]  # the keys of every test the pattern leaves out


def parse_go_test_list(text: str) -> dict[str, set[str]]:
    """Top-level test names per package, from the output of `go test -list '.*' ./...`.

    Each package's names are followed by its `ok  <package>` line. Names after the last such line
    belong to no package and are dropped, so those tests can never be left out.
    """
    packages: dict[str, set[str]] = {}
    names: list[str] = []
    for line in text.splitlines():
        match = _GO_LIST_PACKAGE_LINE.match(line)
        if match:
            packages.setdefault(match.group(2), set()).update(names)
            names = []
        elif line.strip() and not line[0].isspace():
            names.append(line.strip())
    return packages


def go_skip(
    left_out: Iterable[str],
    kept: Iterable[str],
    test_list: dict[str, set[str]],
    changed_paths: Sequence[str] = (),
) -> GoSkip:
    """A `go test -skip` pattern leaving out as many of `left_out` as Go can aim at precisely.

    `-skip` applies to every package in the run, splits on `/` into one regexp per subtest level,
    and on top-level `|` into alternatives (src/testing/match.go). So a test is only left out when:

    - its top-level name belongs to its own package alone in the current code (`test_list`);
    - none of its known subtests is kept, because leaving a test out leaves its subtests out;
    - no `_test.go` file changed in a directory named like its package, where a subtest could
      have been added to it: a new test always runs.
    """
    left = {_go_split(key) for key in left_out}
    kept_paths = {_go_split(key) for key in kept}
    owners: dict[str, set[str]] = defaultdict(set)
    for package, names in test_list.items():
        for name in names:
            owners[name].add(package)
    changed_dirs = [
        PurePosixPath(path).parent.name for path in changed_paths if path.endswith("_test.go")
    ]
    if any(d == "" for d in changed_dirs):
        # A test file at the module root: its package has no directory name to recognise it by.
        return GoSkip("", ())

    chosen: list[tuple[str, str]] = []
    # Parents before their subtests, so a chosen parent covers them.
    for package, path in sorted(left, key=lambda p: (p[0], p[1].count("/"), p[1])):
        top = path.split("/", 1)[0]
        if owners.get(top) != {package}:
            continue
        if package.rsplit("/", 1)[-1] in changed_dirs:
            continue
        if any(p == package and k.startswith(path + "/") for p, k in kept_paths):
            continue
        if any(p == package and path.startswith(c + "/") for p, c in chosen):
            continue
        chosen.append((package, path))

    covered = sorted(
        f"{package}::{path}"
        for package, path in left
        if any(p == package and (path == c or path.startswith(c + "/")) for p, c in chosen)
    )
    pattern = "|".join(
        "/".join(f"^{_go_quote(part)}$" for part in path.split("/"))
        for _, path in sorted(chosen, key=lambda p: (p[1], p[0]))
    )
    return GoSkip(pattern, tuple(covered))


def _go_quote(name: str) -> str:
    return _GO_REGEXP_META.sub(r"\\\1", name)


def _go_split(key: str) -> tuple[str, str]:
    package, _, path = key.partition("::")
    return package, path
