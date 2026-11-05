# Task manifest (`review-task/1`)

One JSON file describes one benchmark task. `materialize.py` turns it into a
local review target; `run_review.py` uses the same file to pick the benchmark
adapter for the report it produces.

```json
{
  "schema": "review-task/1",
  "id": "axios-10836",
  "source": "https://github.com/review-bench/axios_axios",
  "base": "90ae1993e0eaa39ccccbaa25957bb23cc5676df7",
  "head": "9cd706ccb836c581371c760b4c6a5c61c656ea1f",
  "branch": "review/axios-10836",
  "work_item": {
    "tracker": "local-file",
    "title": "axios/axios#10836 — async/await docs example",
    "body": "The PR adds an async/await example to the README. Review the diff."
  },
  "judge": {
    "adapter": "reviewbench",
    "clone": "~/work/forks/reviewbench",
    "command": "npm run judge -- {candidate}",
    "model": "qwen/qwen3-coder",
    "repo": "https://github.com/axios/axios",
    "pr": 10836,
    "base": "90ae1993e0eaa39ccccbaa25957bb23cc5676df7",
    "head": "9cd706ccb836c581371c760b4c6a5c61c656ea1f"
  }
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | Always `review-task/1`. |
| `id` | yes | Task id; also the default report label and branch stem. |
| `source` | yes | Any `git clone` source: a URL (the only network use) or a local path (hermetic tests). |
| `base` | yes | Pinned base (merge-base) commit. |
| `head` | yes | Pinned head commit; the reviewed revision. |
| `branch` | no | Branch to create at `head`; default `review/<id>`. |
| `work_item` | no | `title`, `body`, `tracker` for the file-backed work item. `tracker` defaults to `local-file`. |
| `judge` | no | Which adapter turns the report into a benchmark candidate. Omit (or `adapter: none`) to stop at the report. |

`judge.adapter` values:

- `reviewbench` — needs `repo`, `pr`, `base`, `head`; optional `agent`.
  Writes `<run>/candidate.json` via `adapters/to_reviewbench.py`.
- `martian` — needs `pr_url` and `golden_comments` (path, relative to the
  manifest's directory); writes `<run>/martian/benchmark_data.json` plus a
  `candidates.json` via `adapters/to_martian.py`.

The base/head in `judge` repeat the task identity the judge validates against;
they normally equal the top-level `base`/`head`, but the full SHAs are kept
explicit because the adapter passes them to a judge that checks them literally.

Scoring fields (on `judge`):

- `clone` — path to a local working copy of the judge's fork; the judge code
  stays in its own fork, it is never vendored into the bench.
- `command` — judge invocation template run inside `clone`; `{candidate}` is
  replaced by the path of the candidate file to score.
- `model` — judge model pin, recorded in every score for reproducibility.

They are configured as a set: give all three or none. A partial scoring
config (or a non-string/empty value) is rejected with `ManifestError` by
`run_review.validate_judge` before anything runs.

## Limitation: fetching a pinned commit by SHA

`materialize.py` clones `source` and checks out the pinned `base`/`head`. When
a pinned commit is absent from the clone, it falls back to `git fetch origin
<sha>`. Git servers that do not enable
`uploadpack.allowReachableSHA1InWant` refuse a bare-SHA fetch, so the fallback
fails with git's error even though the commit exists on the remote. Work
around it by pinning a commit reachable from a fetched ref (a branch or tag
tip), or by enabling `uploadpack.allowReachableSHA1InWant` on the server.
