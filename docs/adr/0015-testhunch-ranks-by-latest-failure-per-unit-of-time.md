# 15. testhunch ranks by the latest failure per unit of time

Date: 2026-09-14
Status: accepted

## Context

The ranking study (ADR 0014) kept `latest-failure+time^1.0+test_file_changed*0.5`, and on the
held-out projects it beat both the latest failure and testhunch 0.2.0 (benchmarks/results/study).
The roadmap now makes it testhunch's ranking. Three things stand between the study's engine and
the product:

- **History.** 0.2.0 reads its history from the 50 most recent runs, counting failures and runs.
  The kept version needs, over every earlier build: when each test last failed, RTPTorrent's
  failure priority, and its mean duration per build. Recomputing those from every stored result
  at each call grows with the whole history: SonarQube has 53 307 runs of about a thousand classes
  each.
- **Exactness.** ADR 0014 requires the product replay to give the engine's numbers. The engine
  computes the priority in floating point, `α + (1 − α) P`, and a build's duration as the mean of
  its jobs rounded by Python, half to even. SQL's `ROUND` rounds half away from zero in both
  databases.
- **Builds.** The engine counts builds, groups of jobs that may have run at the same time. The
  store only knows runs and their commit.

## Decision

**A test's score is the study's final version.** For a test that has passed or failed before, over
every earlier build: RTPTorrent's priority of its failures (α = 0.8, ADR 0014), plus 0.5 when the
change touches the test's own file, divided by its mean duration per build plus 1 ms. Higher scores
run first. Ties go to the shorter test, then the newer failure, then the higher priority, then the
SHA-256 of a seed and the test's key. The CLI seeds with the commit being ranked, and the replay
with the job, as the engine does. A test with no known duration gets the median of the others. Every
ranked test keeps its reasons: when it last failed, its usual duration, whether its file changed.
Tests that never passed or failed are not ranked and always run (ADR 0006, 0007).

**A build is every run of one commit**, numbered per repository in the order of its first run.
Several jobs of a commit form one build, whenever each of them arrives. In the replay, the store
sees each group of concurrent jobs as a commit of its own, so that its builds are the engine's.

**The store keeps each test's history in builds up to date at ingest**, in three new tables:
`builds`; `build_tests`, a test's outcome and durations in one build; and `test_history`, its
aggregates over builds. The arithmetic runs in Python, the engine's own, so results are identical
in SQLite and Postgres, and reading the history costs one row per known test. A run that arrives
after later builds of other commits updates the priority exactly: the priority at a test's last
failure is the sum of α (1 − α)^(last − b) over the builds b it failed in. Migration 0005 creates
the tables in both databases and rebuilds them from the runs already stored.

**The history has no window.** The `--last` option keeps its meaning for the reports; ranking and
selection read every build.

**The product replay filters the history to each job's tests** before ranking, as the engine ranks
a job's own tests, so that the median duration of a test with none known is taken over the same
tests. A test checks, job by job, that the product replay orders the RTPTorrent extract and a
synthetic history as the engine's final version does. Replaying every study project with the product
and comparing its numbers with the published ones is the next step.

**0.2.0's ranking stays in the benchmarks**, as a frozen copy in `benchmarks/study`, so the study
still reproduces; a test holds it to the orders 0.2.0 gave the RTPTorrent extract, recorded before
this change.

## Consequences

- Selection still leaves out a share of the known tests (ADR 0007). The kept version gains in time,
  not in count, so a time budget for `select`, the shadow mode and the Action comes next, with its
  own decision.
- Ingest does more work per run: a read and an upsert per test for the build and the aggregates.
- Deleting runs, which nothing does yet, would require rebuilding the aggregates; the rebuild that
  migration 0005 runs can be reused.
- A test's file is the latest one reported for it, as before. The engine takes it from the builds a
  test ran in; they differ only for a test first reported as skipped with a file and later run
  without one.
- The Phase 3 results keep the version they were measured with, 0.2.0.
