# 006 — Prose skill sections are sliced by outcome, with a separate traceability audit unit

**Status:** proposed

## Context

Authoring a prose skill section (e.g. the write-loop section of
`emergent-contract-coding`, issue #9) under `large-task-slicing` raises two
decomposition questions: how to cut a prose deliverable into units, and where
requirement-clause traceability (each R clause mapping to exactly one
instruction/extension) belongs.

## Decision

1. Slice by outcome blocks (skeleton → main scenario → extensions → duties),
   not by requirement-list order; prose sections do not verify
   independently per clause, so coarsest-sufficient units win.
2. When the stated risk is "text reads as guidance rather than procedure",
   run the R-clause traceability audit as its own work unit with the
   clause→mapping table recorded in `findings.md`, rather than folding it
   into the last authoring unit — a distinct pass makes the mitigation
   visible.
3. No unit writes a test for skill behavior: verification of skill behavior
   is the manual scenario trial, per the repo's skill-testing carve-out;
   unit verifies are inspection and honestly labelled weak.

## Consequences

Authoring plans for prose deliverables get fewer, larger units and one extra
audit unit. Skill behavior stays unverified until the manual trial runs;
traceability is the only in-plan guarantee.

## Enforced by

procedure (plan authoring; no automated gate)
