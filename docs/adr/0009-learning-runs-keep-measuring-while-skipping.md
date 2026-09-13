# 9. Learning runs keep measuring while tests are skipped

Date: 2026-09-13
Status: accepted

## Context

Shadow mode (ADR 0006) measures a ranking on builds that run every test. Once a project uses
`testhunch select` to skip tests, its builds no longer run everything, and ADR 0007 forbids
recording their rankings: the skipped tests have no results, so the report would look better than
the truth. Left alone, a project would stop measuring exactly when the measurement matters most,
and nobody would notice the ranking getting worse.

Facebook's predictive test selection solves the same problem with learning test runs: "We sample
independently a subset D′ ⊂ D such that |D′| ≪ |D| and schedule for each d ∈ D′ a learning test
run. During such run we exercise all test targets in DependentTests(d) and record their results",
sampling "close to a quarter of submitted code changes" (Machalica et al., ICSE-SEIP 2019,
section IV-C).

## Decision

**`testhunch select` makes a share of builds learning runs (`--learning-runs`, 25% by default).**
On a learning run it leaves nothing out and records the ranking for shadow mode. On every other
build it leaves tests out and records nothing. The rule of ADR 0007 is enforced by the tool rather
than left to each CI configuration.

**The draw is a hash of the repository and the commit**, compared with the share. The same commit
always gets the same answer, so every job of a build matrix agrees and a re-run build behaves the
same way. The draw does not depend on the change's content or ranking, so learning runs are a
sample independent of how risky a change looks.

`--learning-runs 0%` turns them off; `100%` makes every build a learning run, which is shadow mode.

## Consequences

- With the default, about one build in four runs the whole suite. That is the price of knowing
  what skipping costs; a project can lower it and read the shadow report's counts to see how much
  evidence it still gets.
- Shadow reports of projects that skip tests are estimates from a sample of builds, and say how
  many runs they are based on.
- A build forced to run everything (for example the main branch after merging, ADR 0007) is not a
  learning run unless it records its ranking, as `prioritize --record` does.
