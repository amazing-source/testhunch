# 14. The ranking study measures time to red against the latest failure

Date: 2026-09-14
Status: accepted

## Context

The roadmap's phase 4 looks for the best simple ranking, starting from the tests that failed most
recently (ADR 0013 fixes where it is tuned and where it is measured). Three things have to be
settled before any candidate is compared with another.

**How to replay many candidates.** The published replay (ADR 0010) ranks every job through the SQL
store, as users run testhunch: SonarQube alone took 53 minutes. A study that tries a dozen
candidates per step cannot replay every project once per candidate.

**What to measure.** Phase 3 counted tests: a budget ran a share of the known tests. What a user
saves is time, and what the build needs is to turn red soon. The literature has the measure:
APFDc, the cost-cognizant APFD of Elbaum, Malishevsky and Rothermel (ICSE 2001), which Luo et al.
(TSE 2019, [arXiv:1806.09774](https://arxiv.org/abs/1806.09774), equation 3) write, with every
fault equally severe, as

    APFDc = sum over faults i of (t[TF_i] + ... + t[n] - t[TF_i] / 2) / (m * (t[1] + ... + t[n]))

where t are the tests' durations in the order run, TF_i the position of the first test detecting
fault i, and m the number of faults. Cheng et al. (ISSTA 2024, sections 4.1 and 4.2) evaluate it
under two mappings of failures to faults: every failure of a run is the same fault (FFMapS), or each
is its own (FFMapU); they add 0.001 s to every duration, since Maven reports 0.000 s below a
millisecond.

**Which reference.** RTPTorrent's own baseline (Mattis et al., MSR 2020, section 4) gives test t in
build n the priority `P_t(n) = α F_t(n) + (1 - α) P_t(n - 1)`, `P(0) = 0`, where `F_t(n)` is 1 when t
failed in build n, over past builds that were not running concurrently, with α = 0.8. Its schedules
have a mean APFD of 0.847 on the jobs they cover (benchmarks/results).

The development projects' durations, read from their files: 7 class results of titan have an
unknown duration, in 4 failing jobs; 620 502 of buck's 783 990 class results last
0 seconds; Go reports durations to the hundredth of a second (benchmarks/results).

## Decision

**A study engine (`benchmarks/study`) replays each project once per step and ranks every failing
job with every candidate** of that step, from per-test state updated build by build. A build is a
group of concurrent jobs on RTPTorrent (ADR 0010) and a commit on the harness; the state only
holds the builds before the job's build. The engine also orders jobs as testhunch 0.2.0 does, by
calling `testhunch.prioritize.rank` on the history of the same 50-run window the store reads; a test
checks, job by job on the RTPTorrent extract, that this order equals the product replay's. The
version the study keeps is then implemented in testhunch itself, and its held-out numbers come from
the product replay (ADR 0010), which must give the engine's numbers.

**Rules every candidate shares.** A test is known once it has passed or failed in an earlier build;
unknown tests run first, in the job's own order (ADR 0006, 0010). Ties are broken by the SHA-256 of
the job and the test key, not by the key, whose alphabetical order could follow where failures are.
Known means any earlier build, not a window: 0.2.0's window of 50 runs is a cost of the store, and
limiting history is measured as a candidate of its own.

**The reference is the latest failure**: RTPTorrent's priority with α = 0.8, counted in builds, a
test failing in any job of a build. Since α > 0.5, the newest failure always outweighs all older
ones together, so the order is the tests that failed most recently first, older failures breaking
ties; the engine sorts by that directly, which floating point would lose after a few hundred
builds.

**Measures, per failing job.** A job fails when a test fails that is not flaky (ADR 0006); a
detected mutant is a failing job whose failures are the tests that detected it (ADR 0012).
Durations are the job's own, plus 1 ms each, as Cheng et al. add 0.001 s; a job with a test of
unknown duration is left out of every time measure, and counted.

- **Primary: APFDc with a job's failures mapped to one fault (FFMapS)**, which is 1 minus the share
  of the job's test time spent before its first failing test, counting half of that test: how soon
  the build turns red. 1 is at once; a single failing test placed at random scores 0.5 on average.
- Secondary: APFDc with each failing test its own fault (FFMapU, the mapping of Cheng et al.'s
  table 8); APFD, comparable with the RTPTorrent authors' schedules; the share of failing jobs whose
  first failing test ends within 10%, 25% and 50% of the test time; and within 10%, 25% and 50% of
  the known tests, as the shadow mode counts (ADR 0006).

**When a candidate beats another.** A candidate's score on a project is its mean primary measure over
the project's failing jobs, the same jobs for every candidate: jobs ranked from an empty history and
jobs with an unknown duration are left out for all. Candidate B beats A when, over the 10 RTPTorrent
development projects, the mean of the per-project differences B − A has a 95% percentile bootstrap
interval (10 000 resamples of the projects, with replacement, seed 0) entirely above 0, B scores
higher on at least 6 of the 10 projects, **and** the mean difference is at least 0.005 (amended, see
below). click and cobra are reported but do not decide: two
projects, whose failures are almost all mutants, which favour name matching (benchmarks/results).

**The study adds one signal at a time.** Before a step runs, its candidates are committed: the
current version with each remaining signal added, each signal with at most three values of its
parameter. Of the candidates that beat the current version, the one with the largest mean
difference becomes the current version, committed with its numbers. The study stops when no
candidate beats the current version. Then the held-out projects are replayed once (ADR 0013), for
the latest failure, testhunch 0.2.0 and every version kept.

## Consequences

- Every candidate is compared on the same jobs, from the same history, with the same ties.
- The bootstrap over 10 projects is a coarse interval; the rule of 6 projects out of 10 guards
  against a mean carried by one project, and the held-out replay is the real test.
- On buck most classes take 0 s and every one gets 1 ms, so its time measures rest on the few
  classes with a duration. On cobra almost every duration is 0, so APFDc stays close to APFD.
- The engine computes again what the store computes. The equivalence test for 0.2.0, and the
  product replay of the version kept, keep the two from drifting apart.
- If the kept version needs more history than a window of runs, the store will have to keep
  per-test aggregates, which the hosted service will have to account for.

## Amendment, 2026-09-14, after step 2

As first written, the rule had no minimum effect. In step 2, adding verdict changes with weight 0.1
to `latest-failure+time^1.0` met both conditions with a mean difference of +0.0002: the interval was
[+0.00001, +0.00046], and "higher on 6 projects" counted differences of a few hundred-thousandths.
Such a change does not make any build red sooner in a way anyone would notice, and keeping it would
add a signal to compute and explain for nothing. A candidate must now also improve the mean by at
least 0.005, half a percent of a job's test time. The threshold only makes the rule stricter, and it
changes no other verdict of steps 1 and 2: every other candidate that met both conditions improved
the mean by at least 0.014.
