# review-change benchmark harness

Evaluation harness for the `review-change` skill against public code-review
benchmarks. This is dev tooling for the skill, deliberately kept out of
`skills/`; other skills get their own `evals/<skill>/` tree.

The harness is a **spike**, not a finished pipeline. It establishes that a
`review-report/1` produced by `review-change` can be scored by two independent
judges. Producing the report from a benchmark task is still an open piece (see
*Review generation* below).

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

## Review generation (open)

The spike scored reports but never generated one from a task. `review-change`
resolves a target from a merge/pull request or a work item, so a benchmark task
must be presented as one of those.

What the benchmark offers:

- **ReviewBench** keeps a mirror per source repository
  (`review-bench/<owner>_<repo>`) holding each task's base and head commits.
  Each mirror also carries per-tool evaluation PRs whose base/head equal the
  task's (`axios_axios` has 50 such PRs, all the same task). Those PRs exist,
  but they are the benchmark's own runs and their comment threads carry other
  reviewers' rounds — unsuitable as clean targets.
- **martian** ships `step0_fork_prs.py`, which clones a source repo, rebuilds
  the task's base/head branches, and opens a real PR in a chosen org.

Options, in increasing cost:

1. **Local target, no forge.** `targets/work-item.md` already accepts a
   caller-named tracking system plus a branch/commit named by the caller. Build
   a local repo per task (base/head), write a file-backed work item, and review
   it offline. No external repos, no skill change, hermetic and repeatable. This
   is the same "offline fixture target" shape already proposed for the
   regression set.
2. **Own clean PR per task.** Adapt `step0_fork_prs.py` to open PRs in the
   `vhallac` forks (or a dedicated eval org) with the task's base/head. Real MRs,
   but one repo per task/repo and external sprawl.
3. **Review the upstream PRs directly.** They are real MRs (`axios/axios#10836`),
   but many are merged/closed and the repos are the training-leakage surface the
   benchmark exists to avoid.

Recommendation: **(1)**. It satisfies the skill's target contract without
mutating external systems, and keeps the harness reproducible against pinned
commits. Decide whether the materializer and runner live here (this bench tree)
and whether the "generate reviews" work is filed as an issue rather than built
inline.
