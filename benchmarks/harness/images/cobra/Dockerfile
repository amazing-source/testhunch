# spf13/cobra (docs/adr/0011). Not root: TestFailGenFishCompletionFile expects a read-only file
# to be unwritable, which root ignores.
FROM golang:1.27.1@sha256:f44f6e88636cfb311f9ebace870ded69d943f227bb3cb27d32ffd84ea18c43ea
RUN go install gotest.tools/gotestsum@v1.13.0 \
    && useradd --create-home runner \
    && mkdir /home/runner/.cache \
    && chown runner /home/runner/.cache
USER runner
WORKDIR /home/runner
# The image's Go, never a toolchain a go.mod would download: a commit needing another cannot be built.
ENV GOTOOLCHAIN=local GOMODCACHE=/home/runner/.cache/go-mod GOCACHE=/home/runner/.cache/go-build
