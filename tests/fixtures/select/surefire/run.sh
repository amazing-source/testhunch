#!/bin/sh
# Real Maven Surefire runs for tests/test_select_surefire.py. From the repo root:
#   docker run --rm -v "$PWD/tests/fixtures/select/surefire:/src" -w /src \
#     maven:3.9.16-eclipse-temurin-21 sh run.sh full
#   ... sh run.sh selected   (after exclusions.txt was written from left-out.txt)
# Retries are off so that every test runs exactly once.
set -eu
run() {
  rm -rf target/surefire-reports
  mvn --batch-mode --quiet test -Dsurefire.rerunFailingTestsCount=0 -Dmaven.test.failure.ignore=true "$@" || true
  rm -rf "$out" && mkdir "$out" && cp target/surefire-reports/TEST-*.xml "$out"/
}
case "$1" in
  full) out=full; run ;;
  selected) out=selected; run "-Dtest=$(cat exclusions.txt)" ;;
esac
rm -rf target
