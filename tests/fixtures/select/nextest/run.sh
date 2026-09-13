#!/bin/sh
# Real cargo-nextest runs for tests/test_select_nextest.py. From the repo root:
#   docker run --rm -v "$PWD/tests/fixtures/select/nextest:/src" -w /src rust:1.97.1 sh run.sh full
#   ... sh run.sh selected   (after filterset.txt was written from left-out.txt)
# Retries are off and the flaky test is made to pass, so that every test runs exactly once.
set -eu
curl --proto '=https' --tlsv1.2 -LsSf https://get.nexte.st/0.9.144/linux | tar zxf - -C "${CARGO_HOME:-$HOME/.cargo}/bin"
FLAKY_STATE_DIR=$(mktemp -d)
touch "$FLAKY_STATE_DIR/attempted"
export FLAKY_STATE_DIR
case "$1" in
  full) cargo nextest run --profile ci --retries 0 --no-fail-fast || true; cp target/nextest/ci/junit.xml full.xml ;;
  selected) cargo nextest run --profile ci --retries 0 --no-fail-fast -E "$(cat filterset.txt)" || true; cp target/nextest/ci/junit.xml selected.xml ;;
esac
rm -rf target Cargo.lock
