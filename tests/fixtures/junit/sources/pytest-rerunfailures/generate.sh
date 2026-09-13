#!/bin/sh
# Regenerates tests/fixtures/junit/pytest-rerunfailures.xml from this sample. From the repo root:
#   docker run --rm --hostname ci-runner -v "$PWD/tests/fixtures/junit:/fixtures" \
#     -w /work python:3.14-slim sh /fixtures/sources/pytest-rerunfailures/generate.sh
# The tests are copied to /work so that no local path ends up in the report.
set -eu

pip install --quiet --root-user-action=ignore pytest==9.1.1 pytest-rerunfailures==16.6.1
cp -r /fixtures/sources/pytest-rerunfailures/tests /work/tests

FLAKY_STATE_DIR=$(mktemp -d)
export FLAKY_STATE_DIR

# Failed tests are rerun up to twice. Failures make pytest exit non-zero, which is expected here.
python -m pytest --reruns 2 -p no:cacheprovider --junitxml=/fixtures/pytest-rerunfailures.xml tests || true
