# 3. One SQL layer for SQLite and Postgres

Date: 2026-09-13
Status: accepted

## Context

testhunch runs in two shapes: a CLI on a laptop or CI runner, where requiring a database server
would stop anyone from trying it, and a hosted service with concurrent uploads, where SQLite's
single writer does not fit.

The options were an ORM or query builder (SQLAlchemy), two separate hand-written stores, or one
hand-written SQL layer with small per-database differences.

## Decision

- Queries are written once, in portable SQL, in `store/base.py`. They use `?` placeholders, which the
  Postgres store rewrites to `%s`.
- What cannot be portable lives in per-database files: schema migrations
  (`store/migrations/{sqlite,postgres}`), connection setup, transactions and locking.
- Migrations are numbered SQL files applied in one transaction by a small runner, tracked in a
  `schema_migrations` table. Both databases must have the same migration versions, which a test
  enforces.
- Every storage test runs against both databases (`tests/test_store.py`). CI fails, rather than
  skips, if the Postgres run is unavailable.

## Consequences

- The SQL stays visible and reviewable, which matters for a project whose queries define what
  "flaky" and "recent" mean.
- Queries must avoid a literal `?` or `%`, and database-specific features (Postgres partitioning,
  JSON operators) need care or a per-dialect query when they arrive.
- Read sessions are snapshot transactions on both databases (SQLite read transactions, Postgres
  `REPEATABLE READ`), so a multi-query read sees one consistent state.
- "Recent" means highest run id. SQLite uses `AUTOINCREMENT` so ids never go backwards. Postgres
  identity values are assigned at insert time, so two concurrent uploads may commit out of id order.
  This is acceptable for ranking and will be revisited if a use case needs strict ordering.
- If migrations become complex enough to need downgrades or generated diffs, adopting a migration
  tool is a new decision.
