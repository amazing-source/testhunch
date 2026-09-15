# 0025: main is deployable without a release

Date: 2026-09-16

## Status

Accepted. Corrects a consequence of [ADR 0020](0020-one-server-reached-only-through-ssm.md) that was
never argued for, only inherited.

## Context

The server runs a published image, which is right: the instance builds nothing, and what runs on it
can be named exactly. But the only workflow that published an image was `release.yml`, which fires
on a `vX.Y.Z` tag. So the only way to put a change on the server was to publish that change to
everyone, on PyPI, as a version.

That tied two decisions that have nothing to do with each other. A version number is a statement to
readers of the project: this is what you should install, these are the numbers the README quotes.
Deploying is a statement to nobody: it is how the maintainer's own server catches up with `main`.
Four versions exist, two of them cut on the same evening, and the second was cut because a server
needed a feature, not because anything had been decided about the project.

It also made the deployment fragile in the direction that matters. Any urgent fix on the server had
to travel through a release, which is the slowest and least reversible path in the project.

## Decision

`ci.yml` publishes `ghcr.io/<owner>/testhunch:main` and `:sha-<commit>` for every commit of `main`,
after every other job has passed. `release.yml` keeps the version tags, and keeps PyPI, which is its
real subject.

The image job **needs** the whole suite. A commit of `main` whose tests failed must not become
something a server can pull, and there is no reason to accept one: the build is the last step, not a
parallel one.

A deployment pins `sha-<commit>`, never `main`. The moving tag is there to say what `main` is right
now, for a person reading the registry; pinning it would mean `terraform plan` reports no change
while the server changes underneath. A variable validation refuses `:latest` and `:main` for exactly
that reason.

## Consequences

Versions go back to meaning what they should: a release is cut when something is worth telling users
about, not when a server needs a commit. The next release is not owed to anyone.

The registry gains one image per commit of `main`, which is the cost of the arrangement and a small
one. Nothing prunes them yet.

Continuous deployment now has something to deploy. Its whole content becomes "point the stack at a
`sha-` tag and apply", instead of "cut a release first".

The image of `main` is still `linux/amd64` only, since neither workflow passes a `platforms:` list.
Nothing here changes that.
