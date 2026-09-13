#!/bin/sh
# Real Vitest runs for tests/test_select_vitest.py. From the repo root:
#   docker run --rm --hostname ci-runner -v "$PWD/tests/fixtures/select/vitest:/src" -w /src node:24-slim sh run.sh full
#   ... sh run.sh selected   (after test-name-pattern.txt was written from left-out.txt)
set -eu
npm install --silent --no-audit --no-fund
case "$1" in
  full)
    # Run the files to list tests: static parsing lists test.each under its template name.
    npx vitest list --json=vitest-list.json --no-static-parse
    npx vitest run --reporter=junit --outputFile=full.xml || true
    ;;
  selected)
    npx vitest run --reporter=junit --outputFile=selected.xml -t "$(cat test-name-pattern.txt)" || true
    ;;
esac
rm -rf node_modules
