#!/bin/sh
# Regenerates tests/fixtures/junit/surefire/ from this sample project. From the repo root:
#   docker run --rm --hostname ci-runner -v "$PWD/tests/fixtures/junit:/fixtures" \
#     -w /fixtures/sources/surefire maven:3.9.16-eclipse-temurin-21 sh generate.sh
# Check the reports for hostnames and local paths before committing them.
set -eu

# Failing tests are rerun up to twice: FlakyTest passes on its rerun, the others fail every time.
# Failing tests make Maven exit non-zero, which is expected here.
mvn --batch-mode --quiet -Dsurefire.rerunFailingTestsCount=2 test || true

rm -rf /fixtures/surefire
mkdir /fixtures/surefire
cp target/surefire-reports/TEST-*.xml /fixtures/surefire/
rm -rf target
