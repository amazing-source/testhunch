# 16. Every look at the held-out projects is recorded

Date: 2026-09-14
Status: accepted

## Context

ADR 0013 splits the benchmark projects: the ranking is tuned on the development projects, and the
held-out projects only measure versions frozen beforehand. The `--held-out` flags enforce part of
it in code, and the study's entry point goes further: `--held-out` is refused on every tuning step,
so a tuning run cannot read a held-out project even when the flag is passed on purpose.

Those guards protect the program. They do not protect the person. Three things they miss:

- **The held-out numbers are published.** `benchmarks/results/study/held-out.md` is in the
  repository, and its numbers were copied into README.md. Whoever tunes the ranking next has read
  them. No flag prevents that, and no flag can.
- **Nothing counts the looks.** ADR 0013 asks for a version "committed and listed before the
  replay". Nothing checked it. Replaying the held-out projects, seeing a number, changing a weight
  and replaying again left no trace but the honesty of whoever wrote the commit message.
- **Phase 6 makes this worse.** A learned model is not only fitted by its training data; it is
  fitted by the person choosing its features and hyperparameters against a score. Compared against
  the held-out projects a few times, they stop being held out and become a validation set, and the
  published number stops meaning anything.

The project's claim is that its numbers can be trusted because of how they were measured. A rule
kept only by intention does not support that claim.

## Decision

**Every run that reads a held-out project appends a row to `benchmarks/results/held-out-log.md`**,
written by the benchmark commands themselves (`benchmarks/heldout.py`): the date, the commit, the
version, the command, what was replayed and which projects. The row is written **before** the
replay starts, so an interrupted run, or one whose numbers are thrown away, still leaves its trace.
Hiding a look means deleting a line that git history keeps.

The ledger is not a permission: it does not say a look was legitimate. It lets a reader count.
Several rows for the same version, with the ranking changed in between, mean the held-out projects
were used to tune, and the reader can say so without taking anyone's word for it.

**A held-out replay refuses to start unless the commit is frozen and public**: no uncommitted
change, and the commit already on a remote branch. ADR 0013's "committed and listed before the
replay" becomes a refusal instead of a promise, and the code behind a held-out number cannot be
edited after the number is seen.

**The development projects are split again, for phase 6**, by the same seedless rule of ADR 0013
applied once more: `benchmarks/split.py` derives five training projects (HikariCP,
deeplearning4j, dynjs, jetty.project, jOOQ) and five validation projects (Achilles, buck,
graylog2-server, okhttp, titan). A learned model fits on the first and chooses between its own
variants on the second, so that choosing a model is never a look at the held-out projects. Fixing
the rule now, before any model exists, is the point: later there would be a reason to prefer one
split over another.

**What no code can fix is written down instead.** The held-out numbers of every version measured so
far are public, so every future choice is made by someone who has seen them. The ledger makes the
looks countable; it does not make the reader of them forget. This limit belongs in the results, not
in a footnote: a version whose held-out row is not the first for its lineage is weaker evidence
than one measured once, and the results say which.

## Consequences

- A held-out replay from a dirty or unpushed checkout now fails. Long runs already start from a
  `git worktree` detached at `main`, which satisfies both checks.
- The ledger starts with the runs already in git history, entered by hand and marked as such; from
  now on the commands write their own rows.
- Collecting a harness project still needs no flag and writes no row: collection ranks nothing
  (ADR 0013).
- The RTPTorrent test extract, 80 jobs of the held-out LittleProxy, keeps testing how the dataset
  is read and how the product and the study engine agree on an order. It must never assert that one
  ranking measures better than another; that would be a look outside the ledger.
- Phase 6 trains on five projects instead of ten. That is the price of having somewhere to choose a
  model that is not the held-out set.
