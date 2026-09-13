# 4. Flaky means: same commit, different outcome

Date: 2026-09-13
Status: accepted

## Context

A model that learns "this change breaks this test" is poisoned by flaky tests: their failures say
nothing about the change. So testhunch needs a definition of flaky that it can defend before it
uses one.

Common heuristics include "failed then passed on retry", "changes state often", or a statistical
flip rate across commits. Flip rates across commits confuse flakiness with real regressions and
fixes, which also flip state.

## Decision

A test is flaky on a commit when, for that exact commit, it has at least one passing result and at
least one failed or errored result. Different commits never count, because the code differs.

Within a single run, duplicate reports of one test are collapsed to the worst status. They are not
counted as flakiness yet: a test can appear twice for reasons other than a retry, and each runner's
retry format has to be verified from a real report first (see the roadmap).

## Consequences

- No false positives from regressions: a test that passes on one commit and fails on the next is
  reported as failing, not flaky.
- Flakiness is only visible where a commit was run more than once (re-runs, merge queues,
  scheduled builds). Projects that never re-run a commit will see few flaky tests until in-run
  retries are supported.
