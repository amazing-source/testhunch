"""Mutants of the lines a commit changed: one token replaced, strings and comments left alone.

See docs/adr/0012.
"""

from __future__ import annotations

import hashlib
import io
import random
import re
import subprocess
import tokenize
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

MUTANTS_PER_COMMIT = 3

_OPERATORS = {
    "==": "!=",
    "!=": "==",
    "<": ">=",
    ">=": "<",
    ">": "<=",
    "<=": ">",
    "+": "-",
    "-": "+",
}
_PYTHON_NAMES = {"and": "or", "or": "and", "True": "False", "False": "True"}
_GO_WORDS = {"&&": "||", "||": "&&", "true": "false", "false": "true"}


@dataclass(frozen=True, slots=True)
class Site:
    """A token that can be mutated: 1-based line, 0-based column in characters."""

    line: int
    column: int
    original: str
    replacement: str


@dataclass(frozen=True, slots=True)
class Mutant:
    path: str
    line: int
    column: int
    original: str
    replacement: str
    content: str  # the whole mutated file


def added_lines(diff: str) -> dict[str, set[int]]:
    """Per file, the line numbers in the new version that `git diff -U0` shows as added."""
    lines: dict[str, set[int]] = {}
    path: str | None = None
    for text in diff.splitlines():
        if text.startswith("+++ "):
            path = text[6:] if text.startswith("+++ b/") else None
        elif text.startswith("@@") and path is not None:
            match = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", text)
            if match is None:
                raise ValueError(f"unexpected hunk header: {text!r}")
            start, count = int(match[1]), int(match[2] or 1)
            lines.setdefault(path, set()).update(range(start, start + count))
    return lines


def python_sites(source: str) -> Iterator[Site]:
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        text = token.string
        replacement = None
        if token.type == tokenize.OP:
            replacement = _OPERATORS.get(text)
        elif token.type == tokenize.NAME:
            replacement = _PYTHON_NAMES.get(text)
        elif token.type == tokenize.NUMBER and text.isdigit():
            replacement = str(int(text) + 1)
        if replacement is not None:
            yield Site(token.start[0], token.start[1], text, replacement)


_GO_TOKEN = re.compile(
    r"""
    (?P<skip> //[^\n]* | /\*.*?\*/ | "(?:\\.|[^"\\\n])*" | `[^`]* ` | '(?:\\.|[^'\\\n])*' )
    | (?P<number> \b\d[\w.]* (?:[eEpP][+-]\d+)? )
    | (?P<word> [A-Za-z_]\w* )
    | (?P<operator> <<= | >>= | &\^= | \.\.\. | && | \|\| | <- | \+\+ | -- | == | != | <= | >=
                  | := | \+= | -= | \*= | /= | %= | &= | \|= | \^= | << | >> | &\^
                  | [-+*/%&|^<>=!~.,;:()\[\]{}] )
    """,
    re.VERBOSE | re.DOTALL,
)


def go_sites(source: str) -> Iterator[Site]:
    line_starts = [0] + [index + 1 for index, char in enumerate(source) if char == "\n"]
    line = 0
    for match in _GO_TOKEN.finditer(source):
        text = match.group()
        if match.lastgroup == "skip":
            continue
        replacement = None
        if match.lastgroup == "operator":
            replacement = _OPERATORS.get(text) or _GO_WORDS.get(text)
        elif match.lastgroup == "word":
            replacement = _GO_WORDS.get(text)
        elif match.lastgroup == "number" and text.isdigit():
            replacement = str(int(text) + 1)
        if replacement is None:
            continue
        while line + 1 < len(line_starts) and line_starts[line + 1] <= match.start():
            line += 1
        yield Site(line + 1, match.start() - line_starts[line], text, replacement)


def apply(source: str, site: Site) -> str:
    lines = source.splitlines(keepends=True)
    text = lines[site.line - 1]
    if text[site.column : site.column + len(site.original)] != site.original:
        raise ValueError(f"line {site.line} has no {site.original!r} at column {site.column}")
    end = site.column + len(site.original)
    lines[site.line - 1] = text[: site.column] + site.replacement + text[end:]
    return "".join(lines)


def _compiles_as_python(source: str) -> bool:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the original's own warnings, such as invalid escapes
        try:
            compile(source, "<mutant>", "exec")
        except (SyntaxError, ValueError):
            return False
    return True


@dataclass(frozen=True, slots=True)
class Language:
    sites: Callable[[str], Iterator[Site]]
    compiles: Callable[[str], bool]  # checked where it can be, before the container


PYTHON = Language(python_sites, _compiles_as_python)
GO = Language(go_sites, lambda _source: True)  # built by `go build` in the container


def mutants(
    repository: Path,
    project: str,
    sha: str,
    is_source: Callable[[str], bool],
    language: Language,
    count: int = MUTANTS_PER_COMMIT,
) -> list[Mutant]:
    """Up to `count` mutants of the lines `sha` changed, drawn with a seed of project and commit."""
    diff = _git(repository, "diff", "-U0", "--no-color", "--no-renames", f"{sha}^1", sha)
    candidates: list[tuple[str, Site]] = []
    sources: dict[str, str] = {}
    for path, lines in sorted(added_lines(diff).items()):
        if not is_source(path):
            continue
        try:
            # Bytes, decoded without newline translation, so a mutant changes only its token.
            sources[path] = subprocess.run(
                ["git", "-C", str(repository), "show", f"{sha}:{path}"],
                capture_output=True,
                check=True,
            ).stdout.decode("utf-8")
        except UnicodeDecodeError:
            continue
        candidates.extend(
            (path, site) for site in language.sites(sources[path]) if site.line in lines
        )
    seed = hashlib.sha256(f"{project}\0{sha}".encode()).digest()
    generator = random.Random(seed)
    generator.shuffle(candidates)
    chosen: list[Mutant] = []
    for path, site in candidates:
        if len(chosen) == count:
            break
        content = apply(sources[path], site)
        if language.compiles(content):
            chosen.append(
                Mutant(path, site.line, site.column, site.original, site.replacement, content)
            )
    return chosen


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
