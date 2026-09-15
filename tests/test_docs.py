"""The documentation site's navigation points at pages that exist (docs/adr/0019).

Mintlify builds the site elsewhere, so a navigation entry pointing at nothing is found by a reader
before it is found by us. It costs nothing to check here instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs.json"


def pages(navigation: dict[str, object]) -> list[str]:
    """Every page path in the navigation, however deeply the groups are nested."""
    found: list[str] = []
    stack: list[object] = [navigation]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            found.append(node)
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            stack.extend(node.get("pages", []))
            stack.extend(node.get("groups", []))
    return found


def test_every_page_of_the_navigation_exists() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    listed = pages(config["navigation"])

    assert listed, "the navigation lists no page"
    missing = [
        page for page in listed if not any((ROOT / f"{page}{e}").is_file() for e in (".mdx", ".md"))
    ]
    assert not missing, f"the navigation points at pages that do not exist: {missing}"


def test_the_site_carries_no_em_dash() -> None:
    """A house rule, and one a reader notices before any of the content."""
    guilty = [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.joinpath("docs").rglob("*.mdx")
        if "—" in path.read_text(encoding="utf-8")
    ]

    assert not guilty, f"em dashes in: {guilty}"


def test_the_site_quotes_no_measured_figure() -> None:
    """The site links to a measurement, it never repeats one (docs/adr/0019).

    The check is narrow on purpose: a percentage or a score written with a decimal is what an
    accuracy figure looks like, and it is the shape that went stale six times in the audit of
    2026-09-15. Whole numbers are left alone, since they are usually counts in an example.
    """
    figure = re.compile(r"\d+[.,]\d+\s*%|\b0[.,]\d{3}\b")
    guilty = []
    for path in sorted(ROOT.joinpath("docs").rglob("*.mdx")):
        text = path.read_text(encoding="utf-8")
        # Fenced blocks are a command's own output, which a reader reproduces rather than trusts.
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        found = figure.findall(prose)
        if found:
            guilty.append(f"{path.relative_to(ROOT).as_posix()}: {found}")

    assert not guilty, "measured figures belong in benchmarks/results, linked to: " + "; ".join(
        guilty
    )
