# 0030: the learned model is judged before it is fitted

Date: 2026-09-16

## Status

Accepted. Opens phase 6. Written **before** any model was fitted, which is the point of it.

## Context

A learned model is the easiest thing in this project to fool oneself with. It has hyperparameters,
feature sets, sampling rates and a training split, and every one of them is a knob that can be
turned until a number improves. The literature does not even agree on whether it wins: on LRTS the
best learned model reaches 0.736 mean APFDc against 0.735 for "most recently failed" (Cheng et al.,
table 8), while Yaraghi et al. report 0.82 against 0.71 (RQ2.5).

So the rule that matters is not which model, it is what would count as beating the heuristic, and
that has to be fixed before anything is fitted.

## Decision

**The model is a ranking like any other.** It implements the study's `Ranking` protocol and is
scored by the same engine, on the same trials, with the same primary measure and the same
acceptance rule as every candidate of phase 4
([ADR 0014](0014-the-ranking-study-measures-time-to-red-against-latest-failure.md)): APFDc with a
job's failures as one fault, a 95% bootstrap interval above zero, a mean difference of at least
0.005, and a win on at least six projects of ten. No new measure is introduced for it, because a
new measure is how a loser becomes a winner.

**It trains on one half of the development projects and is chosen on the other.** The split is
ADR 0013's rule applied once more, computed in `benchmarks/split.py` and fixed long before this
step: five projects train, five validate, and the ten held-out ones are not touched until a version
is frozen ([ADR 0016](0016-every-look-at-the-held-out-projects-is-recorded.md)). Every comparison
that chooses anything happens on the validation half.

**Rows come only from builds that went red.** A ranking is consulted to decide what to run, and
what it can get wrong is which test of a red build comes first. A green build teaches nothing about
that and there are a hundred times more of them. Within a red build every failing test is kept and
the passing ones are sampled, twenty per failure, because the passes are the repetitive half.

**The features are computed from the builds before the one being ranked**, out of the same
`BuildHistory` the heuristics read. There is no separate pipeline that could see something they
cannot; a feature that read the build's own results would make the model unbeatable on paper and
useless in CI.

**Machalica's feature families that this dataset cannot carry are named, not dropped quietly.**
Windows in days become windows in builds, since RTPTorrent's jobs carry no timestamp this replay
trusts. There is no author, no reviewer and no distributed-build history in the dataset. File
extensions become one comparison rather than a vocabulary, because a one-hot over the extensions of
twenty Java projects would mostly encode which project a row came from.

**Gradient-boosted trees, from scikit-learn.** `HistGradientBoostingClassifier` is the same
histogram algorithm as LightGBM, ships as a pure wheel on every platform this project builds on,
and adds one dependency to the benchmarks rather than a compiler toolchain. It is a development
dependency: nothing in the published package imports it, and nothing will unless the model wins.

**The comparison is published either way.** If the trees lose, the page says so and the heuristic
stays. That was the roadmap's rule before this ADR and it stays the rule.

## Consequences

The model cannot be tuned into a win on the numbers that decide, because the numbers that decide
come from projects it was never fitted on, and the rule for reading them was written here first.

Shipping is a separate decision this ADR does not make. A fitted `HistGradientBoostingClassifier`
is a pickle, and a pickle is not something to load in a user's CI; if the model wins, it will have
to be exported as data the package can read without scikit-learn, and that work is not started.

The study step appears only once a model file exists, which makes `python -m benchmarks.study
learned` unavailable until someone has trained one. That is deliberate: the alternative is a step
that quietly scores an untrained ranking.

Training on red builds only means the model never sees what a quiet week looks like. If it is ever
used to answer "should this build run anything at all", that question will need its own training
set, and this one will not do.
