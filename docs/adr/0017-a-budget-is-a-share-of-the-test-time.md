# 17. A budget is a share of the test time, not a count of tests

Date: 2026-09-14
Status: accepted

## Context

`testhunch select --budget 25%` runs the top quarter of the known tests and leaves out the rest
(ADR 0007). Counting tests was the only thing the ranking of 0.2.0 could be cut by: it did not know
how long a test takes.

The ranking kept by the study does (ADR 0014, 0015). It divides a test's score by its usual
duration, so the tests it puts first are, deliberately, the quick ones. A budget counted in tests
then measures the wrong thing twice over:

- **It does not control what CI pays.** A quarter of the tests, chosen because they are quick, is
  far less than a quarter of the test time. The user asks for a quarter and gets something else.
- **The gain measured is a gain in time.** On the held-out projects, the kept version needs 58% of
  the test time to turn 90% of failing builds red, against 66% for the latest failure and 70% for
  0.2.0 (benchmarks/results/study/held-out.md). The count-based measures moved much less. A product
  cut by count spends its gain where it was never measured.

The study measures both, and its two numbers are not comparable: `tests_0.25` gives the unknown
tests for free, while `time_0.25` counts the whole job's time from the first test. The product has
to choose what its own budget means, and say it plainly.

## Decision

**A budget is a share of the expected test time of the tests testhunch knows.** `--budget 25%`
keeps the longest prefix of the ranking whose expected durations add up to at most a quarter of
the expected duration of every known test. Tests testhunch has never seen still always run, on top
of the budget, as they do today (ADR 0006, 0007): their duration cannot be expected, because
nothing has measured it. The documentation says so where it says what a budget is.

**A prefix, never a better-packed set.** A knapsack would fit more tests into the same time by
skipping a slow one and taking two quick ones below it. It would also run a test the ranking placed
lower before one it placed higher, which is the one thing the ranking promises not to do. The cut
follows the order.

**At least one known test always runs**, as with the count budget: a budget above 0% that is
smaller than the first test's duration still runs that test, rather than nothing.

**The expected duration is the ranking's own.** `rank` already computes, per test, the mean
duration over the builds it ran in, the median of the others when it has none, plus the 1 ms of
ADR 0014. It now returns that number on each `RankedTest`, and the cut spends exactly it. A test
cannot be ranked by one duration and paid for by another.

**Shadow mode cuts by the durations recorded with the ranking**, not by the durations of the run it
is judging. A ranking recorded before a build could not know how long that build's tests would take;
cutting with them afterwards would report a budget nobody could have spent. Migration 0006 adds
`expected_ms` to `prediction_positions` in both databases.

**`--budget-unit tests` keeps the old meaning**, for a suite whose runner reports no usable
duration. Every duration equal makes a time budget behave as a count budget anyway, so this is for
saying it on purpose, not for rescuing a degenerate case.

## Consequences

- The same `--budget 25%` now leaves out more tests than before, and saves about a quarter of the
  test time instead of an unmeasured amount. This is a behaviour change in a pre-alpha, written in
  the README next to the option.
- The shadow report's budgets become time budgets. The counts it already prints, tests run and time
  run, keep showing both sides, so a reader still sees what a budget costs in each unit.
- Rankings recorded before migration 0006 have no expected duration. Shadow mode leaves those runs
  out of its time budgets rather than guessing a duration for them, and says how many it left out.
- The published Phase 3 numbers were measured with count budgets and stay as they are, labelled.
  Re-measuring them with time budgets is one held-out look (ADR 0016), to be spent once, after this.
- Go's `%.2fs` durations are almost all 0 (benchmarks/results/README.md). With the 1 ms epsilon
  every test then costs the same and the time budget degrades into a count budget, which is the
  right behaviour rather than a failure.
