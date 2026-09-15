# 0023: the server keeps the ranking it served

Date: 2026-09-16

## Status

Accepted. Closes the gap left open by
[ADR 0021](0021-the-api-answers-on-one-public-name.md) and named in the documentation since.

## Context

Shadow mode measures what skipping tests would have missed by comparing a ranking recorded before a
run with the results of that run (ADR 0006). Both halves have to live in the same database.

When `ingest --api` appeared, only one half moved. `prioritize --record` still ranked from the local
database and recorded there, while the run went to the server. The two never met, so a job using the
hosted service got no shadow report at all, and worse, it ranked from a local history that a hosted
client does not have: on a fresh runner, an empty one.

## Decision

`prioritize --api` asks the server to rank. The server ranks from its own history, and with
`record` it keeps what it just served, pinned to the newest run its history stopped at.

**The client never uploads a ranking.** It could have: rank locally, post the result, let the server
store it. That would let any client record a ranking the server never made, and a shadow report is
only worth reading if nobody could have written the prediction after seeing the outcome. Having the
server record what it served makes that impossible by construction rather than by policy.

`POST /v1/prioritize` now answers with an object, `{ranked, total, prediction_id}`, where it used to
answer with a bare list. `total` is every ranked test and `ranked` only those a `limit` kept, so a
caller asking for the top twenty still knows how many there were, which is what a job summary says.
This is a breaking change to a `/v1` route, made while the only client is this repository and the
package is pre-alpha; it would not be acceptable later.

Recording needs the commit the ranking is for, and refuses with 422 without it: a ranking that does
not say what it predicts cannot be compared with anything. An empty history records nothing and says
so, rather than storing a prediction about no tests.

## Consequences

The hosted path now has both halves, so shadow mode works through it. The report itself is still
read from the database: `testhunch shadow` has no `--api`, so a hosted user cannot yet print what a
budget would have missed. That is the next piece, and it is a read, which makes it simple.

A scoped token records only for its own repository, because the check that refuses another
repository runs before the recording, like every other route.

One more round trip before the tests run, and the ranking now depends on the server being up. A job
that cannot reach it fails at that step instead of ranking from a stale local history, which is the
right failure: a ranking from an empty database is worse than none.
