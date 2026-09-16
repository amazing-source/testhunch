# 0029: a budget passes over what it cannot afford

Date: 2026-09-16

## Status

Accepted. Amends [ADR 0017](0017-a-budget-is-a-share-of-the-test-time.md), which chose the rule this
one replaces.

## Context

A time budget took the longest prefix of the ranking that fits and stopped at the first test too
expensive to fit. ADR 0017 chose that deliberately: the order is what the ranking promises, and a
better-packed set would run tests the ranking placed below ones it left out.

Running testhunch on its own CI made the cost of that rule visible
([ADR 0028](0028-testhunch-measures-itself-and-publishes-that-it-cannot.md)). One test there is
worth most of the suite's time. When its own file changes, the ranking lifts it near the top, it
does not fit, and everything below it is cut with it: **one build of seventy-four spent a hundredth
of the time its budget allowed**. The user asked to spend a quarter of the test time and got a
hundredth of it, with the protection that buys.

That is not the order being honoured. It is the budget being lost.

## Decision

Three rules were replayed side by side on the **same** rankings, over the ten development projects
and their 30 944 usable jobs, so that the only difference between the columns is what happens at a
test that does not fit (`python -m benchmarks.budgetpacking`, page in
`benchmarks/results/study/budget-packing/`):

- **prefix**: stop there, the rule of ADR 0017.
- **oversized**: pass over a test that could not have fitted in the whole budget however early it
  came, and stop at any other test that does not fit.
- **fill**: pass over everything that does not fit, to the end of the ranking.

**Under every rule, the ranking's first choice runs whatever it costs.** That is what "at least one
test" has meant since ADR 0017, and making it common to all three is what makes the comparison
about packing rather than about which rule may skip the top of the ranking. The first attempt at
this measurement did not do that, and made prefix look better than it is.

**A rule that spends more time is not thereby better**, so the comparison that decides is at equal
time: prefix measured at three budgets gives a curve of failing jobs caught against time spent, and
each rule is placed on that curve at its own time cost. The page computes it; it is not prose
written beside a figure.

**The rule becomes `fill`.** At equal time it catches **2.0, 3.0 and 2.6 points more failing builds**
at the three budgets. `oversized`, the conservative repair that only passes over what no order could
have run, gains 0.5 to 0.6 points: it fixes the degenerate case and leaves most of the gain on the
table.

This overrules the principle ADR 0017 argued from, and it is worth saying why rather than only that
the numbers won. **The order is a promise about priority, not about inclusion.** A budget is a
constraint the user set, and running the next test that fits does not reorder anything: every test
that could be afforded in its turn still runs in its turn. What changes is that a test nobody could
afford no longer takes the rest of the ranking down with it.

An earlier draft of this ADR chose `oversized`, on seven of the ten projects, where the gap between
the two looked small. It is not small. The draft is recorded here because a decision reversed by
its own measurement is the kind of thing this repository is supposed to keep.

## Consequences

The published budget tables move, which is why this needed a measurement and a page rather than a
quiet fix.

`testhunch.shadow.budget_ranks` now returns the **set of ranks** a budget runs, not a count, because
the selection is no longer a prefix. `time_budget_size` remains, defined in terms of it, for the
callers that only want a prefix length. `budget_cut` is gone, replaced by `budget_selection`.

**A user will see a test left out with cheaper tests below it running.** That is the visible cost of
this decision. The answer is that the expensive one did not fit in what was left, and testhunch
prints the reason beside every ranked test.

**A larger budget can run fewer tests and catch fewer failures than a smaller one.** This was found
after the fact, on 2026-09-16, while regenerating the published tables, and it is a property of the
rule rather than a defect in its implementation: filling greedily in rank order is first-fit, and
first-fit is not monotone in the capacity. With expected durations `[1, 4, 1, 1]`, a budget of 50%
runs ranks 1, 3 and 4, and a budget of 75% runs ranks 1 and 2, because the second test finally fits
and takes the whole budget with it. The `prefix` rule this ADR replaces could not do that, since a
longer prefix contains the shorter one. `oversized` is not monotone either: on the same durations it
gives ranks 1, 3, 4 at 50% and rank 1 alone at 75%.

Counted per job, over the 61 888 adjacent budget pairs of the ten development projects, the cost is
common and rarely harmful. The page has the table; the shape of it is that `fill` drops a test in
**15.9%** of pairs, runs strictly fewer failures in 27 of them, and turns a failing build back to
green in 19. `prefix` scores zero on all three, so its monotonicity is now measured rather than
argued. `oversized` sits between the two on the first column and is **worse than `fill` on the one
that matters**: it loses 27 builds against 19, while dropping fewer tests.

Per project the losses are usually buried by the gains, which is why the development projects show
no inversion in their published totals. On a small project they surface: `neuland@jade4j` catches 96
of its 96 failing jobs at a 25% budget and 92 at 50%, while running 2 208 more classes.

**The rule stays.** Monotonicity would mean going back to `prefix`, which costs 2.0 to 3.0 points of
failing builds caught at equal time, measured above, against an inversion that costs a red build in
19 pairs out of 61 888. What changes is that the property is written down, rather than discovered by
a user who raised a budget and caught less.

`oversized` stays in the code and in the page. It is the rule to reach for if the explanation above
ever proves too surprising in practice, and keeping it measured costs nothing.

The measurement covers the development projects only. Nothing is claimed about the held-out ones
until a frozen version is replayed against them and a row is written in the ledger
([ADR 0016](0016-every-look-at-the-held-out-projects-is-recorded.md)).
