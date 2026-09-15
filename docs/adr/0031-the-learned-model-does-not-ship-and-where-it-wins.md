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
set of hyperparameters, and no look at the held-out projects. A ranking that used the model only
where the history is silent is the obvious next candidate, and it is not built.

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
