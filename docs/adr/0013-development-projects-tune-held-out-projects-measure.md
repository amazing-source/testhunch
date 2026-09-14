# 13. Development projects tune the ranking, held-out projects measure it

Date: 2026-09-14
Status: accepted

## Context

The roadmap studies simple rankings before anything else (ROADMAP.md, phase 4): from the tests
that failed most recently, each addition (test duration, failure rate, verdict changes, file × test history, names
and diffs) is kept only if it measures better. Every addition kept, every weight and every window
tried fits the ranking a little more to the projects it is measured on. Published on those same
projects, the numbers would overstate what users get on theirs.

Some things were seen before any split and cannot be unseen:

- the Phase 3 results of testhunch 0.2.0 on all 20 RTPTorrent projects and on click and cobra
  (benchmarks/results);
- the ideas the study tests, which come from those results (SonarQube's many jobs per build
  leaving many classes unknown) and from papers (Cheng et al., ISSTA 2024; Yaraghi et al., TSE
  2023; Machalica et al., ICSE-SEIP 2019).

## Decision

**RTPTorrent's 20 projects are split into 10 development and 10 held-out projects**, balanced on
size, by a rule fixed before it was computed:

1. sort the projects by their failing jobs evaluated in the Phase 3 results;
2. pair them in that order, the 1st with the 2nd, the 3rd with the 4th, and so on;
3. in each pair, hold out the project whose name (`owner@repository` in UTF-8) has the smaller
   SHA-256 digest, compared as hexadecimal text.

There is no seed to choose, and anyone gets the same split (`benchmarks/split.py`). Pairing
neighbours in size gives each side one project of every size: 4 545 failing jobs on the
development side, 5 962 on the held-out side, most of them SonarQube's.

| Failing jobs | Development | Held out |
|---|---|---|
| 55 and 59 | dynjs@dynjs | jsprit@jsprit |
| 68 and 77 | doanduyhai@Achilles | adamfisk@LittleProxy |
| 94 and 96 | brettwooldridge@HikariCP | neuland@jade4j |
| 130 and 190 | Graylog2@graylog2-server | julianhyde@optiq |
| 217 and 280 | thinkaurelius@titan | DSpace@DSpace |
| 316 and 414 | eclipse@jetty.project | l0rdn1kk0n@wicket-bootstrap |
| 429 and 477 | facebook@buck | jcabi@jcabi-github |
| 534 and 563 | jOOQ@jOOQ | CloudifySource@cloudify |
| 585 and 846 | deeplearning4j@deeplearning4j | apache@sling |
| 1 946 and 3 131 | square@okhttp | SonarSource@sonarqube |

**click and cobra are development projects**: every harness result so far was measured on them.

**The harness's held-out projects are fastapi/fastapi (pytest) and ollama/ollama (go test)**, one
for each runner of the development projects. So that they are not picked by taste, each is the
first project of GitHub's most-starred projects of its language (the searches `language:Python`
and `language:Go` sorted by stars, read on 2026-09-14) to meet ADR 0011's reasons, checked in this
order:

1. a permissive licence (MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0 or ISC), not archived, not a
   fork;
2. its lockfile at the root of each of the 200 most recent first-parent commits: `uv.lock`, with
   pytest in `pyproject.toml`, for Python; `go.mod` for Go;
3. its whole suite passes at the newest commit, in a harness image with what GitHub's runners
   provide, in under a minute once caches are warm, as they are in a collection after its first
   commit (the cache volume of ADR 0011).

Every project that passed the first two checks, in star order, until one also passed the third:

| Language | Project | Stars | Outcome |
|---|---|---:|---|
| Python | NousResearch/hermes-agent | 245 300 | Out: its CI splits the tests into 6 jobs of about 4 minutes each (not run here) |
| Python | TheAlgorithms/Python | 224 557 | Out, see below |
| Python | langflow-ai/langflow | 154 775 | Out: its CI splits the unit tests into 5 jobs of 17 to 24 minutes each (not run here) |
| Python | harry0703/MoneyPrinterTurbo | 123 429 | Out: 330 seconds |
| Python | Graphify-Labs/graphify | 116 563 | Out: 423 seconds and 11 failures, once a C compiler was added to install it |
| Python | **fastapi/fastapi** | 102 323 | **Held out**: 3 348 tests pass in 34 seconds at `50113da` |
| Go | avelino/awesome-go | 184 084 | Out: still running after 25 minutes, stopped |
| Go | **ollama/ollama** | 180 866 | **Held out**: 7 931 tests, 305 of them skipped, pass in 23 seconds warm (over 100 cold) at `53fed26` |

TheAlgorithms/Python is the one project left out for a reason ADR 0011 does not give. Only 22 of
its 1 507 Python files are test files; its other tests are doctests inside the algorithm files
(`--doctest-modules`), so the tests of a change sit in the changed file, found by name without
predicting anything. Kept, it would have made name matching look better than it is.

fastapi runs the commit's own `scripts/test.sh` (pytest-xdist); its image adds `git`, which one
test calls. ollama uses the same toolchain as cobra. Both windows were read for what the setup
needs: fastapi's `tests` group and `all` extra, and ollama's `go 1.26.0`, are in all 200 commits.
Collecting a held-out project ranks nothing, so it needs no flag.

**Every choice of the study is made on development projects.** Held-out projects are replayed
only for versions that are committed and listed before the replay, and the held-out numbers of
every listed version are published, better or worse. A version changed after its held-out numbers
were seen is a new version: both are published.

**The benchmark commands refuse held-out projects unless `--held-out` is given**, so that a routine
run over every project does not show them by accident.

**The RTPTorrent test extract stays.** Its 80 jobs of LittleProxy, now held out, test how the
dataset is read and replayed, never which ranking does better.

## Consequences

- Choices rest on 10 RTPTorrent projects instead of 20, and published medians cover 10 projects.
- Counting history in builds rather than runs was proposed because of SonarQube, which is held out.
  Like any other change, it is kept only if it does better on the development projects.
- SonarQube's replay, 53 minutes long, leaves the loop of trying changes.
- The held-out projects are not untouched: the numbers of 0.2.0 on them are published. What the
  split still prevents is fitting the study's choices to them.
- The Phase 3 results stay published as they are, on all 20 projects.
