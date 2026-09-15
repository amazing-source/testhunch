# 0027: the objective is what shadow mode would have missed

Date: 2026-09-16

## Status

Accepted.

## Context

The service had nothing to say about itself. Whether it was up was a question answered by asking it,
and whether it was any *good* was a question answered by running a benchmark on a laptop.

The second one is the interesting one. A hosted test-prioritisation service can be perfectly healthy
by every ordinary measure, answering every request in milliseconds, and still be worthless, because
the rankings it serves miss the failures. Latency and uptime do not detect that. Nothing detects it
except the comparison testhunch already knows how to make: of the runs that went red, how many a
budget would still have caught.

## Decision

**The service level objective is the shadow miss rate**, not a latency or an uptime figure. Those
are alerts about the machine; this is the alert about the product. It fires when more than one red
build in ten would have been missed at half the test time, sustained for an hour.

**It is exposed as counts, and the rate is computed in the alert.** `testhunch_shadow_failing_runs`
and `testhunch_shadow_caught_runs`, per repository and per budget. A rate would hide how few runs it
came from, and this project's own history is nine tenths of the reason to care: on a test's first
failure the ranking is worse than random ([ADR 0018](0018-first-failures-are-a-guardrail-not-an-average.md)),
and a rate over three runs would fire on noise or, worse, look reassuring. The alert therefore
refuses to divide by fewer than twenty failing runs.

**The exposition is written by hand**, in the Prometheus text format, with no client library. The
format is a few lines of text, and a library's process-wide registry would have to be reset between
tests that each build their own application. What this process has served is counted in memory;
everything else is read from the database at scrape time, cached for thirty seconds, because the
database is the only thing that survives a deployment.

**Requests are labelled by their route template, never by the path requested.** A path is whatever
the caller typed, and one label per typo is how a metrics endpoint exhausts a process.

**`/metrics` is not public.** It names every repository the service knows. The API refuses it to
anything but the operator token, and Caddy does not proxy it at all: Prometheus reaches the API over
the internal network. Two locks, because the failure mode of exposing it is quiet.

**Alerts leave through SNS, signed by the instance role.** Alertmanager can send mail, but that
means an SMTP server and a password stored on the instance. SNS is already in the account, an email
subscription is free, and there is no secret to leak or rotate. As with the budget alert, no address
means nothing is created rather than something created deaf.

## Consequences

The one thing this service exists to do is now measured continuously, on real repositories, and says
so without being asked. That is a stronger claim than any benchmark run on a laptop, because it
cannot be run again until it looks better.

Prometheus, Alertmanager and node-exporter share the one instance, about 300 MB of it, and share the
data disk. Retention is capped by size as well as by time, so metrics can never be the reason the
history runs out of room.

The scrape reads the database, so a scrape interval much shorter than the cache would push load onto
Postgres for numbers that have not moved. Thirty seconds each is the pairing; changing one means
looking at the other.

The alert is per repository, and testhunch's own repository has never had a failing build, so it
will report zero failing runs and the objective will simply not apply to it. That is honest, and it
is also a reminder that the service is not yet measuring itself on anything.

Nothing yet alerts on a deployment that named an image the server did not manage to run
([ADR 0026](0026-a-deployment-names-an-image-it-does-not-run-a-command.md) leaves that open).
`testhunch_build_info` now makes it visible, which is the half of it that had to come first.
