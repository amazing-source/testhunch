# 0032: the data is snapshotted, and the restore is untested

Date: 2026-09-16

## Status

Accepted. Completes [ADR 0024](0024-the-data-outlives-the-server.md), which kept the data across
instance replacements and said nothing about keeping it across mistakes.

## Context

ADR 0024 moved the Postgres data directory and Caddy's certificates onto their own EBS volume, so
that replacing the instance stopped destroying them. That fixed the failure this deployment
actually hit. It left the larger one untouched: **the volume itself**. A volume deleted by hand, a
filesystem corrupted by a forced detach, or a migration that drops the wrong thing takes the history
of every repository using the service, and there is no second copy anywhere.

Since 2026-09-16 the CI of testhunch sends its own history to this service, so the volume now holds
something a person would miss. The roadmap listed snapshots as the only real unmitigated risk left,
and this is that item.

## Decision

A **Data Lifecycle Manager** policy takes one snapshot of the data volume a day and keeps the last
seven. The policy targets the volume by its `Name` tag, read from the volume resource itself, so a
volume that Terraform replaces is still the one being snapshotted. Snapshots inherit the volume's
tags, because a snapshot nobody can identify is a snapshot nobody restores from.

**DLM rather than AWS Backup.** AWS Backup is the richer service: vaults, plans, selections, cross
region copies, a restore testing feature. All of that is worth having when there are many resources
and a compliance story. Here there is one volume. DLM expresses "snapshot this volume daily, keep
seven" in one resource and an IAM role, and it costs nothing of its own. The extra machinery would
be more surface to maintain than the thing it protects.

**Seven days, once a day.** The recovery point objective is therefore up to 24 hours of lost
history, which for a service whose input is CI runs means a handful of builds. Seven days is how
long a mistake has to go unnoticed before the last good copy ages out. Both numbers are variables;
neither was fitted to anything, and this ADR is the place to change them if a week ever proves
short.

## Consequences

**The restore has never been run.** A backup that has not been restored is a hypothesis, and calling
it a backup is the kind of claim this repository does not make elsewhere. What is verified is that
the policy exists, is enabled, and targets the volume. What is not verified is that a snapshot of a
running Postgres data directory comes back as a database that starts, which is the thing that
matters. A crash-consistent snapshot of a live Postgres volume is normally recoverable, since
Postgres replays its write-ahead log exactly as it would after a power cut, but "normally" is not a
measurement. Exercising a restore into a throwaway instance is the obvious next step and it is not
done here.

**It does not protect against everything.** A logical error is copied into the next snapshot as
faithfully as good data, so a bad migration is only recoverable while it is younger than the
retention. The account itself is a single point of failure: snapshots live in the same region and
the same account as the volume they protect. Neither is worth fixing today for a service with one
user, and both are written down rather than left to be discovered.

**The cost is small and not zero.** Snapshots are incremental after the first one and are billed per
gigabyte-month of changed blocks, on a volume of 20 GB that is mostly empty. It sits inside the
existing budget alarm, which fires on net cost after credits.
