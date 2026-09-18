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

## What it found

Replayed on both halves with the code committed with this record, `python -m benchmarks.calibration
training` then `validation`; every figure below is on the page it writes,
`benchmarks/results/study/calibration/README.md`.

**Recommendation: `DO_NOT_SHIP`.** Both candidates meet three conditions of four on the validation
half and fail the fourth: the jobs whose failing test had failed before lose 0.020 of APFDc under
`calibrated` and 0.009 under `calibrated+runs`, where 0.005 was the most allowed. The same happens
on the training half, 0.011 and 0.007.

| Validation half, against the shipped ranking | primary | red at, first failures | position, first failures | had failed: APFDc |
|---|---:|---:|---:|---:|
| `calibrated` | +0.003 | -0.240 | -0.033 | -0.020 |
| `calibrated+runs` | +0.013 | -0.242 | -0.115 | -0.009 |

**What is robust: first failures are reached far sooner in time, on every project.** Red at falls
from 0.496 to 0.253 on the validation half, against 0.425 for random, and `calibrated+runs` is
sooner than the shipped ranking on all ten development projects, from 0.002 on jetty to 0.42 on
okhttp and dynjs. Within a quarter of the test time it catches 65.0% of the validation half's first
failures, against 27.0% for the shipped ranking and 39.0% for random; 57.9% against 34.9% and 39.5%
on the training half. This is the first ranking in the project that beats random on this slice in
time.

**What is not: the primary measure.** Its mean rises, +0.013 and +0.014 on the two halves, but the
intervals contain zero and the rise is carried by two projects: `calibrated+runs` is better than
the shipped ranking on the primary measure on 5 of the 10 projects, and on HikariCP by +0.112 and
okhttp by +0.057. No gain on the primary measure is claimed.

**What it costs: the jobs that had failed before.** Their APFDc drops on 7 of the 10 projects,
by up to 0.072 on dynjs, and their position rises from 0.078 to 0.265 on the validation half. A
state's rate is an average over the tests in it: a test that fails in every build and a flaky one
that failed once, last build, share the state "failed 0" and its rate, so a dear test that is
simply broken can wait behind cheap tests that rarely fail. That is the mechanism the second
prediction described, and it is a hypothesis for the next step, not a measurement of this one.

**The predictions.** The first held: on the training half, red at on first failures is 0.288 and
0.322 against 0.667 for the same ranking without the file signal. The second held on both halves:
the jobs that had failed before move far more in position than in APFDc. **The third failed on the
training half**: test age made first failures worse there, 0.322 against 0.288 in red at and 0.530
against 0.512 in position, and it helped on the validation half, 0.575 against 0.657 in position.
Test age is not established as a signal.

**The guardrail of ADR 0018 is still not cleared in position.** On first failures,
`calibrated+runs` places the failing test at 0.575 against 0.438 for random on the validation half,
an interval entirely above zero. It gets there sooner than random in time by running many cheap
tests first, which is Smith's rule working as intended and the position-time conflict of ADR 0036
seen from the other side.

**Limitations.** Development projects only, 91 and 192 first-failure jobs. The validation half had
been read before for the references, not for these candidates. The candidates lack the changed-file
signal, which the shipped ranking has; against the same ranking without it, `calibrated+runs` adds
+0.038 and +0.011 of primary, intervals containing zero. RTPTorrent's grouping of overlapping
builds favours every ranking alike.

**What would come next, under a protocol of its own.** Keep the measured rate, which is what moves
first failures, and give back to repeat failures what the pooled state takes from them: tell a test
that keeps failing from one that failed once, within the recent states. The validation half has now
been read for this family of rankings, so a candidate built from what it showed should be explored
on the training half and confirmed on data not yet read for first failures: the held-out RTPTorrent
projects, whose first-failure slice has never been computed, with a row in the ledger.

## After it, on the training half

What the step above called a hypothesis for the next one was measured, on the training half only,
before writing any protocol: `python -m benchmarks.repeats training`, then
`python -m benchmarks.calibration training --step streaks`. No candidate came out of it, and
neither the validation half nor the held-out projects were read.

**Where the time goes before a repeat failure.** On the jobs whose failing test had failed before,
`calibrated` spends more time than the shipped ranking on tests that never failed, on all five
projects, from +0.003 to +0.028 of the job; `calibrated+runs` spends less of it, from +0.003 to
+0.020, and never gets back to the shipped ranking. On dynjs alone, tests that failed eight builds
ago or more also run first more often, about +0.05 together. Tests that failed in the build just before
barely move.

**Streaks predict, and do not help.** A test that failed in the build just before fails again 282
to 659 times per thousand runs after a single failure, and 930 to 991 after eight or more in a row
on deeplearning4j, jetty and jOOQ. Splitting that state by streak, 1, 2 to 3, 4 and more, was the
correction these counts supported best. It does not recover what repeat failures lose: their APFDc
drops by 0.011 against the shipped ranking, where `calibrated+runs` loses 0.007, and first failures
barely move. The pooling of broken and once-failed tests is not what defers repeat failures.

**What that leaves.** The loss on repeat failures is, for the most part, the rule working: a test
that never failed has a chance of failing above zero, so a cheap one runs before a dear test that
failed recently when its chance per unit of time is higher, and that is exactly what reaches first
failures sooner. Part of it was the rate given to tests that never failed, which test age
reduces. What remains is a trade between the two slices, not a calibration error found so far,
and ADR 0037's rule refuses the trade at its current size. Whether that rule should weigh the two
slices differently is a decision about what testhunch is for; it would have to be made before any
further measurement, and it is not made here.
