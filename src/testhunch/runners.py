"""Selections in the form each test runner accepts (docs/adr/0007).

A selection is the known tests to leave out. Each runner can only aim at some of them precisely;
a test the runner's filter cannot aim at alone is not left out, it runs.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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


@dataclass(frozen=True, slots=True)
class SurefireSkip:
    value: str  # for `mvn test -Dtest=...`; empty runs everything
    left_out: tuple[str, ...]


# A JUnit report name that names a Java method: "sumsPrices", "priceIsOdd(int)[2]".
_JAVA_METHOD_NAME = re.compile(r"^([A-Za-z_$][A-Za-z0-9_$]*)(?:\([^)]*\))?(?:\[.*\])?$")
_JVM_SOURCE_EXTENSIONS = (".java", ".kt", ".groovy", ".scala")


def surefire_exclusions(
    left_out: Iterable[str], kept: Iterable[str], changed_paths: Sequence[str] = ()
) -> SurefireSkip:
    """A `-Dtest` value leaving out as many of `left_out` as Surefire can aim at precisely.

    Checked with real Surefire 3.6.0 runs: `!pkg.Class#method` leaves out that method of that class
    only (a simple class name would match same-named classes in other packages); a method filter
    leaves out every invocation of a parameterized method, and `#method[2]` leaves out nothing. So
    a method is only left out when:

    - its report name is a Java method name, possibly with parameters and an index;
    - every known test with that class and method is left out (all invocations, all overloads);
    - the class's source file did not change, where an invocation could have been added.
    """
    wanted: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key in left_out:
        target = _surefire_target(key)
        if target:
            wanted[target].append(key)
    kept_targets = {_surefire_target(key) for key in kept}

    chosen = sorted(
        (cls, method)
        for cls, method in wanted
        if (cls, method) not in kept_targets and not _jvm_source_changed(cls, changed_paths)
    )
    value = ",".join(f"!{cls}#{method}" for cls, method in chosen)
    covered = sorted(key for target in chosen for key in wanted[target])
    return SurefireSkip(value, tuple(covered))


def _surefire_target(key: str) -> tuple[str, str] | None:
    cls, _, name = key.partition("::")
    match = _JAVA_METHOD_NAME.match(name)
    return (cls, match.group(1)) if cls and match else None


def _jvm_source_changed(cls: str, changed_paths: Sequence[str]) -> bool:
    # Nested classes (Outer$Inner) live in the outer class's file.
    stem = cls.split("$", 1)[0].replace(".", "/")
    sources = [stem + extension for extension in _JVM_SOURCE_EXTENSIONS]
    return any(path == src or path.endswith("/" + src) for path in changed_paths for src in sources)


@dataclass(frozen=True, slots=True)
class NextestSkip:
    expression: str  # for `cargo nextest run -E`; "all()" leaves nothing out
    left_out: tuple[str, ...]


# Escapes the equality matcher accepts (nexte.st, filterset DSL reference).
_NEXTEST_ESCAPES = str.maketrans({"\\": "\\\\", "/": "\\/", ")": "\\)", ",": "\\,"})


def nextest_filterset(left_out: Iterable[str], suites: Mapping[str, str | None]) -> NextestSkip:
    """A `cargo nextest run -E` expression leaving out each test of `left_out` precisely.

    A nextest key is "<binary id>::<test name>", and both parts may contain "::", so the binary
    id comes from the recorded suite (the report's classname). `binary_id(=id) & test(=name)` names
    one test: the equality matcher is exact, where the defaults (glob for binary ids, contains for
    test names) would match more. Checked with real cargo-nextest 0.9.144 runs. A key whose suite
    is unknown or does not prefix it is not aimed at.
    """
    chosen: list[tuple[str, str, str]] = []
    for key in sorted(left_out):
        binary = suites.get(key)
        if not binary or not key.startswith(binary + "::"):
            continue
        chosen.append((key, binary, key[len(binary) + 2 :]))
    if not chosen:
        return NextestSkip("all()", ())
    terms = " | ".join(
        f"(binary_id(={_nextest_escape(binary)}) & test(={_nextest_escape(name)}))"
        for _, binary, name in chosen
    )
    return NextestSkip(f"not ({terms})", tuple(key for key, _, _ in chosen))


def _nextest_escape(name: str) -> str:
    return name.translate(_NEXTEST_ESCAPES)


def _go_quote(name: str) -> str:
    return _GO_REGEXP_META.sub(r"\\\1", name)


def _go_split(key: str) -> tuple[str, str]:
    package, _, path = key.partition("::")
    return package, path
