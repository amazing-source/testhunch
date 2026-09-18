# 0037: a measured failure rate in place of the priority

Date: 2026-09-18

## Status

Accepted. Follows [ADR 0036](0036-a-narrower-tie-break-is-judged-before-it-runs.md), which named the
question. This record was committed before either candidate below was replayed; what they measured
is added afterwards, under "What it found", and nothing above that heading changes once they have
run.

## Context

ADR 0036 showed that the tie-break is the smaller part of the first-failure defect: most of the
distance to random remains under any tie-break and comes from what runs before the zero-score
tests. It named a hypothesis, that a nearly spent failure priority carries no information. Three
checks were made before writing any candidate, and the first two could have ended this step.

**A probability over a cost has been tried, as a learned model.** The shipped score is a
probability divided by a cost, the order that reaches a failure soonest when the probabilities are
right (Smith's rule for the expected time to a first success), with RTPTorrent's priority standing
in for the probability. Phase 6's `learned+time^1.0` put a learned probability there. It tied the
heuristic on the primary measure, reached only 0.610 of position on first failures against 0.740,
and fell to 0.560 on the jobs that had failed before, against 0.127
([results](../../benchmarks/results/study/learned.md)). So a probability over a cost is not enough
by itself. What differs here is where the probability comes from: that model was fitted on the
training projects and applied to others; the rate below is counted in each project, from its own
past builds.

**testhunch 0.2.0 forgets failures.** It ranks from a window of 50 runs, so a test whose last
failure is older scores like one that never failed. ADR 0035's `window=50` was a different thing,
tests that had not *run* for 50 builds, so forgetting old failures has never been measured on the
shipped ranking, and it may be what ADR 0035 left unexplained between 0.468 and 0.399.

**Measured, an old failure predicts more in some projects and less in others.**
`python -m benchmarks.hazard training`, committed with this record, counts on the training half how
often a test fails in a build, by its state before it: the age of its last failure in builds, or
never failed and for how long it has run. Failures per thousand runs:

- A test that never failed fails 0.67 to 37 times per thousand runs. The shipped score gives it a
  priority of exactly zero, so it runs after every test that ever failed, whatever the costs.
- A failure 16 builds old or more predicts no more than never failing on HikariCP, and less on
  dynjs, 0.45 against 37 at 64 to 127 builds. On jetty and jOOQ, a failure 64 to 127 builds old
  still predicts about four times the base rate. A fixed window like 0.2.0's would be right for
  some projects and wrong for others.
- A test that never failed but has run in only one to three builds fails 4.6 to 286 times per
  thousand runs where it was seen, against about one for a test that ran in 256 builds. Test age is
  a signal the study never tried.
- On the first-failure jobs whose failing test scored zero, the time spent before it goes mostly to
  tests whose last failure is old on HikariCP (0.69 of the job), dynjs (0.55) and jOOQ (0.31), and
  to cheaper zero-score tests on jetty (0.29). These are 5 to 30 jobs a project.

## Decision

### The candidates, closed

Both are `Calibrated` in `benchmarks/study/rankings.py`. A test's probability is the share of runs
that failed, without being flaky, among the runs of tests in the same state, in this project, over
the builds before this one; the order is that probability over the expected duration, and ties go
as in the shipped ranking. A state is drawn toward the project's rate over every state by one run's
worth, so a state not seen yet starts at that rate rather than at nothing. The states are the age of
the last failure in doubling spans of builds, and never failed.

1. **`calibrated`**: never failed is one state.
2. **`calibrated+runs`**: never failed is split by how many builds the test ran in, doubling
   spans. It adds test age and nothing else.

Neither uses the changed-file signal. Folding it into a probability needs a choice of its own, and
two changes at once would not say which one worked. Each candidate is therefore read against what
testhunch ships, which decides, and against `latest-failure+time^1.0`, the shipped ranking without
that signal, which isolates the calibration.

Not kept: a window on the age of failures, as 0.2.0 has. It needs a size, and the measurement
above says the right size differs by project, while the calibration needs none.

### Predictions, written before the replay

1. Both candidates turn red sooner on first failures than `latest-failure+time^1.0` on the training
   half: old failures that predict little stop running before tests that never failed.
2. On the jobs that had failed before, they place the failing test later in the order by more
   than they delay it in time, since the probability over the cost trades one for the other, as the
   learned model did.
3. `calibrated+runs` does at least as well as `calibrated` on first failures.

### The rule

Judged on the **validation half**, each candidate against the shipped ranking on the same failing
jobs, as a mean of per-project means:

1. The primary measure drops by at most **0.003**, as in ADR 0036.
2. On first failures, **red at** improves by at least **half the distance between the shipped
   ranking and random** on the same half. The target is time, not position, for a reason ADR 0036
   measured: among tests the history says nothing about, the two disagree by nature, random beats
   the shipped order in both, and time is what a user with a budget pays.
3. On first failures, the **position** does not get worse by **0.005** or more, so that time is not
   bought with position.
4. On the jobs that had failed before, the APFDc does not drop by **0.005** or more.

A candidate that meets all four on the validation half earns **`NEEDS_HELD_OUT_CONFIRMATION`**,
the one with the higher primary measure if both do; otherwise the result is **`DO_NOT_SHIP`**.
Development data cannot ship a ranking in this project. The training half is reported under the
same rule and does not decide. ADR 0018's guardrail, the position against random with its
interval, is reported and does not decide either. The rule is code, `criteria` and `verdict` in
`benchmarks/calibration.py`, tested, and committed with this record.

## What this decision was made knowing

The training half was read for the hazard counts and the time decomposition above, and the
candidates were chosen from them. The validation half has been read before, in ADR 0036, for the
shipped ranking, random, 0.2.0 and global hash on first failures, so the distance the second
condition is measured against is known: 0.496 against 0.425 in red at. Neither candidate has been
measured on either half, and LRTS and the held-out projects are not touched.

RTPTorrent groups only consecutive jobs of one commit set, so two builds that overlapped in time
can see each other's results. That favours every ranking alike; LRTS, which orders by time, found
the same primary advantage, and nothing here depends on it more than the rest of the study does.

## Consequences

If a candidate passes, the next step is a frozen replay on held-out data under
[ADR 0033](0033-lrts-is-measured-once-under-a-rule-written-first.md)'s two conditions, and the
changed-file signal would have to be folded in first, under a rule of its own. If none passes, the
measured rates still stand as a description of these projects, and the page says which condition
failed.
