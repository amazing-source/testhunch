# 12. Mutants seed faults in the lines a commit changed

Date: 2026-09-14
Status: accepted

## Context

The harness (ADR 0011) runs the real history of a default branch, where almost every commit passes:
there are few failures for a ranking to catch, and the ones there are tend to be flaky. A
benchmark of test selection needs changes that break tests, many of them, whose breaking tests
are known.

Mutation analysis makes such changes: small syntactic changes to the code, called mutants, and a
test detects a mutant when it fails on it. Just et al. (*Are Mutants a Valid Substitute for Real
Faults in Software Testing?*, FSE 2014, [doi:10.1145/2635868.2635929](https://doi.org/10.1145/2635868.2635929))
studied 357 real faults of 5 programs: mutant detection is correlated with real fault detection,
with statistical significance and independently of code coverage, and 73% of the real faults
are coupled to mutants. They used the Major framework's operators (replace constants, replace
operators, modify branch conditions, delete statements) and mutated only the classes the bug fix
modified.

## Decision

**Mutants are made from the lines a commit added or changed**, in files that are not tests
(`src/click/**.py` for click; `.go` files other than `_test.go` for cobra), as `git diff` of the
commit with its first parent lists them. A fault in those lines is a fault the commit could have
introduced, and the change a ranking sees is the commit's own change, whose files contain the
mutant.

**Each mutant changes one token**, with one replacement per operator:

| Kind | Replacements |
|---|---|
| relational operator | `==` and `!=`, `<` and `>=`, `>` and `<=`, each into the other |
| logical operator | `and` and `or` (Python), `&&` and `\|\|` (Go) |
| boolean constant | `True` and `False` (Python), `true` and `false` (Go) |
| arithmetic operator | `+` and `-` |
| integer constant | `n` into `n + 1` |

Tokens in strings and comments are never mutated. Statement deletion is left out: deleting a line
in Python breaks indentation more often than it makes a fault.

**Up to 3 mutants per commit**: every candidate token is shuffled by a random generator seeded by
the project and the commit, so the order is the same on every collection and independent of what
the tests do, and candidates are taken in that order until 3 compile. A Python candidate must pass
`compile()` before it is sent; a Go candidate must pass `go build ./...` in the container, since
only a build knows that a `+` joins strings. At most 10 candidates are sent per commit; those tried
that did not build are counted as not compiled.

**Mutants run after the commit's own suite, in the same container**: the mutated file replaces the
original, the suite runs once, the original is put back. A test detects a mutant when it fails on
the mutant and passed on the commit on every attempt. A mutant no test detects survived: it is
counted, not evaluated, since there is nothing to catch (some are equivalent to the original).

**Mutants never enter the history.** A detected mutant is evaluated against the ranking of its
commit, made from the history before the commit and the commit's changed files: at each budget of
ADR 0006, whether a detecting test runs (per change) and how many of the detecting tests run (per
test).

## Consequences

- Mutants stand in for faults a commit could have introduced, not for the faults projects had:
  results on them are reported apart from the real history's, and next to it.
- One-token mutants in changed lines are close to their tests by construction when tests are named
  after the code they test; testhunch's name matching may do better on them than on real faults.
  The report says so, and the real history's results stay the reference where it has failures.
- Three mutants and one suite run each add seconds per commit, not minutes: the suites are fast.
