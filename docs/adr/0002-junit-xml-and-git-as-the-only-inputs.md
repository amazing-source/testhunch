# 2. JUnit XML and git are the only inputs

Date: 2026-09-13
Status: accepted

## Context

Test selection tools usually learn which tests cover which code by instrumenting the program
(coverage, bytecode agents) or by analysing its structure (import graphs, Bazel targets). Both
approaches are precise, but each works for one language or one build system, and instrumentation
slows the test run it is meant to speed up.

Almost every test runner can already write JUnit XML, and every CI job has the repository's
history.

## Decision

testhunch learns only from JUnit XML reports and `git diff`. It does not instrument, import or
parse the code under test.

## Consequences

- Works for any language and framework from day one, and adds nothing to test run time.
- It cannot know that a test exercises a file unless history shows it: new code and new tests
  start with weak signal (the "cold start" problem), which the baseline softens with path matching.
- JUnit XML has no specification. Each dialect must be handled from real reports, never from
  documentation alone, so every supported runner has a real fixture in `tests/fixtures/junit`.
- Test identity has to be normalized across dialects, and renames look like one test disappearing
  and another appearing until identity tracking improves.
