# 0031: the learned model does not ship, and the one place it wins

Date: 2026-09-16

## Status

Accepted. The outcome of the protocol fixed in
[ADR 0030](0030-the-learned-model-is-judged-before-it-is-fitted.md).

## Context

Gradient-boosted trees were fitted on the training half of the development projects and scored by
the study's engine on the validation half, against the heuristic the study kept in phase 4. Two
variants ran: the model's predicted probability of failure, and the same probability divided by the
test's expected duration, which is the cost arbitration the shipped ranking makes.

The page is `benchmarks/results/study/learned.md`. On the primary measure, APFDc with a job's
failures as one fault:

- the raw model **loses** to the heuristic, and wins on one project of five;
- divided by duration it **ties**: the mean difference is +0.001, the 95% interval spans zero, and
  the acceptance rule of ADR 0014 asks for at least +0.005.

Neither passes. That is not a surprise the literature forbids: on LRTS the best learned model and
"most recently failed" are separated by a thousandth (Cheng et al., table 8).

## Decision

**The learned model does not ship.** The rule was written before it was fitted and it is applied as
written: the heuristic stays. Nothing in the published package imports scikit-learn, and the model
lives in `benchmarks/` as a measurement, not as a product.

**The comparison is published anyway**, as the roadmap required before any of it was run.

**One result is worth carrying forward, and it is not the primary measure.** On the slice where a
job's failing test had never failed before, the guardrail of
[ADR 0018](0018-first-failures-are-a-guardrail-not-an-average.md), the raw model puts the first
failure at **0.445** against the heuristic's 0.740, and against **0.455 for random** measured on
the same five projects and the same 192 jobs (`python -m benchmarks.firstfailures` on the
validation half). It costs almost nothing on the other slice, 0.132 against 0.127.

So it is the first ranking this project has measured that is not worse than random where the
history says nothing. The margin over random is one hundredth, which is not a claim of skill; what
it is, is the end of a regression the study itself introduced (ADR 0018).

That is the first thing this project has measured that improves the regime it is worst at. It is
recorded here as a lead, not as a result: 192 jobs of the validation half, one fitted model, one
set of hyperparameters, and no look at the held-out projects.

## The candidate this ADR named, built and measured

`cold-learned` keeps the heuristic's order for every test whose failure priority is not zero, and
re-orders the others among themselves by the model's probability, in the positions they already
had. It is the narrowest use of the model there is: it cannot move a test the history speaks about.

It **loses**: 0.854 on the primary measure, 0.029 below the heuristic, ahead on none of the five
projects. And it does so while improving both position slices, 0.740 to 0.521 where the history is
silent, and 0.127 to 0.123 where it is not.

The explanation is the one ADR 0018 already found from the other side. Among tests the history says
nothing about, the heuristic orders by cost, and that ordering is doing real work for a time-weighted
measure: running the cheap ones first turns the build red sooner even when the guess about *which*
test is worse. Replacing that order with a risk estimate buys a better position and pays for it in
time, and APFDc counts the time.

## Combining the estimate with the cost, which is the same measurement from the other side

`cold-learned+time^1.0` divides the model's probability by the expected duration among the cold
tests, instead of letting it replace the cost ordering. It scores 0.879, four thousandths below the
heuristic with an interval that spans zero, ahead on three projects of five: a tie. And the
first-failure slice goes back to 0.734, against the heuristic's 0.740.

**The gain and the loss are the same thing.** The model's advantage on first failures comes exactly
from ignoring the cost, and the cost is what buys the primary measure. Divide by it and the order
among cold tests converges back to the heuristic's; do not, and the build turns red later. There is
no arrangement of these two that keeps both, and three were measured.

So phase 6 ends on a question the roadmap already parks: what a candidate may give up on the primary
measure to clear the guardrail of ADR 0018, which that roadmap says is to be decided after LRTS and
not before. This ADR does not decide it. What it adds is that the trade is now **measured** rather
than hypothetical: roughly 0.03 of APFDc buys 0.22 of first-failure position.

## Consequences

Phase 6 closes without changing what testhunch ranks with, and says so on the front page of the
measurements rather than only in a step page.

The features, the dataset builder and the fitting code stay in the repository. They cost one
development dependency, they are what makes the claim checkable, and they are where the next
candidate starts.

**The permutation importances are reported and should not be read as "what the ranking uses".** The
strongest column is `tests_in_build`, which is constant within a build and therefore cannot order
anything inside one; it helps a pointwise classifier tell risky builds from quiet ones, which is a
different question from the one the ranking answers. That mismatch between a pointwise model and a
ranking task is itself a lead: a model trained to order within a build, rather than to score a pair
in isolation, is not what was tried here.

Nothing was measured on the held-out projects, and nothing may be until a version is frozen
([ADR 0016](0016-every-look-at-the-held-out-projects-is-recorded.md)). Since no candidate is kept,
there is nothing to freeze, and the ledger gains no row.
