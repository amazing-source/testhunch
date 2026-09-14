# 13. Development projects tune the ranking, held-out projects measure it

Date: 2026-09-14
Status: accepted

## Context

Phase 5 starts with a study of simple rankings (ROADMAP.md): from the tests that failed most
recently, each addition (test duration, failure rate, verdict changes, file × test history, names
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
The harness's held-out projects are new ones, one for each runner of the development projects
(pytest and go test), chosen for ADR 0011's reasons only and pinned in this ADR before the study
measures anything.

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
