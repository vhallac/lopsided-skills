#!/usr/bin/env python3
"""Run a task manifest's judge on a candidate and write run/score.json.

The bridge between the adapters (`run_review.py` output) and the benchmark
judges. The judge itself lives in its fork (`judge.clone`); this script never
vendors judge code — it invokes `judge.command` inside that checkout with
`{candidate}` replaced by the candidate path and `{out}` by the raw-output
path, then normalizes whatever the judge wrote into the `bench-score/1`
schema.

Score schema `bench-score/1`:

    {
      "schema": "bench-score/1",
      "benchmark": "reviewbench" | "martian",
      "task": "<manifest id>",
      "status": "scored" | "generation-failed" | "empty-candidate" | "judge-failed",
      "judge_model": "<judge.model pin>",
      "base": "<judge.base or null>", "head": "<judge.head or null>",
      "precision": <float|null>, "recall": <float|null>, "f1": <float|null>,
      "raw_output": "<path to the raw judge output file>",
      "candidate": "<path to the candidate file>"
    }

Failure statuses are recorded, not raised: a failed generation or a judge
crash is data about the run, never a synthesized score of 0.

Usage:
  python score.py --task DIR            # candidate at <task>/run/candidate.json
  python score.py --task DIR --candidate PATH --out RUNDIR
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))
from run_review import validate_scoring  # noqa: E402
from tasklib import ManifestError, load_manifest  # noqa: E402

SCHEMA = "bench-score/1"
STATUSES = ("scored", "generation-failed", "empty-candidate", "judge-failed")


class JudgeOutputError(ValueError):
    """The judge ran but its output could not be normalized."""


# --- normalization ---------------------------------------------------------


def _f1(precision: float, recall: float) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def normalize_reviewbench(raw: dict) -> tuple[float | None, float | None, float | None]:
    """rb-oracle-results.json shape: macro.overall.{grounded_precision,grounded_recall}."""
    overall = (raw.get("macro") or {}).get("overall") or {}
    p = overall.get("grounded_precision")
    r = overall.get("grounded_recall")
    if p is None or r is None:
        raise JudgeOutputError("reviewbench output: no macro.overall grounded precision/recall")
    f = overall.get("grounded_f1")
    if f is None:
        f = _f1(p, r)
    return float(p), float(r), (None if f is None else float(f))


def _martian_pr_entry(raw: dict) -> dict:
    """step3_judge_comments writes one entry per PR; take the single entry."""
    entry = raw
    if "precision" not in raw and "recall" not in raw:
        prs = [v for k, v in raw.items() if isinstance(v, dict)]
        if len(prs) == 1:
            entry = prs[0]
    return entry


def normalize_martian(raw: dict) -> tuple[float | None, float | None, float | None]:
    """step3_judge_comments shape: precision/recall/f1 (per PR or top level)."""
    entry = _martian_pr_entry(raw)
    p = entry.get("precision")
    r = entry.get("recall")
    if p is None or r is None:
        raise JudgeOutputError("martian output: no precision/recall found")
    f = entry.get("f1")
    if f is None:
        f = _f1(p, r)
    return float(p), float(r), (None if f is None else float(f))


NORMALIZERS = {"reviewbench": normalize_reviewbench, "martian": normalize_martian}


# --- scoring ---------------------------------------------------------------


def make_score(manifest: dict, status: str, candidate: str | None, raw_path: str | None,
               metrics: tuple | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    judge = manifest.get("judge") or {}
    precision, recall, f1 = metrics or (None, None, None)
    return {
        "schema": SCHEMA,
        "benchmark": judge.get("adapter", "none"),
        "task": manifest["id"],
        "status": status,
        "judge_model": judge.get("model"),
        "base": judge.get("base"),
        "head": judge.get("head"),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "raw_output": raw_path,
        "candidate": candidate,
    }


def read_candidate_status(path: Path) -> str:
    """Map the candidate artifact to a pre-judge status, or 'ok' to proceed."""
    if not path.exists():
        return "generation-failed"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"score: candidate {path} is not valid JSON ({exc}); "
              "treating as generation failure", file=sys.stderr)
        return "generation-failed"
    findings = doc.get("findings")
    if isinstance(findings, list) and not findings:
        return "empty-candidate"
    # artifacts without a findings key (e.g. martian benchmark_data) cannot be
    # classified as empty here — let the judge decide
    return "ok"


def run_judge(manifest: dict, candidate: Path, raw_out: Path, manifest_dir: Path) -> dict:
    """Invoke judge.command inside judge.clone; return the parsed raw output."""
    judge = manifest["judge"]
    validate_scoring(judge)
    # same resolution semantics as the runner's _resolve_judge_path: ~ is
    # expanded, relative paths resolve against the manifest's directory
    clone = Path(os.path.expanduser(judge["clone"]))
    if not clone.is_absolute():
        clone = manifest_dir / clone
    if not clone.is_dir():
        raise ManifestError(f"judge: clone {clone} is not a directory")
    command = judge["command"].replace("{candidate}", str(candidate)).replace("{out}", str(raw_out))
    proc = subprocess.run(command, shell=True, cwd=str(clone), text=True, capture_output=True)
    raw_out.parent.mkdir(parents=True, exist_ok=True)
    if proc.returncode != 0:
        # capture stderr on stdout's behalf so failures are still auditable
        raw_out.write_text(proc.stderr, encoding="utf-8")
        raise RuntimeError(f"judge exited {proc.returncode}: {proc.stderr[-2000:]}")
    if not raw_out.exists() or not raw_out.stat().st_size:
        # judge wrote nothing of its own; fall back to its stdout
        raw_out.write_text(proc.stdout, encoding="utf-8")
    source = raw_out if raw_out.stat().st_size else None
    if source is None:
        raise JudgeOutputError("judge produced no output")
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JudgeOutputError(f"judge output is not valid JSON: {exc}") from exc


def score(manifest: dict, manifest_dir: Path, candidate: Path, run_dir: Path) -> dict:
    candidate_status = read_candidate_status(candidate)
    if candidate_status != "ok":
        return make_score(manifest, candidate_status,
                          str(candidate) if candidate.exists() else None, None)
    raw_out = run_dir / "judge-output.json"
    try:
        raw = run_judge(manifest, candidate, raw_out, manifest_dir)
        metrics = NORMALIZERS[(manifest.get("judge") or {}).get("adapter")](raw)
    except (RuntimeError, JudgeOutputError, ManifestError) as exc:
        print(f"score: judge failed: {exc}", file=sys.stderr)
        return make_score(manifest, "judge-failed", str(candidate), str(raw_out))
    return make_score(manifest, "scored", str(candidate), str(raw_out), metrics)


def main() -> int:
    ap = argparse.ArgumentParser(description="Score a candidate with the task's judge.")
    ap.add_argument("--task", required=True, help="materialized task directory (holds task.json)")
    ap.add_argument("--candidate", help="candidate JSON (default: <run>/candidate.json)")
    ap.add_argument("--out", help="run directory (default: <task>/run)")
    args = ap.parse_args()

    task_dir = Path(args.task).resolve()
    manifest = load_manifest(str(task_dir / "task.json"))
    run_dir = Path(args.out).resolve() if args.out else task_dir / "run"
    candidate = Path(args.candidate).resolve() if args.candidate else run_dir / "candidate.json"
    result = score(manifest, task_dir, candidate, run_dir)
    out_path = run_dir / "score.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
