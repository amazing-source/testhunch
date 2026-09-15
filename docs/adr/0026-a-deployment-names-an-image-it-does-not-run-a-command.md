# 0026: a deployment names an image, it does not run a command

Date: 2026-09-16

## Status

Accepted. Builds on [ADR 0025](0025-main-is-deployable-without-a-release.md), which made every
commit of `main` into something a server can pull.

## Context

Deploying was a person at a laptop with Terraform, AWS credentials and the Windows quirks that come
with both. That is the wrong place for a routine, frequent act, and it is the reason the server sat
two features behind `main` for a day.

The roadmap asked for continuous deployment to a staging stack with manual promotion. That is the
right shape for a service with users and a second team. Here it would mean a second instance and a
second disk, roughly doubling a bill paid out of a fixed credit, to test a commit whose only
remaining unknown is the suite that has just passed on it. The cost is certain and the information
is not.

The obvious mechanism, `terraform apply` from CI, brings two problems that are bigger than the one
it solves. The state lives on the maintainer's machine and holds the generated secrets in clear, so
CI would need it moved and guarded first. And an identity that can run `terraform apply` can do
anything this account can do, from a workflow file that any future change can edit.

## Decision

**The image is a parameter, not a line of Terraform.** `/testhunch/image` in Parameter Store names
what the server runs. Terraform creates it with a first value and then ignores it, so a deployment
and an `apply` can never disagree about what is running. The startup script reads it at every boot,
which is what makes a replaced instance come back on the deployed image rather than on whatever the
configuration last said.

**A deployment names an image and triggers one fixed command.** `/usr/local/bin/testhunch-deploy`
lives on the instance, written by the startup script and reviewed in this repository. The SSM
document that runs it takes no argument. So the deploying identity holds exactly two powers: write
that one parameter, and run that one document on that one instance. It cannot open a shell, read a
secret, or touch anything else in the account.

**GitHub authenticates by OIDC, with no stored key.** The role trusts one repository and one
branch, `refs/heads/main`. There is no access key to leak, rotate or find in a log.

**One environment, deployed on every green commit of `main`.** The gate is the suite: the image job
needs every other job, and the deploy job needs the image job. Rolling back is writing the previous
`sha-` into the parameter and running the document again, which is the same two calls.

## Consequences

Putting `main` on the server is a merge. Nothing is typed, and no credential leaves the account.

Infrastructure changes are still applied by hand, with local state. That is deliberate: they are
rare, they are the changes that can destroy the disk, and they are exactly what should not be
reachable from a workflow file. Continuous deployment here means the application, not the account.

There is no staging environment, and this ADR is where that was decided rather than forgotten. If
the service ever gets a second user, the argument above stops holding: the cost of a bad deploy
becomes somebody else's, and the second stack becomes worth its price.

The deployment restarts the stack, so the API is unavailable for a few seconds on every merge to
`main`. With one instance there is no way around that short of running two, which is the staging
argument again.

A deploy can still fail after the image is named: the parameter then points at something the server
is not running, and the next boot would pick it up. The command fails loudly, and the fix is to name
the previous image again. Nothing detects it on its own.
