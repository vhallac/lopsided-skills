# 015 — Benchmark reviews are generated against offline, locally materialized targets

**Status:** accepted

## Context

The `review-change` benchmark harness could score a `review-report/1` with two
independent judges, but could not generate a report from a benchmark task. The
skill resolves a target from a merge/pull request or a work item, so a
benchmark task has to be presented as one of those. The alternatives considered
were: (1) build a local repo per task and present a file-backed work item;
(2) open one clean PR per task in a fork or eval org; (3) review the upstream
benchmark PRs directly.

## Decision

Reviews are generated against **option 1: a per-task offline local target**.
`materialize.py` clones the task's source at the pinned base/head, checks out
the head on a branch, and writes a file-backed work item naming the branch and
commit. `run_review.py` runs `pi --print` with `review-change` loaded against
that target and maps the emitted report through the benchmark adapter.
`review-change` itself is unchanged: its work-item target already accepts a
caller-named tracking system plus a caller-named branch/commit.

The materialized clone is the only network use; there is no forge or tracker
write. The benchmark forks (`vhallac/ReviewBench`,
`vhallac/code-review-benchmark`) remain the durable references for golden data
and judge code.

## Consequences

- Every run is reproducible against pinned commits and hermetic: no forge
  state, no external PR sprawl, no training-leakage surface.
- Option 2 was rejected as external sprawl (one repo per task/repo); option 3
  as reviewing merged/closed upstream PRs whose threads carry other reviewers'
  rounds and whose repositories are the leakage surface the benchmark exists
  to avoid.
- Because the scoring solution (forks, adapters, judge wiring, oracle controls)
  was built and validated before this problem instance existed, the ordering is
  **solution before problem**: option 1 constructs the problems to fit the
  validated solution. A generation failure therefore reads as a review-engine
  failure rather than a format failure; the materializer and runner exist to
  close that gap.
- The harness remains dev tooling under `evals/`, not a `skills/` target
  extension; `skills/review-change/targets/work-item.md` already covers the
  shape.
