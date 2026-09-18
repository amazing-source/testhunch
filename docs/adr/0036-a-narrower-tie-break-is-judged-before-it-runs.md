# 0036: a narrower tie-break is judged before it runs

Date: 2026-09-18

## Status

Accepted. Follows [ADR 0035](0035-the-cost-order-decides-where-the-history-is-silent.md). This
record was committed before any of the variants below was replayed; what they measured is added
afterwards, under "What it found", and nothing above that heading changes once they have run.

## Context

ADR 0035 located a cause of the first-failure defect: where the history is silent every test scores
zero, and the duration, second in the sort key, runs those tests cheapest first. Taking the cost out
of the tie-break everywhere bought 0.102 of first-failure position for 0.006 of the primary measure,
on the ten development projects. The maintainer's hypothesis is that the cost could be kept where it
is informative and dropped only where the score carries no risk, for most of that gain at a fraction
of that cost. This record tries to refute it before trying to confirm it.

Before any variant was chosen, the shipped order was described on the **training half only**, by
`python -m benchmarks.costorder training`. Its page, `benchmarks/results/study/cost-order/README.md`,
is committed with this record. Four facts come out of it.

**The duration decides almost nothing but pairs of silent tests.** Of the 2,660,657 pairs of tests
the shipped key orders by duration on the training half's failing jobs, 99.9% are two tests that
have never failed and on which no signal fires. Tests that did fail, so long ago that their priority
underflowed to zero, account for 2,900 pairs; tests of equal score above zero, for 50. A score
divided by a duration practically never ties, so the tie-break only works where the score is zero,
and the score is zero because the history is silent. On these data, a tie-break that keeps the cost
wherever the score is above zero **is** the global one.

**The cost order earns and costs on the same jobs.** Everything the cost order gains over a hash on
the primary measure, +0.004 on the mean over every failing job, and everything it loses in position
comes from one cell: jobs whose failing test had never failed, with that test silent. Of the 1,465
jobs whose failing test had failed before, none has its first failing test among the zero-score
tests: 1,449 have it among the tests with a failure priority above zero, where the tie-break
practically never decides.

**On those jobs the two measures disagree, and they should.** Among the zero-score tests, the failing
one sits at 0.578 counted in tests and at 0.215 counted in time, on 73 jobs. A failure that ignored
cost would sit at 0.5 in tests; one drawn in proportion to cost would sit at 0.5 in time. The data
lie between: dearer tests fail more often, but much less than in proportion to what they cost. Under
that, running the cheapest first reaches the failure sooner in time and later in tests than any
shuffle of the same tests, which is Smith's rule for ordering by probability over cost. The primary
measure counts time and the guardrail position counts tests, so among silent tests any change of
order buys one with the other. That is a property of the problem, not of a parameter.

**The tie-break is the smaller part of the defect.** On the 91 first-failure jobs of the training
half, the position of the first failing test is 0.574 shipped, 0.528 with a hash, 0.453 for random;
in time to red, 0.509, 0.563 and 0.436. The hash closes 0.046 of the 0.121 gap in position and makes
time worse by 0.053. The rest, 0.075 in position and 0.127 in time, remains with any tie-break: the
zero-score tests run after every test whose failure priority is above zero, however small. Where the
failing test is silent, those tests are 0.372 of the job. **Random beats the shipped order on first
failures in time as well as in tests**, so the defect is not an artefact of counting tests.

## Decision

### The variants, closed

Five were considered, from the maintainer's list and from the code. Two are kept.

- **`tie=cost-if-scored`**, the maintainer's priority: the duration decides between equal scores
  above zero, a hash between zeros. Kept, and predicted identical to global hash, which is what
  makes it worth running: by the first fact it can only differ on 50 pairs. If it differs
  measurably, the description above is wrong.
- **`cold-free/tie=cost-if-risk`**: the cost only where the failure history estimates a risk. A test
  whose failure priority is zero is neither divided by its duration nor ordered by it, even when its
  file changed. This is the other reading of "no risk information": the history's, not the score's.
  It differs from the first on the tests whose only score is the changed-file signal, and 16 of the
  91 first-failure jobs of the training half have such a test as their first failing test.
- Not kept, each for a measurement that says it cannot differ from the first:
  - the cost only for tests that did fail once: it reorders faded tests only, 0.1% of the pairs, and
    no first failing test of the training half is faded;
  - the cost after recency and priority in the key: the same 0.1%, and the pairs of silent tests
    keep the cost order under it;
  - the cost only when the job has some evidence at all: 14 of the 1,584 failing jobs have no known
    test scoring above zero.

Global hash, ADR 0035's candidate, is measured again as the yardstick. The shipped ranking is the
reference; `latest-failure`, testhunch 0.2.0 and random are read alongside. No variant touches the
fourth fact: how small a failure priority may be and still outrank a test that never failed is a
different hypothesis, and this step does not test it.

### Predictions, written before the replay

1. `tie=cost-if-scored` equals global hash to within 0.001 on every measure, on both halves.
2. On first-failure jobs whose failing test is silent, `cost-if-risk` places the failing test
   exactly where global hash does. It reorders only tests that stand before every zero-score test
   under both, so the same tests stand before the failing one, in the same time.
3. From the third fact, a variant that hands the pairs of silent tests to a hash cannot keep the
   cost order's primary measure, since all of it sits on those pairs. The first variant therefore
   fails the primary condition below, and the second can only pass if what it gains on
   changed-file tests pays for what it loses on silent ones, without costing the jobs that had
   failed before.

### The rule

Judged on the **validation half** of the development projects, each variant against the shipped
ranking on the same failing jobs, as a mean of per-project means:

1. **It gains enough**: the first-failure position improves by at least **0.051**, half of the
   0.102 global hash gained on the ten development projects. A narrower form that keeps less than
   half the gain is not the correction this looks for.
2. **It costs little enough**: the primary measure drops by at most **0.003**, half of the 0.006
   global hash lost. The maintainer asked for markedly less than 0.006, ideally nothing.
3. **It spares the regime that works**: on the jobs whose failing test had failed before, neither
   the position nor the APFDc moves the wrong way by **0.005** or more, the smallest difference
   ADR 0014 counts.
4. It reads only the history before the build, and 5. it is stated in one sentence. Both variants
   hold these by construction.

A variant that meets the first three on the validation half earns
**`NEEDS_HELD_OUT_CONFIRMATION`**, the one with the higher primary measure if both do. Otherwise
the result is **`DO_NOT_SHIP`**. `SHIP` is out of reach by construction: in this project a ranking
does not ship from development data ([ADR 0013](0013-development-projects-tune-held-out-projects-measure.md),
[ADR 0033](0033-lrts-is-measured-once-under-a-rule-written-first.md)). The training half is reported
under the same rule and does not decide; if it disagrees with the validation half, the
disagreement is stated as a limitation.

The rule is code, `criteria` and `verdict` in `benchmarks/costorder.py`, tested, and committed with
this record.

## What this decision was made knowing

**The training half was looked at**, for the shipped ranking, global hash and the three references:
that is the description above, and it is what the variants were chosen from.

**The validation half is not clean for global hash.** ADR 0035 published its per-trial results
there, and on 2026-09-18, before this record, ADR 0033's rule was computed on those files as an
exploration: global hash's primary advantage over `latest-failure` drops there from +0.025 to
+0.016, and its first-failure position stands 0.084 above random's. So the validation result of
`cost-if-scored` is known in advance, through the first prediction. `cost-if-risk` has not been
measured on either half; each of its two parts has, alone: the divisor removed where the priority
is zero (ADR 0018's `cold-free` step) and the hash tie-break (ADR 0035).

LRTS and the held-out projects are not touched, and nothing here may become a release.

## Consequences

If the rule refuses both variants, the hypothesis that the cost can be dropped only where the score
says nothing is refuted twice: mechanically, because that is the only place the tie-break acts, and
by measurement. What survives is a narrower statement than ADR 0035's. Where the history is silent,
the cost order is not an unjustified preference for short tests: it is the fastest order to a
failure whose chance grows more slowly than its cost, and it pays for that in tests, not in time.

The larger lever then lies elsewhere, and it is named here so that it is tested under a protocol of
its own rather than folded into this one. RTPTorrent's priority decays by a factor of five per build
and reaches zero only after 463 builds, so a test that failed once, a hundred builds ago, still runs
before every test that never failed. Whether such a priority carries any information is an empirical
question, and it is the one the fourth fact points to.
