# 0035: the cost order decides where the history is silent

Date: 2026-09-17

## Status

Accepted. Resumes the search [ADR 0018](0018-first-failures-are-a-guardrail-not-an-average.md)
stopped, under a rule fixed before anything runs, which is what that ADR asked of whoever picked it
up. The question it answers is the one
[ADR 0034](0034-what-lrts-said-and-what-it-refused.md) left: **what** gives testhunch 0.2.0 its
first-failure property, since LRTS showed the property is real and worth 0.329 of position.

## Context

Four phases of study have measured that this ranking is worse than shuffling at finding a test that
is failing for the first time, and LRTS confirmed it on ten projects it had never seen: 0.620
against random's 0.449. On the same slice, 0.2.0 reaches 0.291, better than the shipped ranking on
ten projects of ten.

ADR 0018 eliminated three explanations and named a fourth. The fourth, the window, is not the
answer: it never fires. On HikariCP, okhttp and jOOQ the median age of a test since its last run is
**one build**, and a five-build window marks between 0.0% and 1.3% of encounters as stale, because
these suites re-run everything every build. That measurement is redone reproducibly by this step
rather than quoted from the exploration that found it.

**The explanation this ADR proposes was found by reading the sort key, not by searching.** A
candidate orders its known tests by

```python
(-score, duration, -record.last_failure, -record.priority, tie(job_id, test))
```

On the first-failure slice every candidate scores zero: the test has never failed, and the signals
the study kept fire on a fifth of jobs at most. So the first element is a tie for all of them, and
**the order is decided by the second: the duration, cheapest first**. A test that has never failed
and takes a long time is placed last, systematically, on every job, by construction.

0.2.0 has no such element. It sorts by `(-score, key)`: alphabetical, which carries no information
about cost and therefore no bias against slow tests.

This also explains why ADR 0018's `cold-free` step found nothing. It set `cold_time_exponent=0`,
which removes the divisor from the **score**, and left the sort key untouched, so the cost ordering
survived the experiment meant to remove it. The step measured 0.692 against 0.691 and concluded the
divisor was not the cause. It could not have measured anything else.

## Decision

**This step explains, it does not select.** Its output is an answer to "what causes the property",
and a candidate that ships is a separate decision made later, under
[ADR 0033](0033-lrts-is-measured-once-under-a-rule-written-first.md)'s two conditions on held-out
data. Nothing here is allowed to become a release on its own.

**The tie-break becomes an option with three values**, and the default is what ships today, so no
published number moves:

- `cost`: duration then a hash of the job and the test. What the current ranking does.
- `hash`: the hash alone. The cost ordering is gone and nothing replaces it.
- `name`: the test's own name, which is what 0.2.0 does.

**The candidate set is fixed here and closed.** Each one isolates one difference between 0.2.0 and
the shipped ranking, and nothing is added after a result is seen:

1. the shipped ranking, as the reference;
2. it with `tie_break=hash`;
3. it with `tie_break=name`;
4. `latest-failure` with 0.2.0's two signals, `name*2.0` and `failure_rate*1.0`, which the study's
   vocabulary can already express;
5. the same with `tie_break=name`;
6. the window, at 50 builds, so the mechanical result above is in the record rather than in a note;
7. `testhunch-0.2.0` and `random`, as the two references that bound the slice.

**What counts as an explanation, fixed before running.** The gap to explain is the shipped ranking's
first-failure position minus 0.2.0's, on the same trials. A variant explains the property when it
closes **at least half** of that gap while staying within 0.005 of the shipped ranking on the primary
measure. Half is a coarse bar, chosen for being coarse: this step is meant to tell a cause from a
detail, not to rank near-equals.

**Explored on the training half of the development projects, chosen on the validation half**, the
split phase 6 introduced. The held-out projects are not touched, and LRTS is not touched at all.

## What this decision was made knowing

Three exploratory measurements were run on the training half before this ADR was written, and they
are why the candidate set looks as it does: the window does not fire; `name*2.0` added to
`latest-failure` moves the slice from 0.742 to 0.552 with the divisor and 0.554 without; and 0.2.0
still reaches 0.380, so the signals do not explain all of it. Three projects, 48 trials in the slice,
directional at best.

That is a degree of freedom, it is the fourth taken on these projects, and it is written here rather
than left implicit. What makes it defensible this time is that the hypothesis did not come from
those runs: it came from reading the sort key, and from LRTS confirming on data nobody had tuned on
that the property is real. A rule stated after three looks is still weaker than a rule stated after
none, and this is the last set this line of search gets.

## What it found

Run on the ten development projects, training half first, validation half second, 283 trials in the
slice. First-failure position, lower better; the gap to explain is the shipped ranking minus 0.2.0.

| Ranking | primary | first failure | share of the gap closed |
|---|---:|---:|---:|
| what testhunch ships | 0.861 | 0.632 | |
| it with `tie=hash` | 0.855 | 0.530 | 44% |
| it with `tie=name` | 0.853 | 0.523 | 47% |
| `latest-failure+name*2.0+failure_rate*1.0` | 0.840 | 0.472 | 69% |
| the same with `tie=name` | 0.840 | 0.468 | 70% |
| it with `window=50` | 0.861 | 0.628 | 2% |
| `latest-failure` | 0.825 | 0.618 | |
| testhunch 0.2.0 | 0.843 | 0.399 | |
| random | 0.603 | 0.447 | |

**No variant meets the bar this ADR fixed.** Closing half the gap costs more than 0.005 of the
primary measure in every case that manages it: `tie=name` closes 47% for 0.008, and 0.2.0's two
signals close 69% for 0.021. On the validation half alone the shares are higher, 51% and 81%, and
the costs are 0.012 and 0.014. The rule asked for one difference that explains the property nearly
for free, and there is none.

**The cause is nonetheless located, and it is two things rather than one.** The cost ordering in the
sort key is real and cheap: removing it buys 0.102 of position for 0.006 of the primary, which is
the best exchange rate this project has measured anywhere. 0.2.0's two signals buy more and cost
more. Together they account for most of the distance, and what remains between 0.468 and 0.399 is
still unexplained.

**The window explains nothing, now in the record rather than in a note.** 0.628 against 0.632, on
ten projects. It does not fire because these suites re-run every test in every build: the median age
of a test since its last run is one build.

## Consequences

If the tie-break is the cause, the repair is the cheapest this project has ever had in front of it:
a sort key, not a model, not a new signal, not a pipeline. It would also be an uncomfortable
finding, because the cost ordering it removes is where a real part of the primary measure comes
from, and the two slices would have to be weighed against each other with the numbers in hand.

If it is not the cause, the property stays unexplained after five attempts, and this ADR records
that the search stops rather than turning the wheel a sixth time. The next lever would be a signal
this dataset cannot carry, which is a different project.
