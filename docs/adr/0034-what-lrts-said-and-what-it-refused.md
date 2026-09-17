# 0034: what LRTS said, and what it refused

Date: 2026-09-17

## Status

Accepted. Records the outcome of the single replay
[ADR 0033](0033-lrts-is-measured-once-under-a-rule-written-first.md) registered, run on
2026-09-16 at 21:40 and finished at 01:19, ledger row at commit `002aba9f6b2d`, version 0.5.0.
Nothing was changed about the protocol after the numbers appeared.

## What it measured

Ten projects, 34 645 builds, 108 366 suite runs, 49 665 failing trials scored, six frozen rankings.
The page is `benchmarks/results/lrts/README.md`.

**The ranking holds outside the data it was built on.** On the primary measure, APFDc with a job's
failures as one fault, averaged per project then over projects:

| Ranking | LRTS | for comparison, the RTPTorrent held-out half |
|---|---:|---:|
| what testhunch ships | **0.893** | 0.840 |
| `latest-failure` | 0.864 | 0.812 |
| `random` | 0.656 | |
| testhunch 0.2.0 | 0.865 | 0.797 |

The shipped ranking beats the baseline by **+0.030**, with a 95% clustered interval of
[+0.021, +0.040], and it is ahead on **ten projects out of ten**. That is the external validation
this phase existed for, and it passed.

**The weakness is confirmed, and it is worse here than at home.** On the first-failure slice, the
position of the first failing test, lower being better:

| Ranking | first failure | had failed before |
|---|---:|---:|
| what testhunch ships | 0.620 | 0.038 |
| `latest-failure` | 0.544 | 0.028 |
| `random` | 0.449 | 0.342 |
| **testhunch 0.2.0** | **0.291** | 0.081 |
| learned | 0.325 | 0.049 |
| cold-learned | 0.357 | 0.031 |

The shipped ranking is worse than shuffling by +0.171, interval [+0.083, +0.259], entirely on the
wrong side of zero. On a dataset it had never seen, testhunch is measurably worse than chance at
finding a test that is failing for the first time.

## What the rule refused

None of the four candidates satisfies both conditions, and the rule was written before any of this
was visible.

| Candidate | clears the guardrail | above `latest-failure` | ships |
|---|---|---|---|
| what testhunch ships | no, +0.171 [+0.083, +0.259] | yes, +0.030 [+0.021, +0.040] | no |
| testhunch 0.2.0 | yes, -0.157 [-0.232, -0.079] | no, +0.002 [-0.016, +0.021] | no |
| learned | yes, -0.124 [-0.185, -0.065] | no, -0.089 [-0.116, -0.062] | no |
| cold-learned | yes, -0.092 [-0.157, -0.027] | no, -0.011 [-0.025, +0.000] | no |

`testhunch-0.2.0` fails on a tie, not on a loss: +0.002 against the baseline with an interval that
spans zero is level, and the rule asks for above. `cold-learned` fails by 0.011, with an interval
whose upper end touches zero. Both are refused, and the refusals stand: a bound that moves after the
table is read is not a bound.

## The finding worth keeping, and it is not the one phase 6 expected

**The learned model is not what repairs the first-failure regime here. Our own 0.2.0 is**, and by a
distance: 0.291 against the model's 0.325 and the shipped ranking's 0.620, better than the shipped
ranking on **ten projects out of ten**.

So the trade the roadmap parked now has a number, measured on data that did not raise the question:
**0.028 of the primary measure buys 0.329 of first-failure position**. Phase 6 estimated 0.03 for
0.22 from 192 trials, one model and one set of hyperparameters
([ADR 0031](0031-the-learned-model-does-not-ship-and-where-it-wins.md)). The exchange is better than
that estimate, and it does not need a learned model at all.

This also settles which direction to look. A learned model would have to be exported as data the
package can read, would add a fitting pipeline to maintain, and is beaten on this slice by a
formula of three terms that shipped in 0.2.0. Whatever gives 0.2.0 this property is worth finding
before anything else is built.

## Two honesty notes

**The slice is 993 trials, not the 2 140 builds ADR 0033 quoted.** That number came from the
external audit, which counts a build as soon as **one** class fails for the first time. This project
has counted the slice differently since ADR 0018, and kept doing so here: **every** known failing
test of the trial has to be a first failure. Under our own definition LRTS holds 993 of them,
against 283 on the development projects. The looser count would have been a different measure, and
switching to it after seeing the results would have been the worse choice.

**No per-project claim is made on the slice.** Three projects contribute a few dozen trials each.
The pooled estimate is what this page reports, its interval is clustered by pull request inside
project, and the per-project column exists for the primary measure only.

## Consequences

Nothing ships, and the shipped ranking keeps a measured defect that is now confirmed twice, on two
datasets, one of which it had never seen.

The next step is **not** a candidate: it is finding what gives 0.2.0 that property, because until
that is known, any attempt to buy it back is guessing. ADR 0018 eliminated three explanations, the
proximity signals, the name signal on its own, and the cost divisor, and named a fourth it refused
to test. That work resumes under a rule fixed before it runs, on the training half of the
development projects, with the choice made on the validation half.

LRTS is not spent for good: a frozen candidate can be replayed on it once more, with its own ledger
row, the way the RTPTorrent held-out projects are. What is excluded is going back for a better
answer to the same question.
