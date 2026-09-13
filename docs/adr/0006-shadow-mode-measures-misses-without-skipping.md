# 6. Shadow mode measures misses without skipping anything

Date: 2026-09-13
Status: accepted

## Context

testhunch will only be trusted to skip tests once it is known how often skipping would have hidden
a failure. That number has to come from real builds, and it must not flatter the ranking: a
ranking that has already seen a run's results "predicts" that run perfectly.

A selection also needs a budget (how many tests to run), and picking one before there is any data
would be a guess.

## Decision

**Record rankings, not selections.** `testhunch prioritize --record` stores, for the tested commit,
the position of every test in the ranking. The budget is applied afterwards: the shadow report
evaluates several budgets over the same recorded rankings (the top 10%, 25% and 50% of ranked
tests).

**A ranking is only compared with runs it could not have seen.** Each recorded ranking keeps the
id of the newest run in the history it was computed from. A run is evaluated against the latest
ranking recorded for its commit whose newest run is older than the run itself. A ranking computed
after the results were ingested is never used for that run. Rankings computed from an empty
history are not recorded: there is nothing to evaluate.

**What counts:**

- A test is selected when its position is within the budget, or when the ranking does not know it
  (no history yet): an unknown test would always run.
- A failure to catch is a failed or errored result that is not flaky within its run (ADR 0005).
  Skipped results are ignored.
- A failing run is *caught* when at least one of its failures was selected: the build would still
  have gone red. This is the number a CI user cares about. The share of individual failures
  selected is reported too.
- The share of tests run, and the share of test time, among the run's executed results. Time only
  counts results with a known duration.

Every rate is shown with its counts ("caught 7 of 9 failing runs"), and with no failing run the
report says there is nothing to measure yet instead of showing 100%.

## Consequences

- One recorded ranking holds a row per known test, so storage grows with tests times recorded
  builds. Acceptable until the hosted service (phase 4) needs retention or partitioning.
- Each job of a test matrix is its own run and is evaluated separately against the same ranking.
- The report measures the ranking as it was used. It is evidence for this repository's history,
  not a general accuracy claim: that is what the public benchmark (phase 3) is for.
