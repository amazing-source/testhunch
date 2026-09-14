# 11. The harness replays real projects commit by commit in pinned containers

Date: 2026-09-14
Status: accepted

## Context

The RTPTorrent benchmark (ADR 0010) has class-level results of Java projects from Travis CI build
logs. It cannot say how testhunch does on what it is built for: method-level JUnit reports from
the runners it supports (pytest, go test, Surefire, nextest, Vitest, Jest), keys as those runners
write them, and changed files as `git diff` lists them.

That needs test suites actually run, at many past commits, with results that do not depend on the
day they were run. Running a project's history is fragile: a dependency that was resolvable then
may not be now, and a test can depend on the machine. Measured while choosing projects, on the
newest commit of pallets/click in a Python image without `less`, 24 pager tests fail that pass in
the project's CI, and on spf13/cobra `TestFailGenFishCompletionFile` fails when run as root, since
root can write to a read-only file.

## Decision

**Projects are chosen before any result is seen**, for these reasons only: a permissive licence, a
runner testhunch supports, a suite that runs in under a minute, and a lockfile so that each
commit's dependencies resolve to the versions it was tested with. The first two, in two
languages:

| Project | Runner | Window ends at | Licence |
|---|---|---|---|
| pallets/click | pytest | `6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1` (2026-09-05) | BSD-3-Clause |
| spf13/cobra | go test, JUnit by gotestsum | `adbc8813901bba65827259daa8e22ff94ec1f30e` (2026-07-10) | Apache-2.0 |

**The window is the 200 most recent first-parent commits of the default branch**, up to and
including the pinned end commit. A first-parent commit is what landed on the branch, a pull
request merge or a direct push, and its change is its diff with its first parent, read with
`testhunch.gitinfo.changed_files` exactly as the CLI reads it.

**Each project runs in its own image**, built from a base image pinned by digest, with what the
project's CI provides and the harness does not otherwise have (`less` for click), and a non-root
user. The Dockerfiles are in `benchmarks/harness/images`; the ID of the image actually used is
recorded with the results, since system packages are resolved when the image is built.

**Each commit runs its whole suite**, in a fresh container, from `git archive` of the commit: first
the project's setup (installing its locked dependencies), then its tests, writing a JUnit report.
When the suite fails it runs a second time, and both reports are the run's attempts, so that a
failure that passes on the retry counts as flaky and one that fails again as confirmed (ADR 0005,
0008). Dependency downloads are cached in a Docker volume per project; the lockfile decides the
versions, the cache only saves time. Test result caches are not used: Go's is turned off with
`-count=1`, since a cached result is not a run of the commit's tests. A commit whose setup fails,
or whose tests write no report, is recorded as not built and counted, never dropped. Runs are
kept on disk so that collection can stop and resume.

**A setup failure is not taken at its word.** During the first full collection of cobra, a DNS
outage inside Docker failed 31 commits in a row in under a second each (`lookup proxy.golang.org
... no such host`), then the network came back: recorded as they were, they would have been
published as commits of cobra that do not build. A failing setup is therefore tried again after
30 seconds, and collection stops after 3 commits in a row are not built, so that someone reads
their logs before they count; `--allow-not-built` goes on when the project itself is at fault.

**Evaluation replays the commits in order**, with the same code and metrics as the RTPTorrent
replay: each commit is ranked from the history of the commits before it and its own changed
files, then its results are recorded. The metrics are those of ADR 0006 at budgets of 10%, 25%
and 50%.

## Consequences

- On a default branch most commits pass, so the real history of these projects has few failures to
  catch. The harness still measures the share of tests and of test time each budget runs, and
  produces the history that seeded faults (mutation testing, next on the roadmap) are ranked from.
- A 200-commit window with suites under a minute takes hours per project, which is why collection
  is resumable and kept out of CI.
- Two projects are a start, not a sample of all projects: more runners (Surefire, nextest, Vitest)
  come as projects are added, with their numbers published whatever they are.
