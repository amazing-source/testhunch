# 10. The benchmark replays RTPTorrent in build order

Date: 2026-09-13
Status: accepted

## Context

No accuracy or time-saving number may be published without the measurement behind it. The first
measurement uses RTPTorrent (Mattis et al., MSR 2020, [doi:10.5281/zenodo.4046180](https://doi.org/10.5281/zenodo.4046180),
version 1.1, CC-BY-4.0), because its data already exists: real Travis CI builds of 20 Java projects.

What the dataset contains, read from its files and readme rather than assumed:

- `<project>.csv`: for each Travis job and each test **class**, its position in the run, duration in
  seconds, and counts of test methods run, failed, errored and skipped. There is no per-method result.
- `<project>-patches.csv`: the files changed by each commit. `tr_all_built_commits.csv`: the commits
  of each job, an n:m relation (a job can build several commits).
- `baseline/<project>@<strategy>.csv`: the authors' schedules (untreated, random, recently-failed,
  two file × test failure matrices, and the optimal schedule in hindsight), with build numbers. They
  cover only jobs with failures, and not all of them (62 of LittleProxy's 77 failing jobs).
- The readme warns: "concurrent jobs of the same build share the same build ID. For prioritization
  studies, only builds that finished before this build should be used to inform the scheduling".

Measured on LittleProxy and HikariCP: job ids increase with build numbers on every job that has a
build number; 13.3% and 7.9% of jobs have a failing test class; 235 of their 2 243 jobs have no commit
in `tr_all_built_commits.csv`.

## Decision

**Replay each project in job id order**, with the real ingest, ranking and shadow evaluation code
and a fresh store, so that the benchmark measures what users run.

**Jobs that may have run concurrently are ranked before any of them is recorded.** Build ids exist
only for failing jobs, so jobs are grouped instead: consecutive jobs that build the same set of
commits form a group. Every job of a group is ranked from the history before the group, then the
group's results are ingested. Grouping more than a real build would only hide information from the
ranking, never leak it.

**Each job becomes a run**, one result per test class: failed when a method failed, errored when a
method errored and none failed, skipped when every method was skipped, passed otherwise. Negative
durations (a runner defect the authors report) are unknown, not zero. There are no retries in the
data, so no failure is confirmed (ADR 0008), and flaky failures cannot be told apart.

**Changed files are the union of the job's commits' patches.** A job without a commit mapping has
unknown changed files, not an empty change: it is ranked without them and counted in the report.

**Metrics, per project, for budgets of 10%, 25% and 50% of the known test classes** (ADR 0006): how
many failing jobs would still have failed (change recall), how many failing test classes would have
run (test recall), and the share of test classes and of test time run. Jobs ranked from an empty
history are reported apart, since every test is unknown and runs. APFD, the metric of the RTPTorrent
paper, is computed for the same jobs as the authors' schedules, so testhunch's ranking is compared
with theirs job for job.

**Only the files a project needs are downloaded**, by HTTP range requests on the published archive;
each file's CRC-32 from the archive is checked when it is read.

## Consequences

- Results are class-level, Java, from Travis CI build logs the paper dates "from 2007 to 2016", and
  not de-flaked: they say how testhunch's ranking does on this data, not how it does elsewhere.
- Every project's numbers are published, including the ones where testhunch does badly.
- The harness of real projects (method level, other languages) and mutation testing remain needed to
  go beyond these limits.
