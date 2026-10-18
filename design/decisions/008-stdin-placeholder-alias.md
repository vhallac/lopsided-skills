# 008 — stdin placeholder alias (`-`) for file-reading flags

Status: accepted
Date: 2026-10-18
Refs: issue #8; prior fix in store.py/plan.py (PR #16)

## Decision

Every CLI flag that reads file content supplied by the agent ( resolutions
input for `contracts resolve`, diff input for `contracts affected`, and any
future file-reading flag) accepts `-` as an alias for stdin, in the style of
gzip and common Unix filters.

## Rationale

Agent-supplied content otherwise needs a temp file, which trips scratch
hygiene rules (temp files are ephemeral, must be swept, and add failure
modes). Reading from stdin lets the agent pipe content directly, e.g.:

```
generate-diff | contracts affected --diff -
```

Implementation is deliberately small: a one-line helper per read site
(`stdin if flag == "-" else Path(flag).read_text()`), mirroring
`body_argument()` in store.py.

## Scope note

The pattern applies when applicable to any LLM helper script that takes
file-content flags — not just the contracts CLI. New helper scripts should
follow it by default for content-supplying flags; config/path-style flags
(repository root, config file) are not covered, since those name persistent
repository locations, not piped content.
