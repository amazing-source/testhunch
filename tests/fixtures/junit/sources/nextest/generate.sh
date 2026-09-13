#!/bin/sh
# Regenerates tests/fixtures/junit/nextest.xml from this sample crate. From the repo root:
#   docker run --rm --hostname ci-runner -v "$PWD/tests/fixtures/junit:/fixtures" \
#     -w /fixtures/sources/nextest rust:1.97.1 sh generate.sh
# Check the report for hostnames and local paths before committing it.
set -eu

curl --proto '=https' --tlsv1.2 -LsSf https://get.nexte.st/0.9.144/linux \
  | tar zxf - -C "${CARGO_HOME:-$HOME/.cargo}/bin"

FLAKY_STATE_DIR=$(mktemp -d)
export FLAKY_STATE_DIR

# The ci profile retries failing tests up to twice (.config/nextest.toml): flaky_first_attempt
# passes on its retry, fails_on_purpose fails every attempt. Failures make nextest exit non-zero.
cargo nextest run --profile ci || true

cp target/nextest/ci/junit.xml /fixtures/nextest.xml
rm -rf target
