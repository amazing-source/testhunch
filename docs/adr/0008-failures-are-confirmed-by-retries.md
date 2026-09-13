# 8. Failures are confirmed by retries

Date: 2026-09-13
Status: accepted (amends [0005](0005-retries-within-a-run-are-flakiness-evidence.md))

## Context

A failure that happened once may be a real regression or a flaky test. Facebook's predictive test
selection only counts a test as failed when every retry failed, and measured what happens without
that step: a model evaluated on failures that were not de-flaked reported a test recall of about
0.9 when the real one was about 0.7, leaving three times as many failures unreported as expected
(Machalica et al., ICSE-SEIP 2019, sections V and VI-C). Shadow mode (ADR 0006) counts every failure
that is not flaky, so it has the same blind spot.

Runners report retries differently. From real reports in `tests/fixtures/junit`:

- Maven Surefire and cargo-nextest keep every attempt inside one `<testcase>`: `<rerunFailure>` or
  `<rerunError>` for each rerun that failed again, `<flakyFailure>` or `<flakyError>` for each
  failed attempt before a pass.
- gotestsum `--rerun-fails` repeats the `<testcase>`, one entry per attempt.
- pytest-rerunfailures also repeats the `<testcase>`, but writes every attempt that was rerun as an
  empty `<testcase>`, which reads as a pass; only the last attempt carries its outcome. Its
  `<testsuite tests="N">` counts tests, not attempts, so the suite holds more `<testcase>` elements
  than it declares. None of the other reports has that mismatch. Under ADR 0005 a test that failed
  three times therefore looked like "passed, passed, failed", and was wrongly marked flaky.

## Decision

**Every result records how many times the test ran in the run (`attempts`)**, when the report
shows it:

- Surefire and nextest: one, plus one per `rerunFailure`, `rerunError`, `flakyFailure` or
  `flakyError`.
- Repeated `<testcase>` entries: one per entry, added up when they are collapsed.
- In a `<testsuite>` that declares fewer tests than it has `<testcase>` elements, the entries of a
  repeated test before its last one are attempts that were rerun, so they failed. If all of them
  are empty, the entries become one result: the last entry's outcome, flaky if it passed. If any
  of them has an outcome, this reading does not apply and ADR 0005 does.

**A failure is confirmed when it failed on every attempt and there was more than one.** A failure
from a single attempt is unconfirmed: it may be flaky. Results recorded before `attempts` existed
have unknown attempts and are never counted as confirmed.

**Shadow mode reports confirmed failures next to all failures**: how many failing runs and failures
were confirmed, how many of those the ranking would have caught, and how many failures ran only
once, with the advice to turn retries on.

## Consequences

- Turning retries on makes shadow mode's numbers trustworthy; without retries they stay an upper
  bound on what is caught, and the report says so.
- A future learned model can train on confirmed failures only, as Facebook does.
- pytest-rerunfailures reports are read correctly, and would be misread by any tool that takes
  their `<testcase>` entries at face value.
