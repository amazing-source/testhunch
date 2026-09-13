#!/bin/sh
# Real Jest runs for tests/test_select_jest.py. From the repo root:
#   docker run --rm --hostname ci-runner -v "$PWD/tests/fixtures/select/jest:/src" -w /src \
#     node:24-slim sh run.sh full
#   ... sh run.sh selected   (after ignore-pattern.txt was written from left-out.txt)
set -eu
npm install --silent --no-audit --no-fund
node -e 'for (const p of ["jest", "jest-junit"]) console.log(p, require(`./node_modules/${p}/package.json`).version)'
export JEST_JUNIT_ADD_FILE_ATTRIBUTE=true
case "$1" in
  full) npx jest --ci --reporters=default --reporters=jest-junit || true; mv junit.xml full.xml ;;
  selected)
    npx jest --ci --reporters=default --reporters=jest-junit \
      --testPathIgnorePatterns "$(cat ignore-pattern.txt)" || true
    mv junit.xml selected.xml
    ;;
esac
rm -rf node_modules
