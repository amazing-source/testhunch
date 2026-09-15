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

The cold-start form does **not** fence off the regime that works, and it would be wrong to assume
it does: a test whose failure has decayed keeps a small priority, so a large enough cold weight puts
a never-failed test in front of it. That is exactly why both slices are measured rather than only
the one the change is aimed at. A test holds this behaviour, so nobody rediscovers it by surprise.

## What this decision was made knowing

The proximity signals had already been measured **alone, with no history**, on the development
projects before this ADR was written (`--signals`,
benchmarks/results/study/first-failures-signals.md): on the first-failure slice they place the
failing test between 0.335 and 0.351, against 0.47 for random and 0.692 for the whole current
ranking. So the direction was known; what was not is how they behave once combined with the
history, which is what the step measures and what the rule above decides.

## What the step it describes found

Run on the development projects (benchmarks/results/study/cold-start.md): **no candidate of the
thirty passes**, and two things came out of it that change where to look next.

The proximity signals are **continuous**: they give a non-zero value to every test that has never
failed. Even at weight 0.1 and applied only at cold start, that outweighs the decayed priority of a
test that failed three builds ago, which is down to 0.006. So the ranking drowns: the best candidate
moves the first-failure position from 0.692 to 0.633 — never reaching random — while the regime
that works collapses from 0.123 to 0.331, and the primary measure loses 0.026 with an interval
entirely below zero.

And the reference line says something worse about us: **testhunch 0.2.0 scores 0.455 on that slice,
better than random, while the version this study kept scores 0.692.** The regression was introduced
by our own study. 0.2.0 carried a cold-start signal — its name affinity, weight 2.0, applied to
every test — and the study replaced it with `test_file_changed*0.5`, which fires on about a fifth of
the jobs. It bought 0.018 of mean APFDc and sold the property that protected new code.

The lesson is about the shape of the signal, not its strength: what worked was **selective**, firing
only on a file-stem match, so it never flooded the ranking. A continuous similarity cannot be made
selective by lowering its weight, as these thirty candidates show.

## The step that follows, and the freedom it takes

`name`, the signal that *is* 0.2.0's file-stem affinity, was never among those thirty: the code
files it under the history signals, and the step iterated the proximity ones. It is tried now, in
the same two forms and at the same three weights, as `STEPS["selective"]`, under the rule above,
unchanged.

This candidate set was chosen **after** seeing that the continuous signals fail and that 0.2.0
keeps the property they could not buy back. That is a degree of freedom the first step did not
take, and it is the reason development projects exist (ADR 0013) — but it is written here rather
than left implicit. The rule that decides is untouched, and the held-out projects stay untouched
until there is something frozen to measure on them.

The signal has already been tried in its `always` form, in steps 1, 2 and 4, and rejected on the
mean. It may well fail again. What is new is only the form and the slice it is judged on.

It did fail (benchmarks/results/study/selective.md): the name costs almost nothing on the mean,
0.861 against 0.861, and buys almost nothing on the slice, 0.692 to 0.670. So it is not the name
that gives 0.2.0 its 0.455, and three of our own numbers say what does:

| | divides by the duration | first-failure position |
|---|---|---:|
| latest-failure | no | 0.616 |
| the current version | yes | 0.692 |
| testhunch 0.2.0 | no | 0.455 |

The same name signal is worth 0.16 in 0.2.0 and 0.02 here. What differs is the divisor: a slow test
whose name matches the change is worth 2.0 undivided, but 2.0 / 900 ms once divided — less than a
quick test that failed two builds ago and has decayed to 0.003. The signal is given and taken back.

**The last step, `cold-free`, drops the cost where the history is silent**: `cold_time_exponent=0`,
alone and with the name at each weight. Dividing by a cost arbitrates between tests whose risk is
estimated; where nothing is estimated there is nothing to arbitrate.

This is the third candidate set derived from looking at development results, and the last: whatever
it returns, this line of search stops there. Each set takes a little more freedom with those
projects, and the risk of fitting them is a thing to stop before discovering, not after.

It failed too (benchmarks/results/study/cold-free.md): dropping the divisor is worth 0.001 on the
slice, 0.692 to 0.691, and with the name added it lands where the name alone already did. The
hypothesis was wrong — the divisor is not what annuls the signal.

**Three families are now measured and eliminated**: the continuous proximity signals flood the
ranking, the selective name signal costs nothing and buys almost nothing, and the cost divisor is
not the cause. And 0.2.0's 0.455 is still unexplained by any of them.

A fourth hypothesis is written down here and deliberately **not** tested: **the window**. 0.2.0
ranked only the tests seen in its last 50 runs and ran everything else first, as unknown; ADR 0015
removed that window, so testhunch now remembers every test forever. A test that has never failed is
often a test that runs rarely, and 0.2.0 floated it to the front for free. Testing it would be the
fourth turn of the same wheel, each turn chosen by looking at the same ten projects — which is how a
ranking ends up fitted to them without anyone noticing. Whoever picks this up starts here, and
starts by fixing a rule.

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
