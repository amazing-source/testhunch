"""The README's headline table is the study's, to the last digit.

Every defect the 2026-09-15 audit found had one shape: a figure written by hand beside a figure
produced by a command, left behind when the command ran again. The README is where that costs most,
because it is the page people read before deciding whether to believe anything else. So the numbers
it quotes are checked against the pages `python -m benchmarks.study` writes.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELD_OUT = ROOT / "benchmarks" / "results" / "study" / "held-out.md"
CURRENT = "latest-failure+time^1.0+test_file_changed*0.5"
BASELINE = "latest-failure"
RELEASE_020 = "testhunch-0.2.0"
HINDSIGHT = "*best order in hindsight*"


def primary() -> dict[str, float]:
    """The APFDc of each ranking, from the verdict table at the top of the page."""
    rows = re.findall(
        r"^\| (\S+) \| (?:current|candidate|reference) \| (\d\.\d{3}) \|",
        HELD_OUT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return {name: float(value) for name, value in rows}


def time_to_catch_90() -> dict[str, Decimal]:
    """The share of test time that turns 90% of failing jobs red, per ranking.

    Cut at the next heading: the page holds other two-column tables below this one, and reading
    past it silently returned the harness figures instead.
    """
    text = HELD_OUT.read_text(encoding="utf-8")
    section = text.split("## Share of the test time needed to turn failing jobs red")[1]
    section = section.split("\n## ")[0]
    rows = re.findall(r"^\| ([^|]+?) \| (\d\.\d{3}) \| \d\.\d{3} \|$", section, re.MULTILINE)
    # Decimal, not float: 0.575 * 100 is 57.4999... in binary, which rounds to 57 where the page
    # and the README both read 58. The rounding has to be the one a person would do by hand.
    return {name.strip(): Decimal(value) for name, value in rows}


def test_the_readme_quotes_the_study_it_links_to() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    apfdc, caught = primary(), time_to_catch_90()

    assert {CURRENT, BASELINE, RELEASE_020} <= set(apfdc), f"page changed shape: {sorted(apfdc)}"
    assert HINDSIGHT in caught, f"page changed shape: {sorted(caught)}"

    for ranking in (CURRENT, BASELINE, RELEASE_020):
        written = f"{apfdc[ranking]:.3f}".replace(".", ",")
        assert written in readme, f"README does not quote the APFDc of {ranking}, {written}"

    for ranking in (CURRENT, BASELINE, RELEASE_020, HINDSIGHT):
        percent = (caught[ranking] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        written = f"{percent} %"
        assert written in readme, f"README does not quote the 90% time of {ranking}, {written}"


def first_failure_positions() -> dict[str, dict[str, str]]:
    """Where the first failing test sits, per slice and per ranking, as written on the page."""
    text = (ROOT / "benchmarks" / "results" / "study" / "first-failures.md").read_text(
        encoding="utf-8"
    )
    slices: dict[str, dict[str, str]] = {}
    for heading, body in re.findall(
        r"^## Jobs whose failing tests (had (?:never )?failed before).*?$(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        rows = re.findall(r"^\| (\S+) \| (\d\.\d{3}) \|", body, re.MULTILINE)
        slices[heading] = {name: value for name, value in rows}
    return slices


def test_the_readme_quotes_the_blind_spot_it_publishes() -> None:
    """The caveat is the most load-bearing claim on the page, so the one most worth holding."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    slices = first_failure_positions()

    assert set(slices) == {"had failed before", "had never failed before"}, sorted(slices)

    for slice_name, rankings in slices.items():
        for ranking in ("testhunch", "random"):
            written = rankings[ranking].replace(".", ",")
            assert written in readme, (
                f"README does not quote {ranking} on '{slice_name}', {written}"
            )


def test_the_readme_quotes_the_measured_gap_over_the_baseline() -> None:
    """+0.028 is a difference, so it goes stale on its own even when both figures are right."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    apfdc = primary()

    gap = f"{apfdc[CURRENT] - apfdc[BASELINE]:+.3f}".replace(".", ",")

    assert gap in readme, f"README does not quote the measured gap, {gap}"
