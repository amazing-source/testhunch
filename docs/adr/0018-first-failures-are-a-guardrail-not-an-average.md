# 18. First failures are a guardrail, not a line in an average

Date: 2026-09-15
Status: accepted

## Context

Splitting the failing jobs of the development projects by whether the failing test had ever failed
before (`python -m benchmarks.firstfailures`, benchmarks/results/study/first-failures.md) showed two
regimes, and only one is good:

| Position of the first failing test | had failed before (4 182 jobs) | never failed (283 jobs) |
|---|---:|---:|
| testhunch | 0.124 | 0.692 |
| latest-failure | 0.107 | 0.616 |
| random | 0.460 | 0.472 |

On a test's first failure testhunch ranks **worse than shuffling**, and structurally so: a ranking
built on the recency of failures puts what has never failed last, so it looks in the wrong place
exactly when the bug is new. Cheng et al. (ISSTA 2024, Table 10) measure the same collapse on the
latest failure alone.

Two things the measurement settled:

- the bias is in the ranking, not in the rule that runs every unseen test first (ADR 0006, 0007):
  the position among the known tests only, 0.704, equals the global 0.692;
- on that slice testhunch's only edge over the latest failure is **cost, not prediction**: it wins
  on time (0.554 against 0.721) because quick tests run first, while its *position* is worse.

The study of ADR 0014 never saw this. Its steps judged every candidate on the mean over all failing
jobs, where the 94% with a usable history drown the 6% without. Step 3 rejected `path_similarity`,
`token_similarity` and `name_similarity` on that mean, and kept `test_file_changed`, the one signal
that is binary and fires on about a fifth of the jobs.

## Decision

**The measures are three, and they are never merged into one score.**

1. *Primary*: the share of failing builds caught at a budget of test time (ADR 0017).
2. *Secondary*: how fast the build turns red — APFDc and `red_at` (ADR 0014).
3. *Guardrail*: the position of the first failing test on the **first-failure slice**.

A single blended score would let the easy 94% keep hiding the hard 6%, which is how this went
unnoticed for the whole study. Every ranking change from now on is reported on both slices.

**The guardrail bar is random, not a fitted threshold.** A ranking must not be worse than shuffling
at finding a test that has never failed. That bar needs no data to justify, so it cannot be bent to
fit a candidate, and it is exactly the line testhunch fails today. It is a bar to clear, not a
measure to maximise: a version that merely reaches random on that slice has stopped being actively
misleading, nothing more.

Deliberately **not** decided here: how much of the primary a candidate may give up to clear the
guardrail. Fixing that number from the 283 jobs that produced this ADR would tune a rule on the
very cases that motivated it. LRTS ships a `FirstFail` variant for exactly this question, and the
trade-off is settled after it has been measured there, not before.

**The next study step tries the proximity signals where the history is silent.** Its rule, fixed
before any candidate is run:

- *Candidates*: the five proximity signals already implemented in `benchmarks/study/rankings.py`, at
  the three weights the study already used (0.1, 0.5, 2.0), in two forms — added to the score for
  every test, as step 3 tried them, and added **only for tests whose failure priority is zero**,
  that is, only where the history says nothing. No new signal is invented for this step, and no new
  weight grid: both would be degrees of freedom chosen after seeing the problem.
- *Kept* only if all three hold, each with the 95% bootstrap interval of ADR 0014 over the
  development projects: the first-failure position improves; the primary measure does not get
  worse; and the first-failure position is not worse than random.
- Nothing is kept on the guardrail alone if it costs the regime that works. The point is to stop
  being worse than chance on new failures while staying four times better than chance on the rest.

## What this decision was made knowing

The proximity signals had already been measured **alone, with no history**, on the development
projects before this ADR was written (`--signals`,
benchmarks/results/study/first-failures-signals.md): on the first-failure slice they place the
failing test between 0.335 and 0.351, against 0.47 for random and 0.692 for the whole current
ranking. So the direction was known; what was not is how they behave once combined with the
history, which is what the step measures and what the rule above decides.

## Consequences

- `benchmarks/firstfailures.py` becomes part of the decision, not a diagnostic: a candidate that is
  not measured on both slices cannot be accepted.
- Only 118 of the 283 first-failure jobs have known changed files, so a proximity signal can reach
  at most 42% of the problem on RTPTorrent. That is a limit of the dataset, where many jobs carry no
  commit, more than of the product: a real `testhunch` run always reads `git diff`.
- The published Phase 3 and Phase 4 results stay as they are. They were measured on the primary and
  secondary measures, which this ADR does not change.
- Meta removed "common tokens between paths and test names" because it degraded their model
  (Machalica et al., Table I). On this slice `token_similarity` is the strongest single signal.
  Both can hold — their model had many other features, ours has nothing when the history is silent —
  and the contradiction is published rather than quietly dropped.
