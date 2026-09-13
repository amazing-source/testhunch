# 7. Selections leave out known, low-ranked tests

Date: 2026-09-13
Status: accepted, extended by [0009](0009-learning-runs-keep-measuring-while-skipping.md)

## Context

To save time, a CI job has to hand the test runner a selection. The obvious form is a list of the
tests to run (`pytest -k`, a list of files, `go test -run`). But testhunch only knows tests that
already have results: a list of tests to run would silently leave out every test added since, which
are among the most likely to fail. Shadow mode (ADR 0006) already assumes the opposite, that a test
the ranking does not know always runs.

Every runner names tests differently, and testhunch only sees the names in JUnit XML. A filter that
matches more than intended skips tests nobody chose to skip.

## Decision

**A selection is a list of tests to leave out.** `testhunch select --budget 25%` ranks the known
tests as `prioritize` does and leaves out those below the budget. The budget is cut exactly as in
shadow mode, so the shadow report measures what the selection does. Everything else runs, new tests
included. With no history, nothing is left out.

**A test is only left out when the runner's filter targets that test and nothing else.** Where a
runner cannot express that, the test runs. Each runner's output is verified by running the real
runner and reading its JUnit report back through testhunch, like the dialect fixtures.

**pytest:** a plugin shipped with testhunch, loaded explicitly (`-p testhunch.pytest_plugin`),
deselects the collected items whose key is listed. It computes each item's key the way pytest's
JUnit XML writer does (node id to classname, including `--junitprefix`), so a key matches exactly
the test it was recorded for, without guessing file paths.

**Go:** `select --runner go` prints one pattern for `go test -skip`. Go splits it on top-level `|`
into alternatives and on `/` into one regexp per subtest level, and applies it to every package of
the run (`src/testing/match.go` in Go 1.27.1; checked with real runs in
`tests/fixtures/select/go`). A known test is left out only when:

- its top-level name exists in its own package alone, according to `go test -list '.*' ./...` run
  on the code under test, because `-skip` would also skip a same-named test elsewhere;
- none of its known subtests is kept, because leaving a test out leaves its subtests out;
- no `_test.go` file changed in a directory named like its package, because a subtest added there
  would be left out with its parent. A changed test file at the module root turns skipping off.

The pattern is printed without a line ending: `"$(...)"` strips `\n` but not the `\r` of a Windows
line ending, which would stick to the last alternative and stop it matching.

**Maven Surefire:** `select --runner surefire` prints a `-Dtest` value such as
`!com.example.shop.CartTest#sumsPrices,!com.example.shop.FlakyTest#failsOnFirstAttempt`. Checked
with real Surefire 3.6.0 and JUnit 6.1.3 runs (`tests/fixtures/select/surefire`): exclusions alone
run every other test; the fully qualified class name aims at one class, where a simple name also
matched a same-named class in another package; method names match exactly; `#method` leaves out
every invocation of a parameterized method and `#method[2]` leaves out nothing. A known test is left
out only when:

- its report name is a Java method name (a phrased `@DisplayName` is not);
- every known test with the same class and method name is left out, covering all invocations of a
  parameterized method and all overloads;
- the source file of its class (the outer class for `Outer$Inner`) did not change, because an
  invocation added there would be left out with the others.

`-Dtest` overrides the `includes` and `excludes` of the build (Surefire's own documentation), so a
project that excludes some tests in its `pom.xml` would run them.

**cargo-nextest:** `select --runner nextest` prints a filterset for `cargo nextest run -E`, such as
`not ((binary_id(=shop) & test(=tests::sums_prices)) | ...)`. The equality matcher (`=`) is exact,
where the defaults would match more (glob for binary ids, "contains" for test names), and the DSL
reference asks programs building expressions to always give a matcher prefix. Checked with real
cargo-nextest 0.9.144 runs (`tests/fixtures/select/nextest`), including tests of the same name in
another binary. A nextest key cannot be split back into binary id and test name, because both may
contain `::`, so the binary id is the suite recorded from the report's classname; a test whose
suite does not prefix its key is not aimed at. With nothing to leave out, the output is `all()`.

## Consequences

- New tests, renamed tests and tests testhunch never saw always run.
- A build that leaves tests out must not record its ranking for shadow mode: the tests it skipped
  have no results, so their failures cannot be counted and the report would look better than the
  truth. Shadow mode needs builds that run everything.
- Leaving tests out will miss failures. It is only safe with a full run behind it: skip on pull
  requests, and run the whole suite on the main branch after merging, so that anything a selection
  let through is caught there. Facebook's predictive test selection relies on the same safety net,
  a stage that runs all tests on master every few hours (Machalica et al., ICSE-SEIP 2019).
- Runners are added one at a time, each with a real run behind it.
