# 0033: LRTS is measured once, under a rule written first

Date: 2026-09-16

## Status

Accepted. Opens the LRTS step. Written **before** a single prioritisation score has been computed on
that dataset, which is the point of it. Settles the question
[ADR 0018](0018-first-failures-are-a-guardrail-not-an-average.md) deliberately left open, in the
only way that does not fit a threshold to the data that answers it.

## Context

Everything this project knows about its own ranking comes from twenty RTPTorrent projects and four
harness projects. The ten development projects have now been looked at across four study phases,
three rejected candidate families and a learned model. They have earned no more freedom.

LRTS (Cheng et al., ISSTA 2024) is the external dataset: ten projects, 2020 to 2024, 108 366
test-suite runs over 34 645 CI builds, suites averaging 6.75 hours. It carries per-test-class
durations, which is the one thing our ranking cannot do without, and changed file paths per build,
which is what it consumes.

It is also the dataset that answers the question this project cares most about. On a test that has
never failed, testhunch places the failing test at 0.692 against random's 0.472: worse than
shuffling, on 283 jobs. ADR 0018 made that a guardrail and refused to say how much of the primary
measure a candidate may give up to clear it, because fixing that number from the 283 jobs that
raised the question would tune the rule on its own motivating cases. Phase 6 then measured the trade
rather than assuming it: roughly 0.03 of APFDc buys roughly 0.22 of first-failure position
([ADR 0031](0031-the-learned-model-does-not-ship-and-where-it-wins.md)). On 192 jobs, one model, one
set of hyperparameters.

An audit of the LRTS artifact and of its MIT code, carried out before this ADR, established what the
dataset can and cannot support. Its findings are the constraints below, and several of them change
what would otherwise have been written here.

## Decision

### LRTS is held out entirely, and forever

No tuning of any kind happens on it. No threshold, no weight, no feature, no candidate set is chosen
by looking at an LRTS number. There is no development half: the development projects are the
RTPTorrent ones, they already exist, and a second split would only invite a second round of
fitting.

This is stricter than [ADR 0013](0013-development-projects-tune-held-out-projects-measure.md) asks,
and it is the only choice that needs no size measure to justify itself and therefore cannot be bent.
A 5/5 split of ten projects in which Kafka is two thirds of the rows would decide nothing anyway.

Every replay of it writes a row in the ledger before it starts
([ADR 0016](0016-every-look-at-the-held-out-projects-is-recorded.md)), exactly as the RTPTorrent
held-out projects do.

### The rankings measured are fixed here, and the list is closed

Six, all of them already frozen when this ADR is written, none of them created for this step:

- the ranking testhunch ships, as of 0.5.0;
- `latest-failure`, the measured baseline of [ADR 0014](0014-the-ranking-study-measures-time-to-red-against-latest-failure.md);
- `random`, the bar of the guardrail;
- `testhunch-0.2.0`, the reference that still scores better than random on the slice;
- the learned model in its raw form, and in its `cold-learned` form (ADR 0031).

The learned model is included because the arbitration needs a candidate that actually trades one
measure for the other, and it is the only one measured so far that does. It was fitted on the
RTPTorrent training half and chosen on the validation half, months of work before this dataset was
touched; measuring it here changes nothing about how it was built.

Adding a seventh ranking after seeing these results would be the degree of freedom this ADR exists
to refuse.

### What is read, and what is deliberately not read

From the processed archive: `dataset.csv` for the metadata, and per suite run the class table's
`testclass`, `duration` and `outcome` columns.

**`last_outcome` is not read**, although it is right there. It is precomputed per project and stage
by start timestamp, without protecting ties or overlapping builds, and a class never seen before
gets the same `0` as a class that passed. **The artifact's own `first_failure` field is not read
either**, for the same reason: its history is indexed per stage and walked by start time with no
handling of overlap. Both would import someone else's definition of the thing this step measures.
Every history is rebuilt from `outcome`, backwards, by the same replay that handles RTPTorrent.

The two look-ahead leaks the audit found in the LRTS code are in files this step never opens: the
running duration mean of `extract_hist_features.py`, which writes a mean already containing the
current build's own duration, and the frequent-failure filter of `extract_filtered_test_result.py`,
which uses whole-period statistics. Neither `test_class_filterlabel.csv.zip` nor
`filtered_tests.json.gz` ships in the archive, so no row we consume was removed with knowledge of
the future.

### A build, its history, and what concurrency means here

A build is `(project, pr_name, build_id)`; a suite run adds `stage_id`. Builds are ordered by
`build_timestamp`, which is not enough on its own: the archive holds 211 groups of tied timestamps
and 29 980 builds whose execution interval overlaps another's.

**A build's admissible history is the builds that finished before it started**: `timestamp + duration
<= this build's timestamp`. Two builds that overlap in time cannot inform each other, because in the
real CI neither had the other's results when it was scheduled. Two builds are concurrent when they
share a project and a `build_head_sha` and their intervals intersect.

This is stricter than ordering by timestamp, and it is the definition the slice below depends on.

### The first-failure slice

A build joins the slice when at least one class fails in it that never failed in its admissible
history. Counted that way the slice holds **2 140 builds** over the ten projects, against 283 in the
current study. That count is a property of the dataset established by the audit, not a result, and
it is written here because feasibility had to be known before the work started: an order of
magnitude of one hundred would have meant LRTS cannot settle anything.

Per project it is thin where projects are small: 41 for Log4j 2, 46 for Karaf, 60 for ActiveMQ,
against 644 for Kafka. **No per-project claim is made on the slice.** The pooled estimate is what
this step produces, and its limits are stated with it.

### How the numbers are aggregated, and why never by row

Kafka is 68.5 million of the 104 million class-test rows. Pooling rows would publish a result
labelled "ten projects" that is a result about Kafka. **Every measure is computed per project, and
aggregated as the mean of the per-project values**, as ADR 0014 already does for RTPTorrent.

Inference is paired at build level and clustered: the bootstrap resamples projects, and within a
project it resamples PRs rather than builds, since several builds of one PR and several re-runs of
one SHA are not independent observations. 2 140 builds are not 2 140 independent facts and this
step will not treat them as such.

### The arbitration: the formula is fixed here, the number is measured there

This is what ADR 0018 left open and what the roadmap says to settle after LRTS, not before. Both
are satisfied by fixing the **form** of the rule now and letting the measurement supply its value.

A candidate ships when both hold:

1. **It clears the guardrail**: its first-failure position is not worse than random, with the 95%
   interval of the difference not above zero. The bar is random because random needs no data to
   justify, which is the whole argument of ADR 0018.
2. **It stays above the baseline it was built to beat**: its primary measure, on the same data, is
   strictly higher than `latest-failure`'s, with the 95% interval of that difference above zero.

The second is the arbitration. It says a candidate may give up primary measure, as much as clearing
the guardrail costs, **down to but not below the simplest thing this project claims to beat**. A
ranking that buys the guardrail by falling under `latest-failure` has spent the reason it exists.
The bound is therefore not a number chosen by anyone: it is a row in the result table, computed on
the same replay as everything else.

Among candidates that satisfy both, the one with the highest primary measure is preferred. The
current shipped ranking is a candidate like the others, and it fails condition 1 today.

**Nothing ships out of this step by itself.** A ranking that satisfies both conditions on LRTS has
earned a proposal, not a release: it would still have to be exported as data the package can read,
and to be replayed on RTPTorrent so that two datasets are on the record rather than one.

### What this dataset cannot answer, said before it is asked

**Confirmed failures cannot be told from single ones.** `rerunFailures` and `flakyFailures` exist in
the raw Jenkins reports and the LRTS parser drops them, so the separation of
[ADR 0008](0008-failures-are-confirmed-by-retries.md) is unavailable here. The measures below are
reported without it, and no claim about flakiness is made from this dataset.

**226 builds hit GitHub's 300-file cap** on a comparison, and 8 more return no path at all. Their
changed-file lists are lower bounds, not facts. Those builds keep every other measure and their
changed files are treated as **unknown**, which is what this project does everywhere with a path it
does not know: unknown is not empty, and a guessed file list would be the one thing CLAUDE.md
forbids more plainly than any other.

**The published build count is wrong in the paper's own README**: it says 32 199, the distributed
`dataset.csv` holds 34 645 distinct builds. Our pages cite our own count against the archive's hash,
the way the RTPTorrent pages cite a CRC-32 per file.

**The processed archive carries no licence.** It is used to measure and never vendored into this
repository. What is published is our numbers and the code that produced them; the raw Zenodo reports
are CC-BY-4.0 and are cited as the source, and reconstructing the archive from them alone is not
possible anyway, since the timestamps, SHAs and changed paths come from the Jenkins and GitHub APIs
and some of those builds no longer exist.

## Consequences

The step costs one night of machine time and about 21 GB of disk: 104 million class-test rows, of
which Kafka is two thirds, streamed one project at a time. That estimate comes from a measurement,
not a guess: `SonarSource@sonarqube` put 13.86 million rows through the real ingest and ranking in 53
minutes on the machine this will run on.

**Kafka is kept**, and it is kept for a reason that had to be decided before seeing anything: it
holds 644 of the 2 140 builds of the slice that decides. The problem it poses is statistical
dominance, not cost, and the aggregation rule above is the answer to that. Dropping the largest
project of an external validation set after seeing its results is exactly the move this ADR is
built to prevent, so the decision is recorded here instead.

The first-failure slice of this dataset is defined by us, not by its authors. That is a difference
from every other number we will publish beside theirs, and the page says so where the figures are.

If the shipped ranking clears nothing and no candidate satisfies both conditions, that is the
result, and it is published exactly as phase 6's failure was. A dataset that has been looked at once
cannot be looked at again for a better answer.
