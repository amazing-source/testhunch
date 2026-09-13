# 1. Record architecture decisions

Date: 2026-09-13
Status: accepted

## Context

testhunch's value depends on people trusting what it reports. That trust extends to how it is
built: a reader should be able to see why the code is shaped the way it is, what was considered,
and what was knowingly left for later.

## Decision

Significant decisions are recorded as short numbered documents in `docs/adr`, in the format
Michael Nygard described: context, decision, consequences. A decision that is replaced keeps its
file, with its status changed to "superseded by N".

## Consequences

Decisions are reviewable in pull requests like code. Writing one takes a few minutes and forces the
trade-off to be stated.
