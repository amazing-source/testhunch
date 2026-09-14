"""Which benchmark projects tune the ranking and which only measure it (docs/adr/0013).

Every choice of the ranking study is measured on the development projects. Held-out projects are
replayed only for versions frozen before the replay, so that their numbers were not tuned on.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

# Failing jobs evaluated per project in the Phase 3 results of testhunch 0.2.0
# (benchmarks/results/rtptorrent at commit 9cfc129): the size the split is balanced on.
RTPTORRENT_FAILING_JOBS = {
    "dynjs@dynjs": 55,
    "jsprit@jsprit": 59,
    "doanduyhai@Achilles": 68,
    "adamfisk@LittleProxy": 77,
    "brettwooldridge@HikariCP": 94,
    "neuland@jade4j": 96,
    "julianhyde@optiq": 130,
    "Graylog2@graylog2-server": 190,
    "DSpace@DSpace": 217,
    "thinkaurelius@titan": 280,
    "eclipse@jetty.project": 316,
    "l0rdn1kk0n@wicket-bootstrap": 414,
    "jcabi@jcabi-github": 429,
    "facebook@buck": 477,
    "jOOQ@jOOQ": 534,
    "CloudifySource@cloudify": 563,
    "deeplearning4j@deeplearning4j": 585,
    "apache@sling": 846,
    "square@okhttp": 1946,
    "SonarSource@sonarqube": 3131,
}


def split(failing_jobs: Mapping[str, int]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The development and the held-out projects, balanced on failing jobs.

    Projects sorted by failing jobs are paired in that order, and in each pair the project whose
    name has the smaller SHA-256 digest is held out. No seed to choose: anyone gets the same split.
    A project left without a pair is a development project.
    """
    ordered = sorted(failing_jobs, key=lambda project: (failing_jobs[project], project))
    development: list[str] = []
    held_out: list[str] = []
    for index in range(0, len(ordered) - 1, 2):
        first, second = sorted(ordered[index : index + 2], key=_digest)
        held_out.append(first)
        development.append(second)
    if len(ordered) % 2:
        development.append(ordered[-1])
    return tuple(sorted(development, key=str.lower)), tuple(sorted(held_out, key=str.lower))


def _digest(project: str) -> str:
    return hashlib.sha256(project.encode("utf-8")).hexdigest()


RTPTORRENT_DEVELOPMENT, RTPTORRENT_HELD_OUT = split(RTPTORRENT_FAILING_JOBS)

# The learned model (ROADMAP phase 6) needs somewhere to compare its own variants that is not the
# held-out projects, or every comparison would be a look at them (docs/adr/0016). The same rule,
# applied once more to the development projects: it trains on one half and chooses on the other.
RTPTORRENT_TRAINING, RTPTORRENT_VALIDATION = split(
    {project: RTPTORRENT_FAILING_JOBS[project] for project in RTPTORRENT_DEVELOPMENT}
)

# Each held-out project is the first of GitHub's most-starred projects of its runner's language
# to meet ADR 0011's reasons, in the order docs/adr/0013 records.
HARNESS_DEVELOPMENT = ("pallets/click", "spf13/cobra")
HARNESS_HELD_OUT = ("fastapi/fastapi", "ollama/ollama")
