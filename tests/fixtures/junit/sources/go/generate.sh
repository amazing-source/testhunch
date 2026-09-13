#!/bin/sh
# Regenerates tests/fixtures/junit/gotestsum*.xml from this sample module. From the repo root:
#   docker run --rm -v "$PWD/tests/fixtures/junit:/fixtures" -w /fixtures/sources/go \
#     golang:1.27.1 sh generate.sh
# Check the reports for hostnames and local paths before committing them (these had none).
set -eu

go install gotest.tools/gotestsum@v1.13.0
export PATH="$PATH:$(go env GOPATH)/bin"

FLAKY_STATE_DIR=$(mktemp -d)
export FLAKY_STATE_DIR

# Every test runs once; failing tests make gotestsum exit non-zero, which is expected here.
gotestsum --junitfile /fixtures/gotestsum.xml -- ./... || true

# Failed tests are rerun up to twice: TestFlakyFirstAttempt passes on its rerun,
# TestTotalFailsOnPurpose and the failing subtest fail every attempt.
rm -f "$FLAKY_STATE_DIR/attempted"
gotestsum --junitfile /fixtures/gotestsum-rerun-fails.xml --rerun-fails=2 --packages ./... || true
