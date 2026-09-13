# 5. Retries within a run are flakiness evidence

Date: 2026-09-13
Status: accepted (amends [0004](0004-flaky-means-same-commit-different-outcome.md)), amended by [0008](0008-failures-are-confirmed-by-retries.md)

## Context

ADR 0004 counted flakiness only across runs of the same commit, and left retries within a run
out until each runner's retry format had been verified from a real report. Those reports now
exist in `tests/fixtures/junit`:

- Maven Surefire (`rerunFailingTestsCount`) and cargo-nextest (`retries`) keep every attempt
  inside one `<testcase>`. A test that failed and then passed has only `<flakyFailure>` or
  `<flakyError>` children, and no `<failure>` or `<error>`. A test that failed every attempt has
  `<failure>` or `<error>` followed by one `<rerunFailure>` or `<rerunError>` per rerun.
- gotestsum (`--rerun-fails`) repeats the `<testcase>`, with nothing that tells a rerun apart
  from any other repetition.
- pytest reports a passing test whose fixture teardown fails as a single `<testcase>`, so that
  common case does not produce a pass and a failure for one test.

## Decision

A result is flaky when the test both failed and passed within one run:

1. Its `<testcase>` has a `<flakyFailure>` or `<flakyError>` child and no `<failure>` or
   `<error>`. Its status stays passed: that is the runner's own verdict.
2. Or the run holds several entries for the test, with at least one pass and at least one failure
   or error. Its status stays the worst entry's, as before. Without a retry marker a repetition
   is not necessarily a retry (two jobs of a test matrix ingested together also repeat a test),
   and hiding a real failure is worse than reporting a flaky test as failing.

`<rerunFailure>` and `<rerunError>` are not flakiness: every attempt failed.

A test is flaky on a commit when it has a flaky result on that commit, or both passing and failing
results on that commit (ADR 0004).

## Consequences

- Projects that retry failing tests within a run see their flaky tests without re-running whole
  commits.
- A test that flaked under gotestsum counts as failing as well as flaky; under Surefire and
  nextest it counts as passed and flaky. The flaky report is the same for every runner, the
  failing report is not.
- As in ADR 0004, the environment is not part of a test's identity: a test that passes on one
  platform of a matrix and fails on another, for the same commit, is reported as flaky.
- `results` gains a `flaky` column (migration 0002, for both databases). Results recorded before
  it are not flaky.
