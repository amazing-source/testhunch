# Roadmap

Each phase is useful on its own. Nothing is claimed about accuracy until phase 3 can measure it.

## Phase 1: record test history (foundation)

- [x] Parse JUnit XML from pytest, Vitest and Jest, tested against real reports from each
- [x] Normalize test identity across dialects; collapse duplicates within a run
- [x] Refuse unsafe XML (entity expansion, external references)
- [x] Read changed files from git, including renames
- [x] One SQL storage layer for SQLite and Postgres, with a contract test suite run on both
- [x] Idempotent ingest: the same reports for the same commit are recorded once
- [x] Reports: flaky (pass and fail on one commit), slowest, failing
- [x] CLI: `ingest`, `report`, `prioritize`, `migrate`
- [x] HTTP API with bearer token auth, health and readiness checks
- [x] Docker image, compose stack, CI (lint, types, tests on 3.12 to 3.14 against Postgres, container smoke test), release to GHCR
- [ ] Real fixtures for Go (gotestsum), JUnit/Surefire (including `flakyFailure` and `rerunFailure`), cargo-nextest
- [ ] Record in-run retries as flakiness evidence (needs those real retry fixtures first)
- [ ] Batch the per-test upserts in `ingest` (one statement per test today)
- [ ] Publish to PyPI with trusted publishing

## Phase 2: use it in CI

- [ ] A GitHub Action wrapping `ingest` and `prioritize`
- [ ] **Shadow mode**: run every test, record what would have been skipped, report the real miss rate
- [ ] Emit selections in each runner's format (`pytest -k`, Jest/Vitest file lists, `go test -run`)
- [ ] Dogfood: testhunch's own CI keeps its history in the hosted API

## Phase 3: the public benchmark

- [ ] Harness that checks out open-source projects at historical commits in pinned containers and runs their suites
- [ ] Mutation testing to create realistic failures where history has too few
- [ ] Evaluate on RTPTorrent, split by time so no model sees the future
- [ ] Report both per-test recall and per-change recall, with test time saved
- [ ] Publish results, including where testhunch does badly

## Phase 4: hosted service

- [ ] Terraform for a single server: Postgres, API, worker, object storage for raw reports
- [ ] Continuous deployment from `main` to staging, manual promotion to production
- [ ] Metrics (Prometheus) and alerts, including shadow-mode miss rate as a service level objective
- [ ] Per-repository tokens instead of one shared token
- [ ] Partition `results` by time once it is large enough to need it

## Phase 5: a learned model

- [ ] Features: co-failure of files and tests, path distance, recency, flakiness, test duration
- [ ] Gradient boosted trees compared against the phase 1 baseline on the phase 3 benchmark
- [ ] Ship it only if it beats the baseline; publish the comparison either way
- [ ] Explore defect-prediction signals (historically bug-prone files) as an extra feature

## References

- Machalica et al., *Predictive Test Selection*, ICSE-SEIP 2019 (Meta)
- Mattis et al., *RTPTorrent: An Open-source Dataset for Evaluating Regression Test Prioritization*, MSR 2020
- *Predicting test failures induced by software defects*, Journal of Systems and Software, 2025 (Nokia 5G)
