#!/bin/sh
# Real go test / gotestsum runs for tests/test_select_go.py. From the repo root:
#   docker run --rm -v "$PWD/tests/fixtures/select/go:/src" -w /src golang:1.27.1 sh run.sh list
#   ... sh run.sh full
#   ... sh run.sh selected   (after skip-pattern.txt was written by the test's generator)
set -eu
go install gotest.tools/gotestsum@v1.13.0
export PATH="$PATH:$(go env GOPATH)/bin"
case "$1" in
  list) go test -list '.*' ./... > go-test-list.txt ;;
  full) gotestsum --junitfile full.xml -- -count=1 ./... ;;
  selected) gotestsum --junitfile selected.xml -- -count=1 ./... -skip "$(cat skip-pattern.txt)" ;;
esac
