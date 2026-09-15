# 0028: testhunch measures itself, and publishes that it cannot

Date: 2026-09-16

## Status

Accepted.

## Context

Every number this project publishes comes from other people's repositories: twenty Java projects
from RTPTorrent, four projects replayed commit by commit. None of them comes from the one repository
whose history is fully known, fully reproducible, and under this project's own control.

Running testhunch on testhunch was the obvious check, and the result was not the one that was hoped
for. Across every build of `main`, **no test has ever failed**. So shadow mode has nothing to
compare: it evaluates a recorded ranking against a build that went red, and there has been no red
build. The tool cannot demonstrate on its own repository the one thing it exists to do.

The tempting responses are all bad. Leaving the measurement unpublished hides a fact that a reader
would want. Seeding a failure on purpose measures a fault chosen by the person being graded. Quoting
the time saving without the caveat claims a prediction that did not happen: the saving here is one
slow test being left out by the duration divisor, and anyone could have it by running that test
separately.

## Decision

**The measurement is published, including the part that says it cannot measure anything.**
`benchmarks/results/self.md` opens on the zero, not on the time saving. A page about how well
testhunch works is the right place for a repository where testhunch cannot be shown to work.

**It is generated, not written.** `python -m benchmarks.selfci` downloads the JUnit artifact of
every build of `main`, replays them in order, ranks before each ingest exactly as the Action does,
and writes the page. Every figure on it is the output of that replay, so it cannot drift from the
prose the way hand-written numbers did before the audit of PRs #64 to #67.

**The history is reconstructed from artifacts, and the page says so.** The history the real CI keeps
lives in the Actions cache, which cannot be downloaded. Artifacts expire after fourteen days, so the
window this can cover shrinks unless the reports are kept; `collect` keeps what it downloads.

**It ranks with the whole commit hash.** The ranking is seeded with the commit to break ties
([ADR 0009](0009-learning-runs-keep-measuring-while-skipping.md)), so an abbreviated hash would produce a
different order from the one CI actually ran, and the page would describe a replay of nothing.

**No ledger row.** The held-out ledger records looks at the held-out *projects*
([ADR 0016](0016-every-look-at-the-held-out-projects-is-recorded.md)). This reads none of them, and
tunes nothing: adding rows for it would dilute the count that makes the ledger a check.

## Consequences

The project's own page is the weakest result it publishes, and it is published anyway. That is the
point of it.

The reconstruction is not the CI's own database, and cannot be: a difference between them would not
be visible. Uploading the history as an artifact would close that gap and is not done.

The page also exposes what the budget really does here, and what the prefix rule costs: one build in
seventy-four spends a hundredth of its budget because the slow test's own file changed, was lifted
near the top, did not fit, and took everything below it with it. That measurement is what makes the
budget-packing question a decision with evidence rather than an opinion.

Every future failure in this repository will be a first failure, the regime where the ranking is
worse than random ([ADR 0018](0018-first-failures-are-a-guardrail-not-an-average.md)). So the first
red build here will not flatter the tool either, and that is worth expecting rather than explaining
afterwards.
