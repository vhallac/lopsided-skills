# review-change benchmark harness

Evaluation harness for the `review-change` skill against public code-review
benchmarks. This is dev tooling for the skill, deliberately kept out of
`skills/`; other skills get their own `evals/<skill>/` tree.

The harness establishes that a `review-report/1` produced by `review-change`
can be scored by two independent judges, and now generates that report from a
benchmark task offline (see *Review generation* below). It does not change the
`review-change` skill.

## Benchmarks

| Benchmark | Upstream | Fork | Judge |
| --- | --- | --- | --- |
| ReviewBench (GitHub) | `review-bench/ReviewBench` | `vhallac/ReviewBench` | `npm run judge` (TS) |
| martian offline (50 PRs / 5 repos) | `withmartian/code-review-benchmark` | `vhallac/code-review-benchmark` | `step3_judge_comments` (Python) |

Both are MIT. `kodustech/codereviewbench` was evaluated and rejected: it is a
Next.js leaderboard site with precomputed scorecards, no judge/runner, no
license.

## What the spike proved

The adapters in `adapters/` translate in both directions:

- **Benchmark golden → `review-report/1`** (`golden_to_report.py`,
  `martian_golden_to_report.py`). This is the *oracle* control: replay the
  benchmark's own findings as a report and confirm the judge recovers them.
  It isolates adapter fidelity from review quality.
- **`review-report/1` → benchmark candidate** (`to_reviewbench.py`,
  `to_martian.py`). A report's findings become the candidate shape each judge
  consumes.

Oracle results (`results/`):

| Benchmark | Task | Result |
| --- | --- | --- |
| ReviewBench | `axios/axios#10836` (2 TPs) | grounded P=100% / R=100%, 0 errors |
| martian | `calcom/cal.com#14943` (2 comments) | P=R=F1=100%, 0 errors |

An oracle result is a **format/semantic-fidelity control, not a quality
measure** of the review engine. Both judges are LLM-based; scores vary with the
judge model and the oracle uses a non-leaderboard judge.

### Not promoted

Non-oracle candidate runs were produced during the spike but are withheld: the
candidate content's file anchors do not correspond to the task identity recorded
in the same JSON. They cannot be published as benchmark data. The oracle
controls and adapters are unaffected.

The following redacted excerpt was recorded during the spike session
(2026-11-04) so the withholding decision stays auditable. A ReviewBench
candidate envelope for `axios/axios#10836` carries findings anchored in an
unrelated project, `pi-ext/agent-mailbox/*.mjs`:

```json
{
  "pr": {
    "repo": "https://github.com/axios/axios",
    "pr_number": 10836,
    "base": "90ae1993e0eaa39ccccbaa25957bb23cc5676df7",
    "head": "9cd706ccb836c581371c760b4c6a5c61c656ea1f"
  },
  "agent": "review-change-real",
  "findings": [
    {
      "file": "pi-ext/agent-mailbox/settle.mjs",
      "message": "settle-on-shutdown sweep aborts on a cancelled request; …"
    }
  ]
}
```

The martian candidate for `calcom/cal.com#14943` from the same session carries the
same seven findings under the cal.com PR URL, anchored in the same
`pi-ext/agent-mailbox/*.mjs` files. In both runs the task identity in the
envelope and the anchored source tree never match, so neither can be scored
against that task's golden.

## Layout

```
adapters/
  reportlib.py                  review-report/1 -> findings (shared parser)
  golden_to_report.py           ReviewBench golden -> oracle report
  martian_golden_to_report.py   martian golden -> oracle report
  to_reviewbench.py             report -> ReviewBench candidate JSON
  to_martian.py                 report -> martian candidates.json + benchmark_data.json
materialize.py                  task manifest -> local repo at base/head + work item
run_review.py                   materialized task -> pi --print -> report -> adapter -> judge score
score.py                        candidate + judge -> run/score.json (bench-score/1)
tasklib.py                      review-task/1 manifest loader
task-manifest.md                manifest format
test_bench.py                   tests for materialize + runner
results/
  oracle-axios.md               oracle report for axios/axios#10836
  oracle-martian.md             oracle report for calcom/cal.com#14943
  rb-candidate-axios.json       candidate the ReviewBench judge scored
  rb-oracle-results.json        ReviewBench judge output (micro/macro)
  rb-oracle-results.details.json
```

## Reproducing the oracle

The adapter takes the golden file as input, so both benchmarks must be cloned
first (the forks above are the durable references).

ReviewBench:

```sh
python adapters/golden_to_report.py <clone>/golden/axios_axios_10836-9cd706cc.json \
    --out /tmp/oracle-axios.md
python adapters/to_reviewbench.py /tmp/oracle-axios.md \
    --repo https://github.com/axios/axios --pr 10836 \
    --base 90ae1993e0eaa39ccccbaa25957bb23cc5676df7 \
    --head 9cd706ccb836c581371c760b4c6a5c61c656ea1f \
    --out /tmp/findings.json
# then: npm run judge -- --candidate /tmp/findings ...
```

martian:

```sh
python adapters/martian_golden_to_report.py \
    <clone>/offline/golden_comments/cal_dot_com.json \
    https://github.com/calcom/cal.com/pull/14943 --out /tmp/oracle-martian.md
python adapters/to_martian.py /tmp/oracle-martian.md \
    --pr-url https://github.com/calcom/cal.com/pull/14943 \
    --model-dir /tmp/results/review-change-oracle \
    --out-data /tmp/results/review-change-oracle/benchmark_data.json \
    --golden-comments <clone>/offline/golden_comments/cal_dot_com.json
# then: uv run python -m code_review_benchmark.step3_judge_comments
```

`reportlib.py` uses `yaml`; run with `uv run --with pyyaml python …` or an
environment that has PyYAML.

## Review generation (option 1 — offline local target)

The spike scored reports but never generated one from a task. Generation is now
handled by two scripts here; `review-change` is unchanged.

`materialize.py` turns a `review-task/1` manifest (`task-manifest.md`) into a
hermetic local target: it clones the task's source at the pinned base/head,
checks out the head on a branch, and writes a file-backed work item naming the
branch and commit. The clone is the only network use; there is no forge,
tracker, or work-item write.

`run_review.py` invokes a fresh `pi --print` round with `review-change` loaded
against that target, captures the emitted `review-report/1`, and hands it to the
manifest's benchmark adapter.

```sh
# 1. describe the task (see task-manifest.md for every field)
cat > /tmp/task.json <<'JSON'
{ "schema": "review-task/1", "id": "axios-10836",
  "source": "https://github.com/review-bench/axios_axios",
  "base": "90ae19...", "head": "9cd706...",
  "work_item": {"title": "axios/axios#10836"},
  "judge": {"adapter": "reviewbench", "repo": "https://github.com/axios/axios",
            "pr": 10836, "base": "90ae19...", "head": "9cd706..."} }
JSON
# 2. build the local target
python materialize.py --manifest /tmp/task.json --out /tmp/axios-10836
# 3. generate + map a review (needs the pi binary)
python run_review.py --task /tmp/axios-10836
# -> /tmp/axios-10836/run/review.md  and  run/candidate.json

# replay an existing report through the adapter, without pi:
uv run --with pyyaml python run_review.py --task /tmp/axios-10836 \
    --report /tmp/axios-10836/run/review.md
```

Why option 1 and not the alternatives: (2) opens one real PR per task/repo —
external sprawl; (3) reviews the upstream PRs, which are merged/closed and are
the training-leakage surface the benchmark exists to avoid. Option 1 keeps the
target resolvable by `review-change` and every run reproducible against pinned
commits. `materialize.py` never contacts a forge; only the clone uses the
network.

Tests: `uv run --with pytest --with pyyaml python -m pytest evals/review-change/bench -q`.

## Scoring

With `judge.clone`, `judge.command`, and `judge.model` set in the manifest (all
three together, or none — see `task-manifest.md`), `run_review.py` runs the
judge after adaptation, so one command emits the report, the candidate, and the
score:

```sh
python run_review.py --task /tmp/axios-10836
# -> run/review.md, run/candidate.json, run/score.json
```

The final stdout document is a JSON summary with `report`, `candidate`,
`score`, and `status`; a non-`scored` status makes the runner exit 1.

To re-score an existing candidate (e.g. after pinning a different judge
model), invoke `score.py` directly — it reuses the manifest's judge config and
does not touch pi or the adapters:

```sh
python score.py --task /tmp/axios-10836 \
    --candidate /tmp/axios-10836/run/candidate.json
# -> /tmp/axios-10836/run/score.json
```

### `bench-score/1`

Every score is written to `run/score.json` in the `bench-score/1` schema:

| Field | Meaning |
| --- | --- |
| `schema` | Always `bench-score/1`. |
| `benchmark` | `reviewbench` or `martian` (the manifest's `judge.adapter`). |
| `task` | Manifest `id`. |
| `status` | See failure semantics below. |
| `judge_model` | The `judge.model` pin used for this score. |
| `base`, `head` | The `judge.base`/`judge.head` SHAs the judge validates the candidate against (`null` if absent, as for martian). |
| `precision`, `recall`, `f1` | Normalized metrics; `null` unless `status` is `scored`. |
| `raw_output` | Path to the judge's raw output file (`run/judge-output.json`). |
| `candidate` | Path to the candidate that was scored. |

ReviewBench metrics come from the judge's `macro.overall` grounded
precision/recall; martian metrics from `step3_judge_comments` per-PR
precision/recall aggregation. `f1` is computed from the two when both are
present and their sum is non-zero.

### Failure semantics

Failure statuses are recorded as data, never synthesized as a score of 0:

- `generation-failed` — the candidate artifact is missing or not valid JSON.
- `empty-candidate` — the candidate has a `findings` key holding an empty list
  (a review that legitimately found nothing; not an error).
- `judge-failed` — the judge command exited non-zero, produced no output, or
  its output could not be normalized; the raw output (or stderr) is preserved
  at `raw_output` for audit.
- `scored` — the judge produced parseable output and metrics were normalized.

When `run_review.py` drives the scoring, any non-`scored` status propagates to
the summary and a non-zero exit code, so automation can tell an unscored run
from a successful one.

### Reproducibility

A score is pinned to `judge.model` (recorded in every `bench-score/1` as
`judge_model`) and to the explicit `judge.base`/`judge.head` SHAs the judge
checks the candidate against. Re-running with the same manifest, the same
fork clone, and the same model pin reproduces the scoring pipeline; only the
review content itself varies between runs.

## Solution before problem

This harness was built solution-first: **solution before problem**. The record
says so plainly.

The spike built and validated the *solution* — the benchmark forks, the in/out
adapters, the judge wiring, the oracle controls — before any *problem instance*
existed. It could replay a benchmark's golden findings as a report and prove the
judge recovered them (the oracle runs in `results/`), but it had no way to
produce a report from a real task: no benchmark task had been materialized as a
reviewable target. The scoring machinery was exercised; the thing it was meant
to score was not.

Option 1 constructs the problems to fit the already-validated solution:
materialize a task at its pinned base/head, present it as a work item, run the
review engine, and feed the result to the adapters the spike proved. The
ordering is solution → problem, not problem → solution. The value is that the
adapters and judge mapping are fixed by existing oracle evidence, so a
generation failure reads as a review-engine failure rather than a format
failure. The cost is that the problem instances were not selected for the
solution's strengths; the materializer and runner exist to close exactly that
gap. This note is descriptive, not a retro-justification.
