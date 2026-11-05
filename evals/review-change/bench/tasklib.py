#!/usr/bin/env python3
"""Task-manifest loading for the offline review-generation harness.

A task manifest is the single description of a benchmark task shared by the
materializer (`materialize.py`) and the runner (`run_review.py`). Schema
`review-task/1`:

    {
      "schema": "review-task/1",
      "id": "axios-10836",
      "source": "https://github.com/review-bench/axios_axios",
      "base": "<commit>",
      "head": "<commit>",
      "branch": "review/axios-10836",              # optional
      "work_item": {
        "tracker": "local-file",                   # optional
        "title": "...",                            # optional
        "body": "..."                              # optional
      },
      "judge": {                                   # optional; absent = no adapt
        "adapter": "reviewbench" | "martian" | "none",
        "clone": "/path/to/judge-fork",            # scoring: fork working copy
        "command": "npm run judge -- {candidate}", # scoring: invocation template
        "model": "judge-model-pin",                # scoring: judge model pin
        ...adapter-specific fields, see adapters/
      }
    }

`source` is any `git clone` source: a URL (the only network use) or a local
path (hermetic tests). `base`/`head` are the pinned commits of the task.

Scoring fields (on `judge`): `clone` is the local working copy of the judge's
fork (the fork stays in its own checkout — the bench never vendors judge
code), `command` is the judge invocation template run inside that checkout
(`{candidate}` is replaced by the candidate file path), and `model` is the
judge model pin recorded in every score for reproducibility. They are
configured as a set: give all three or none — a partial scoring config is
rejected with `ManifestError`.
"""
from __future__ import annotations

import json

SCHEMA = "review-task/1"
REQUIRED = ("id", "source", "base", "head")


class ManifestError(ValueError):
    """A task manifest is missing, malformed, or incomplete."""


def validate_manifest(data: object, where: str = "manifest") -> dict:
    if not isinstance(data, dict):
        raise ManifestError(f"{where}: must be a JSON object")
    schema = data.get("schema")
    if schema != SCHEMA:
        raise ManifestError(f"{where}: schema must be {SCHEMA!r}, got {schema!r}")
    for key in REQUIRED:
        if not data.get(key):
            raise ManifestError(f"{where}: missing required field {key!r}")
    return data


def load_manifest(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{path}: not valid JSON: {exc}") from exc
    return validate_manifest(data, path)
