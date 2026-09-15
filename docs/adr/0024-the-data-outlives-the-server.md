# 0024: the data outlives the server

Date: 2026-09-16

## Status

Accepted. Fixes the consequence [ADR 0021](0021-the-api-answers-on-one-public-name.md) accepted
knowingly and said would have to change.

## Context

Everything the server needs to start is in its user data, and changing user data replaces the
instance. Until now that took the Postgres volume with it. ADR 0021 wrote this down as tolerable
"while the database was empty", and it stayed tolerable exactly as long as that sentence was true.

It stopped being true on 2026-09-16, when testhunch's own CI began sending its history to the
service. Since then every change to the startup script is a data loss, which means the startup
script cannot be changed, which means the deployment cannot be maintained.

It cost something else too. Caddy keeps its certificate in the same kind of volume, so every
replacement asked Let's Encrypt for a new one. Let's Encrypt limits duplicate certificates per week,
and a few more redeployments would have run into it, leaving the API without a certificate for days.

## Decision

One EBS volume, its own Terraform resource, holding the Postgres data directory and Caddy's
certificates. Terraform detaches it, replaces the instance, and attaches it back.

The instance finds it by **elimination, not by name**: on Nitro, a volume requested as `/dev/sdf`
appears as some NVMe device, so the script waits for a disk that is not the root disk. It is
attached after the instance exists, so it is not there in the first seconds of boot, and the wait is
part of the design rather than a retry bolted on.

**It is formatted only when it holds no filesystem.** On every boot after the first, the volume
already carries the database, and `mkfs` is the one command that would destroy precisely what this
ADR exists to protect. The systemd unit also declares `RequiresMountsFor`, so the containers cannot
start before the mount and initialise a second, empty database beside the real one.

The attachment sets `skip_destroy`, because detaching a mounted filesystem from a running instance
either hangs or is forced, and forcing is how filesystems get corrupted. Termination releases the
volume on its own.

The volume sets `prevent_destroy`, and that guard earned itself within the hour. The first version
of this took the volume's availability zone from the instance, which made the volume depend on the
instance: replacing the instance planned to replace the volume too, undoing the whole point. The
plan refused rather than running, and the fix was to pin both to one subnet chosen once. Without the
guard, that mistake would have looked exactly like success.

## Consequences

The startup script can be changed again, which is what makes the deployment maintainable. The
certificate survives replacement, so redeploying no longer spends the weekly allowance.

**`terraform destroy` now fails** on the volume, deliberately: tearing down the stack asks for an
explicit gesture rather than a confirmation typed at midnight. The escape hatch is in
`infra/README.md`.

The data lives on one disk in one availability zone, with no snapshot and no backup. Losing the
volume loses the history, and this ADR does not address that; it only stops the routine, avoidable
loss. Scheduled snapshots are the obvious next step and are not here.

The tokens table lives in this database, so that last replacement also erased the token the CI had
been given, and the secret in GitHub pointed at nothing. Nothing failed loudly: the next build would
simply have been refused. Any change that resets this database now means minting the CI's token
again.

Applying this change replaces the instance one last time, with an empty new volume, so the runs
recorded before it are lost. There is no migration path from a volume that is about to be destroyed
to one that does not exist yet, and the history at that moment was a single run.
