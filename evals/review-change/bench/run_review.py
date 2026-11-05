#!/usr/bin/env python3
"""Run `review-change` non-interactively against a materialized task.

The runner closes the gap the spike left open: it takes the local target
`materialize.py` produced, invokes a fresh `pi --print` round with the
`review-change` skill loaded, captures the emitted `review-report/1`, and hands
it to the benchmark adapter named in the task manifest. `review-change` itself
is not modified.

Usage:
  # end to end (requires the `pi` binary; clone/network already done)
  python run_review.py --task DIR [--label L] [--model PATTERN] [--timeout SECS]

  # replay an existing report through the adapter, without invoking pi
  python run_review.py --task DIR --report REPORT.md [--adapter-python PYTHON]

The report is written to the system temp dir; the runner points the `pi`
subprocess at a private `TMPDIR` so it can find the emitted file. Everything
the run produces lands under `<task>/run/`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))
from tasklib import ManifestError, load_manifest  # noqa: E402

JUDGE_REQUIRED = {
    "reviewbench": ("repo", "pr", "base", "head"),
    "martian": ("pr_url", "golden_comments"),
}

SCORING_FIELDS = ("clone", "command", "model")

DEFAULT_SKILL = BENCH_DIR.parents[2] / "skills" / "review-change"

PROMPT_TEMPLATE = """Run the review-change skill on the local target below. This is a \
disposable, hermetic fixture: do not modify or commit anything, and do not \
publish — stop after writing the report.

Work item (tracker: local-file; read it with `cat {work_item}`):
  {work_item}

Repository under review:
  {repo}
Branch: {branch}
Reviewed commit (head): {head}
Merge base (base): {base}
Report label: {label}
Private TMPDIR: {tmpdir}

The change under review is the commit range {base}...{head}. Follow \
review-change exactly: resolve the work-item target from the file above, choose \
implementation mode, create the review worktree from {repo} at {head}, gather \
evidence, falsify, and write the report to the system temp dir using label \
{label}. Do not call publish-review. End your reply with the full path of the \
report you wrote.
"""


def build_prompt(manifest: dict, task_dir: str | Path, label: str, tmpdir: str | Path) -> str:
    task_dir = Path(task_dir)
    branch = manifest.get("branch") or f"review/{manifest['id']}"
    return PROMPT_TEMPLATE.format(
        id=manifest["id"],
        repo=task_dir / "repo",
        work_item=task_dir / "work-item.md",
        branch=branch,
        base=manifest["base"],
        head=manifest["head"],
        label=label,
        tmpdir=tmpdir,
    )


def validate_judge(manifest: dict) -> None:
    """Reject a malformed judge before pi or any adapter runs."""
    judge = manifest.get("judge") or {}
    if not isinstance(judge, dict):
        raise ManifestError(f"judge: must be an object, got {type(judge).__name__}")
    name = judge.get("adapter", "none")
    if name in ("", "none"):
        return
    required = JUDGE_REQUIRED.get(name)
    if required is None:
        raise ManifestError(f"judge: unknown adapter {name!r}")
    missing = [field for field in required if not judge.get(field)]
    if missing:
        raise ManifestError(f"judge ({name}): missing required field(s): {', '.join(missing)}")
    validate_scoring(judge, where="judge")


def validate_scoring(judge: dict, where: str = "judge") -> None:
    """Scoring config is all-or-nothing: clone + command + model, all non-empty strings."""
    present = [f for f in SCORING_FIELDS if f in judge and judge[f] not in (None, "")]
    if not present:
        return
    missing = [f for f in SCORING_FIELDS if f not in present]
    if missing:
        raise ManifestError(
            f"{where}: partial scoring config; missing scoring field(s): {', '.join(missing)}")
    for field in present:
        value = judge[field]
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(f"{where}: scoring field {field!r} must be a non-empty string")


def _pi_binary() -> str:
    return os.environ.get("PI_BIN") or shutil.which("pi") or "pi"


def _adapter_python(explicit: str | None) -> list[str]:
    """A python command that can import PyYAML (the adapters' one dependency)."""
    if explicit:
        return [explicit]
    try:
        import yaml  # noqa: F401
        return [sys.executable]
    except ImportError:
        if shutil.which("uv"):
            return ["uv", "run", "--with", "pyyaml", "python"]
        return [sys.executable]


def find_report(tmpdir: str | Path) -> Path | None:
    reports = sorted(Path(tmpdir).glob("review-*.md"), key=lambda p: p.stat().st_mtime)
    return reports[-1] if reports else None


def invoke_pi(prompt: str, skill: str, model: str | None, timeout: int | None,
              task_dir: Path, run_dir: Path, tmpdir: Path) -> int:
    cmd = [_pi_binary(), "--print", "--no-session"]
    if model:
        cmd += ["--model", model]
    cmd += ["--skill", str(skill), "--approve", prompt]

    env = os.environ.copy()
    env["TMPDIR"] = str(tmpdir)
    with open(run_dir / "transcript.txt", "w", encoding="utf-8") as out, \
            open(run_dir / "pi.stderr", "w", encoding="utf-8") as err:
        proc = subprocess.run(
            cmd, cwd=str(task_dir), env=env, stdout=out, stderr=err,
            text=True, timeout=timeout,
        )
    return proc.returncode


def _resolve_judge_path(value: str, manifest_dir: Path) -> str:
    p = Path(value)
    return str(p if p.is_absolute() else manifest_dir / p)


def adapt(manifest: dict, report: Path, run_dir: Path, python_cmd: list[str],
          manifest_dir: Path) -> str | None:
    judge = manifest.get("judge") or {}
    name = judge.get("adapter", "none")
    if name in ("", "none"):
        return None

    if name == "reviewbench":
        out = run_dir / "candidate.json"
        cmd = python_cmd + [
            str(BENCH_DIR / "adapters" / "to_reviewbench.py"), str(report),
            "--repo", judge["repo"], "--pr", str(judge["pr"]),
            "--base", judge["base"], "--head", judge["head"],
            "--agent", judge.get("agent", "review-change"), "--out", str(out),
        ]
    elif name == "martian":
        model_dir = run_dir / "martian"
        data = model_dir / "benchmark_data.json"
        cmd = python_cmd + [
            str(BENCH_DIR / "adapters" / "to_martian.py"), str(report),
            "--pr-url", judge["pr_url"],
            "--model-dir", str(model_dir), "--out-data", str(data),
            "--golden-comments", _resolve_judge_path(judge["golden_comments"], manifest_dir),
        ]
    else:
        raise SystemExit(f"error: unknown judge adapter {name!r}")

    proc = subprocess.run(cmd, text=True, capture_output=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"error: adapter {name!r} failed with exit {proc.returncode}")
    return str(out) if name == "reviewbench" else str(data)



def score_candidate(manifest: dict, task_dir: Path, candidate: Path | None, run_dir: Path,
                    python_cmd: list[str]) -> dict | None:
    """Run score.py on the adapted candidate; return the parsed bench-score/1 doc."""
    judge = manifest.get("judge") or {}
    if not candidate:
        return None
    if not any(f in judge for f in SCORING_FIELDS):
        return None  # scoring config absent: adapt-only run
    cmd = python_cmd + [
        str(BENCH_DIR / "score.py"), "--task", str(task_dir),
        "--candidate", str(candidate), "--out", str(run_dir),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        # score.py's own stdout duplicates score.json; surface diagnostics only
        # on failure so the runner's summary JSON stays the last stdout document
        sys.stderr.write(proc.stderr or proc.stdout)
        raise SystemExit(f"error: score.py failed with exit {proc.returncode}")
    return json.loads((run_dir / "score.json").read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run review-change against a materialized task.")
    ap.add_argument("--task", required=True, help="materialized task directory (holds task.json)")
    ap.add_argument("--report", help="existing review-report/1; skip invoking pi")
    ap.add_argument("--label", help="report label (default: task id)")
    ap.add_argument("--out", help="run directory (default: <task>/run)")
    ap.add_argument("--skill", default=str(DEFAULT_SKILL), help="review-change skill path")
    ap.add_argument("--model", help="pi model pattern")
    ap.add_argument("--timeout", type=int, default=1800, help="pi timeout in seconds")
    ap.add_argument("--no-adapt", action="store_true", help="stop at the report")
    ap.add_argument("--no-score", action="store_true",
                    help="stop after adaptation; skip the judge scoring step")
    ap.add_argument("--adapter-python", help="python executable that can import PyYAML")
    args = ap.parse_args()

    task_dir = Path(args.task).resolve()
    manifest_path = task_dir / "task.json"
    manifest = load_manifest(str(manifest_path))
    validate_judge(manifest)
    run_dir = Path(args.out).resolve() if args.out else task_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or str(manifest["id"]).replace("/", "-")

    if args.report:
        report = Path(args.report).resolve()
        if not report.exists():
            raise SystemExit(f"error: report not found: {report}")
    else:
        tmpdir = run_dir / "tmp"
        if tmpdir.exists():
            shutil.rmtree(tmpdir)
        tmpdir.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(manifest, task_dir, label, tmpdir)
        (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        rc = invoke_pi(prompt, args.skill, args.model, args.timeout, task_dir, run_dir, tmpdir)
        if rc != 0:
            err = (run_dir / "pi.stderr").read_text(encoding="utf-8")[-2000:]
            raise SystemExit(f"error: pi exited {rc}\n{err}")
        found = find_report(tmpdir)
        if found is None:
            raise SystemExit(f"error: no review-*.md under {tmpdir}; see {run_dir / 'transcript.txt'}")
        report = found

    kept = run_dir / "review.md"
    shutil.copy(report, kept)

    candidate = None
    if not args.no_adapt:
        candidate = adapt(manifest, kept, run_dir, _adapter_python(args.adapter_python),
                          manifest_path.parent)

    score_doc = None
    if not args.no_adapt and not args.no_score:
        score_doc = score_candidate(manifest, task_dir,
                                    Path(candidate) if candidate else None,
                                    run_dir, _adapter_python(args.adapter_python))

    summary = {"report": str(kept), "candidate": candidate}
    if score_doc is not None:
        summary["score"] = str(run_dir / "score.json")
        summary["status"] = score_doc["status"]
    print(json.dumps(summary, indent=2))
    # a failure status is data about the run, not a synthesized 0 — but the
    # caller must be able to tell the run did not score
    if score_doc is not None and score_doc["status"] != "scored":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
