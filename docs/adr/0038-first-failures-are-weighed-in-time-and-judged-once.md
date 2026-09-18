# 0038: first failures are weighed in time, and two candidates are judged once

Date: 2026-09-18

## Status

Accepted. Decided by the maintainer after [ADR 0037](0037-a-measured-failure-rate-in-place-of-the-priority.md)
and a read-only external review of it. This record, the candidates' code and the rule's code were
committed before either candidate was replayed anywhere. What they measure is added afterwards,
under "What it found", and nothing above that heading changes once they have run.

## Context

ADR 0037's `calibrated+runs` reaches first failures far sooner in time on all ten development
projects and was refused by a rule that asked repeat failures to lose less than 0.005 of APFDc. The
review, checked against the committed per-trial results with this project's own bootstrap, showed
that this refusal fell on noise: on the validation half the repeat-failure difference is −0.0085
with an interval of [−0.033, +0.016], so a bound of 0.005 is finer than what ten projects can
resolve. It also showed that part of that difference is the changed-file signal the candidates
lacked, not the calibration: against the same ranking without that signal, repeat failures move by
−0.004, [−0.025, +0.022], over the ten projects. And it showed that "worse than random in time" was
said of the shipped ranking with an interval that contains zero, +0.072, [−0.043, +0.185].

With the information a ranking has, some trade between the two slices cannot be avoided: running a
test that never failed before one that did gains time on the builds where the first one breaks,
which are first failures, and loses time on the builds where the second one breaks, which are repeat
failures. How much of each is acceptable is a choice about what testhunch is for, and it is made
here, before anything is measured.

## Decision

### The rule

It decides on **one replay of the ten held-out RTPTorrent projects**, run by `python -m
benchmarks.confirmation held-out --held-out`, which writes its row in the ledger before it starts
([ADR 0016](0016-every-look-at-the-held-out-projects-is-recorded.md)). Their first-failure slice has
never been computed for any ranking. Every difference is paired trial by trial on the same failing
jobs and averaged as a mean of per-project means. Every interval is a 95% percentile bootstrap,
10,000 resamples, seed 0, that draws projects with replacement and then builds with replacement
inside each drawn project, as [ADR 0033](0033-lrts-is-measured-once-under-a-rule-written-first.md)
did with pull requests. A build is a concurrent group of the replay, recorded with each trial.
"Clearly" means an interval that excludes zero.

A candidate passes when all four hold:

1. **First failures, in time.** Its red at on the first-failure slice is clearly sooner than
   random's: the interval of the difference lies entirely below zero. The slice is the one
   `benchmarks/study/engine.py` defines, unchanged.
2. **The baseline.** Its primary measure is clearly above `latest-failure`'s: the interval lies
   entirely above zero.
3. **What ships today.** Its primary measure is not below the shipped ranking's on average, and is
   higher on at least 60% of the projects, six of ten, as ADR 0014 counts.
4. **Repeat failures, as a veto only.** Its APFDc on the jobs whose failing test had failed before
   is published against the shipped ranking with its interval, and vetoes only when that interval
   lies entirely below −0.005, ADR 0014's smallest difference.

**The guardrail moves from position to time.** [ADR 0018](0018-first-failures-are-a-guardrail-not-an-average.md)
put it on the position of the failing test. Condition 1 puts it on red at, because the primary
measure and the budgets are in time (ADR 0014, ADR 0017) and because ADR 0036 measured that the two
disagree by nature among tests the history says nothing about. The position stays published beside
it, with its interval, and no longer decides. **A ranking can therefore pass while being worse than
random in position on first failures**; if the one that passes is, the page says so and the README
will say so. No claim is made project by project on the first-failure slice, which holds 5 to 30
jobs a project.

Both candidates pass or fail on their own. If both pass, the one with the higher primary measure is
the result. A pass is a **proposal to ship**: releasing is the maintainer's decision, and the product
would have to rank exactly as the study does, held by a replay test as for ADR 0015. If neither
passes, the result is **`DO_NOT_SHIP`**, published as every other refusal was.

This rule applies to this step. ADR 0037's verdict on the validation half stands as written.

### The candidates, closed

Both are in `benchmarks/study/rankings.py`, and both use the **changed-file signal as a cut of the
state**, as the maintainer asked: each state's rate is also counted separately for runs whose test
file changed and runs whose test file did not, and a cell is drawn toward its state's rate by one
run's worth, the same smoothing the states already get. There is no weight to choose, and the
chance stays a probability. The signal is the shipped ranking's own function, now in
`benchmarks/study/history.py` and used by both. A build or a job whose changed files are unknown
counts in the state and in neither cell, and ranks with the state's rate, since an unknown change is
not an empty one. A cell with few runs is noisy; that is variance, not bias, and it is a limitation
this step accepts rather than a constant it tunes.

1. **`two-stage`**, first. A test that failed before and whose measured chance of failing is above
   the project's rate for a test that never failed keeps the place the shipped ranking gives it,
   ahead of everything else. Every other known test, old failures that predict no more than never
   failing among them, follows in the order of the second candidate. The line is the project's own
   never-failed rate, every run and cell together; there is no constant.
2. **`calibrated+runs+file`**: ADR 0037's `calibrated+runs` with the changed-file cut. It is the
   integration ADR 0037's consequences required before any held-out replay, and the second stage of
   the first candidate.

Measured alongside, never judged: the shipped ranking, ADR 0037's frozen `calibrated+runs`,
`latest-failure`, testhunch 0.2.0 and random.

Not kept: the candidate the review offered second, which would count a failure as 1/k when k tests
fail in the same build. It would make the rate something other than a probability, which the cut
above exists to keep, and the evidence for it was found after the fact on three projects.

### Before the look: the training half

`python -m benchmarks.confirmation training` replays the training half, the only one explored. Its
results cannot add, remove or alter a candidate. They can reveal a defect in the code, which is then
fixed and stated here. The maintainer may, after reading them, decide not to spend the look at all;
that can only cancel the replay, never change it, and the decision would be recorded here.

Predictions, point estimates on the training half, written before the replay:

1. The file cut gives repeat failures back some APFDc: `calibrated+runs+file` is above
   `calibrated+runs` on them, and moves first-failure red at by no more than 0.02 either way.
2. `two-stage` loses no APFDc on repeat failures against `calibrated+runs+file`, and at most 0.002
   against the shipped ranking.
3. `two-stage` keeps at least half of `calibrated+runs+file`'s first-failure gain in red at over the
   shipped ranking.
4. `two-stage` places repeat failures within 0.02 of the shipped ranking in position.
5. `calibrated+runs+file` is calibrated: in each decade of predicted chance where at least 20
   failures are expected or seen, the observed rate is within a factor of two of the predicted one.

## What this decision was made knowing

The training half has been read for ADR 0037's candidates, for the hazard counts and for the
diagnosis of repeat failures. The validation half has been read for ADR 0037's candidates and plays
no part here. On the held-out projects, the primary measure of the shipped ranking, `latest-failure`
and 0.2.0 has been published and read by whoever writes this; their first-failure slice has never
been computed, and neither candidate has been replayed on them. LRTS is not touched. The two
candidates were built from what the training and validation halves showed, which is the reason the
decision is taken on data neither of them saw.

The replay includes SonarQube, which put 13.9 million rows through a single ranking in 53 minutes
(ADR 0033); with seven rankings it will take hours, and it runs from a clean, pushed checkout.

## Consequences

If a candidate passes, testhunch has, for the first time, a ranking that reaches a test failing for
the first time sooner than chance, in time, on projects it was never tuned on, at no cost to the
primary measure; shipping it is then a product change with its own review. If neither passes, the
ADR 0037 family stops here, and what remains is the measured trade and the rates that describe it.
Either way the look is spent, and it is recorded.
