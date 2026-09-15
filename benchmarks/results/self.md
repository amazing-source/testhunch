# testhunch on testhunch

Rebuilt from the `reports-python-3.14` artifact of every build of `main`, ranking before each
ingest exactly as the Action does. The history the real CI keeps lives in the Actions
cache, which cannot be downloaded, so this is a reconstruction: `python -m
benchmarks.selfci` makes it again, for as long as the artifacts have not expired.

**75 builds**, `22353083` to `79f51bd6`.

## It cannot measure its own ranking, and that is the finding

**0 of those builds had a failing test.** Shadow mode compares a ranking recorded
before a build against what the build then did; with no build that went red there is
nothing to compare, and every budget reports nothing caught because nothing was there to
catch.

This is not a measurement problem to work around. A repository whose suite has never
failed is a repository where test prioritisation cannot be validated, and that belongs on
the page whose subject is how well testhunch works. It is worse than neutral: the first
failure here would land in the regime where the ranking is worse than random
([ADR 0018](../../docs/adr/0018-first-failures-are-a-guardrail-not-an-average.md)),
because no test has ever failed, so nothing yet carries the signal the ranking reads.

## What a budget does here

Over the 10 most recent builds, at a budget of 25% of the expected test
time:

| Build | Tests ranked | Tests kept | Time kept | Budget used |
|---|---:|---:|---:|---:|
| `969282ae` | 394 | 393 | 22.8 s of 128.9 s | 71% |
| `b764122d` | 397 | 396 | 22.8 s of 125.2 s | 73% |
| `236e04c4` | 398 | 397 | 22.7 s of 125.3 s | 72% |
| `74853ac4` | 399 | 398 | 22.7 s of 122.5 s | 74% |
| `337b77eb` | 401 | 400 | 22.7 s of 126.4 s | 72% |
| `676ae917` | 401 | 400 | 22.7 s of 127.4 s | 71% |
| `ebf5d35b` | 403 | 402 | 22.7 s of 127.0 s | 72% |
| `b26e0fee` | 403 | 402 | 23.1 s of 127.2 s | 72% |
| `c731ceba` | 403 | 402 | 23.1 s of 128.2 s | 72% |
| `79f51bd6` | 403 | 402 | 23.0 s of 128.1 s | 72% |

The saving is real and large, and **none of it comes from prediction**. One test dominates
this suite's time, so the budget's whole effect is to leave that one test out. The
duration divisor does all the work, and anyone could have the same result by running that
test separately.

## The prefix rule truncates, and it is visible here

A time budget takes the longest prefix of the ranking that fits and stops at the first
test too expensive to fit
([ADR 0017](../../docs/adr/0017-a-budget-is-a-share-of-the-test-time.md)). When the slow
test's own file changes, the ranking lifts it near the top, it does not fit, and
**everything below it is cut with it**.

It happened in **1 of 74 builds**, counting every build whose cut spends
less than half of what its budget allows:

| Build | Tests kept | Time kept | Budget used |
|---|---:|---:|---:|
| `82bb02e7` | 9 of 383 | 0.2 s of 25.8 s allowed | 1% |

The rule is deliberate: the order is what the ranking promises, and packing the budget
better would run tests the ranking placed below ones it did not. But a build that spends
1% of its budget is not honouring an order, it is losing the budget. Whether to
keep filling after a test that does not fit changes the published budget tables, so it is
a decision to measure and record, not a quiet fix.
