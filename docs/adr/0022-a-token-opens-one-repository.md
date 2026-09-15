# 0022: a token opens one repository, and is minted off the wire

Date: 2026-09-15

## Status

Accepted. Answers the debt [ADR 0021](0021-the-api-answers-on-one-public-name.md) took on.

## Context

Until now the hosted API had exactly one token, read from `TESTHUNCH_API_TOKEN`. It opened
everything, and it could not be revoked for one client without being revoked for all of them. That
was tolerable while the only way in was an SSM tunnel. ADR 0021 put the API on the public internet,
where that single token became the only thing between anyone and the whole database, and the first
client to receive it was going to be a GitHub Actions secret.

A secret handed to CI is a secret handed to every job, every workflow file, and everyone who can
change one. It should be worth as little as possible.

## Decision

A token opens one repository. Tokens live in `api_tokens`, one row per token, holding the
repository, a label, the dates, and **only the SHA-256 of the token**. A token is 32 random bytes
from `secrets.token_urlsafe`, so there is nothing to guess and no reason for a slow hash; hashing is
there so that a database that leaks does not hand over working keys.

**Tokens are minted by the CLI, against the database, never through the API.** `testhunch token
create --repo owner/name` prints the secret once and stores only its hash. There is deliberately no
endpoint that creates a token: minting requires access to the server, so no sequence of HTTP
requests, with any token, can produce a new one or widen an existing one.

The operator token from the environment still opens every repository. It is the break-glass key and
the way an empty configuration keeps meaning "open, local development only", exactly as before.

A request that presents nothing, an unknown token, or a revoked one gets **401**. A request that
presents a valid token for another repository gets **403**, because those are different facts and
saying so costs nothing: the caller already knows their own token.

Authentication sits at the router, so a route added later is closed even if its author forgets;
each route then names the repository it touches, and that is what scoping checks.

## Consequences

The CI secret is now worth one repository's history, and revoking it breaks nothing else. That is
what makes it safe to put in GitHub Actions.

A stolen scoped token still reads and writes that repository's history until someone revokes it.
There is no expiry, no rotation helper, and no audit of what a token did. Revocation is manual and
immediate: `testhunch token revoke <id>`, and the next request fails.

Every authenticated request that is not the operator's costs one indexed lookup. At the traffic this
project will see, that is nothing; it would want a cache long before it wanted a different design.

The schema changes, so there is a migration for both databases under the same number, and the
contract tests in `tests/test_store.py` run on both, as the project requires.
