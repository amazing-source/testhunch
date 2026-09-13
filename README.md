# testhunch

[![CI](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml/badge.svg)](https://github.com/amazing-source/testhunch/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**testhunch learns from your CI history which tests a change is likely to break, and runs those first.**

It reads the JUnit XML reports your test runner already produces, plus `git diff`, so it works with
any language and any framework: pytest, Jest, Vitest, Go, JUnit, cargo-nextest, and anything else
that writes JUnit XML.

> **Status: pre-alpha.** The data pipeline (ingest, storage, flaky and failing test reports) and a
> simple, explainable baseline ranking work today. The learned model and the public benchmark that
> proves how well it works are on the [roadmap](ROADMAP.md). No accuracy claim is made until that
> benchmark exists.

## Why

CI runs every test on every push, whatever changed. As a suite grows, that means long waits,
large bills, and flaky failures that force full reruns.

Learning from test history which tests matter for a change is proven at scale: Meta's
[Predictive Test Selection](https://arxiv.org/abs/1810.05286) halved the cost of testing while
still catching over 99.9% of faulty changes. But today that capability is:

| Available as | The catch |
|---|---|
| Internal systems at large companies | Not released |
| Commercial services (Develocity, CloudBees Smart Tests, Datadog) | Paid, often tied to a build tool, and accuracy claims cannot be checked |
| Bazel-based selection | Requires migrating the whole build to Bazel |
| Open-source plugins | One language each, and mostly static analysis rather than learning from history |

testhunch aims to be the open, language-agnostic version, and to **prove its own accuracy in
public**: every number it reports comes with how it was measured, and a shadow mode records
what it *would* have skipped before it is ever trusted to skip anything.

## How it works

```mermaid
flowchart LR
    CI["CI job<br/>runs tests"] -->|JUnit XML + git diff| Ingest
    subgraph testhunch
        Ingest["parse &amp; normalize<br/>(any framework)"] --> Store[("history<br/>SQLite or Postgres")]
        Store --> Report["flaky / slow /<br/>failing report"]
        Store --> Rank["rank tests<br/>for a change"]
    end
    Rank -->|ordered test list + reasons| CI
```

1. After your test job, `testhunch ingest` records every test's outcome for that commit, along with
   the files that changed.
2. `testhunch report` shows flaky tests (passed *and* failed on the same commit), slow tests and
   failing tests.
3. `testhunch prioritize` ranks tests for the files you changed, and says why each one ranks where
   it does.

## Quick start

```bash
# In a git repository, after running your tests with JUnit output:
uvx --from git+https://github.com/amazing-source/testhunch testhunch ingest junit.xml
uvx --from git+https://github.com/amazing-source/testhunch testhunch report
uvx --from git+https://github.com/amazing-source/testhunch testhunch prioritize --base origin/main
```

History is kept in `.testhunch/history.db` (SQLite) unless you point `--db` or
`TESTHUNCH_DATABASE_URL` somewhere else, such as `postgresql://user@host/db`.

Real output, from two runs of the pytest sample in [`tests/fixtures`](tests/fixtures/junit):

```text
$ testhunch prioritize --changed src/sample/parametrized.py --limit 3
   1.  4.000  tests.test_sample::test_parametrized[2]  (matches changed file parametrized; failed in the latest run; failed 2 of 2 runs)
   2.  2.000  tests.test_sample::test_errors_in_setup  (failed in the latest run; failed 2 of 2 runs)
   3.  2.000  tests.test_sample::test_errors_in_teardown  (failed in the latest run; failed 2 of 2 runs)
```

### Getting JUnit XML out of your test runner

| Runner | Command |
|---|---|
| pytest | `pytest --junitxml=junit.xml` |
| Vitest | `vitest run --reporter=junit --outputFile=junit.xml` |
| Jest | `jest --reporters=default --reporters=jest-junit` (set `JEST_JUNIT_ADD_FILE_ATTRIBUTE=true`) |
| Go | `gotestsum --junitfile junit.xml` |

### In GitHub Actions

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0 # testhunch needs history to diff against the base branch
- run: pytest --junitxml=junit.xml
- if: ${{ !cancelled() }}
  run: uvx --from git+https://github.com/amazing-source/testhunch testhunch ingest junit.xml --base origin/main
```

A local SQLite file does not survive between CI runs, so for real use in CI point
`TESTHUNCH_DATABASE_URL` at Postgres, or upload to a self-hosted API (below).

### Self-hosting the API

```bash
docker compose up --build        # Postgres, migrations, then the API on :8000
curl http://localhost:8000/readyz
```

| Endpoint | Purpose |
|---|---|
| `POST /v1/runs` | Upload reports: multipart `reports` files plus `metadata` JSON (`repo`, `commit_sha`, optional `branch`, `base_sha`, `changes`) |
| `GET /v1/report?repo=owner/name` | Flaky, slowest and failing tests |
| `POST /v1/prioritize` | Ranked tests for `repo` and `changed_paths` |
| `GET /healthz`, `GET /readyz` | Liveness, and readiness including the database |

Set `TESTHUNCH_API_TOKEN` to require `Authorization: Bearer <token>` on `/v1`. Without a token
the API is open, which is only acceptable on your own machine.

## Development

```bash
uv sync --all-extras
uv run pytest                       # SQLite contract tests; Postgres ones are skipped
uv run ruff check . && uv run ruff format --check . && uv run mypy

# Run the storage contract tests against Postgres too:
docker compose up -d postgres
TESTHUNCH_TEST_POSTGRES_URL=postgresql://testhunch:testhunch@localhost:5432/testhunch uv run pytest
```

Design decisions are recorded in [`docs/adr`](docs/adr). The storage layer is one SQL
implementation run against both SQLite and Postgres, and every storage test runs against both.

## License

[Apache-2.0](LICENSE)
