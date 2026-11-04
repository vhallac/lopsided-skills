#!/usr/bin/env python3
"""Tests for the offline review-generation harness.

The materializer and runner are ordinary tested code, so these tests assert
externally observable behavior: the materialized repo ends at the pinned head,
the work item names it, a report maps to a non-empty benchmark candidate, and
the runner's prompt names the target. No network: the fixtures build a local
source repository.

Run:
  uv run --with pytest --with pyyaml python -m pytest evals/review-change/bench -q
  # or, with PyYAML already on the path:
  python3 -m pytest evals/review-change/bench -q
  python3 -m unittest discover -s evals/review-change/bench -p 'test_*.py'
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
MATERIALIZE = BENCH_DIR / "materialize.py"
RUNNER = BENCH_DIR / "run_review.py"
REVIEWBENCH_ADAPTER = BENCH_DIR / "adapters" / "to_reviewbench.py"

sys.path.insert(0, str(BENCH_DIR))
import run_review  # noqa: E402

HAVE_YAML = importlib.util.find_spec("yaml") is not None

REPORT_TEMPLATE = """---
schema: review-report/1
label: fixture
round: 1
target: issue:1
forge: none
mode: implementation
base: {base}
head: {head}
verdict: request-changes
findings:
  - {{id: F1, severity: Minor, likelihood: probable, summary: "sample finding"}}
unrelated: []
prior: []
waivers: []
---

# Review

## Findings

#### F1 — Minor: sample finding

- **Anchor:** `src/a.txt:1-2`
- **Claim / expected:** sample claim.
- **Existing behavior:** old behavior.
- **Trigger:** any.
- **Consequence:** none.
- **Evidence:** fixture.
- **Likelihood:** probable
- **Recommended correction:** fix it.
"""


def _git(*args: str, cwd: Path) -> str:
    p = subprocess.run(["git", *args], cwd=str(cwd), check=True, text=True, capture_output=True)
    return p.stdout.strip()


class SourceFixture:
    """A local git repository with two commits, usable as a clone source."""

    def __init__(self, root: Path):
        self.repo = root / "source"
        self.repo.mkdir()
        _git("init", "-q", cwd=self.repo)
        _git("config", "user.email", "test@example.com", cwd=self.repo)
        _git("config", "user.name", "test", cwd=self.repo)
        (self.repo / "a.txt").write_text("one\n", encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.txt").write_text("one\n", encoding="utf-8")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-qm", "base", cwd=self.repo)
        self.base = _git("rev-parse", "HEAD", cwd=self.repo)
        (self.repo / "src" / "a.txt").write_text("two\n", encoding="utf-8")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-qm", "head", cwd=self.repo)
        self.head = _git("rev-parse", "HEAD", cwd=self.repo)


def _manifest(source: SourceFixture, **overrides) -> dict:
    manifest = {
        "schema": "review-task/1",
        "id": "fixture-1",
        "source": str(source.repo),
        "base": source.base,
        "head": source.head,
        "work_item": {"title": "Fixture task", "body": "Body text."},
        "judge": {
            "adapter": "reviewbench",
            "repo": "https://github.com/owner/repo",
            "pr": 1,
            "base": source.base,
            "head": source.head,
        },
    }
    manifest.update(overrides)
    return manifest


class MaterializeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = SourceFixture(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_manifest(self, manifest: dict, name: str = "task.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def _materialize(self, manifest_path: Path, out: Path, *extra: str):
        return subprocess.run(
            [sys.executable, str(MATERIALIZE), "--manifest", str(manifest_path), "--out", str(out), *extra],
            text=True, capture_output=True,
        )

    def test_checks_out_head_and_writes_work_item(self) -> None:
        out = self.root / "task"
        r = self._materialize(self._write_manifest(_manifest(self.source)), out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=out / "repo"), self.source.head)
        work_item = (out / "work-item.md").read_text(encoding="utf-8")
        self.assertIn("fixture-1", work_item)
        self.assertIn(self.source.head, work_item)
        self.assertTrue((out / "task.json").is_file())

    def test_rejects_manifest_missing_head(self) -> None:
        manifest = _manifest(self.source)
        del manifest["head"]
        r = self._materialize(self._write_manifest(manifest), self.root / "bad")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("head", r.stderr.lower())

    def test_refuses_non_empty_output_without_force(self) -> None:
        out = self.root / "taken"
        out.mkdir()
        (out / "keep").write_text("x", encoding="utf-8")
        r = self._materialize(self._write_manifest(_manifest(self.source)), out)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((out / "keep").is_file())


@unittest.skipUnless(HAVE_YAML, "PyYAML required; run under uv run --with pyyaml")
class AdapterTests(unittest.TestCase):
    def test_report_maps_to_non_empty_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "review.md"
            report.write_text(REPORT_TEMPLATE.format(base="aaa", head="bbb"), encoding="utf-8")
            out = root / "candidate.json"
            r = subprocess.run(
                [sys.executable, str(REVIEWBENCH_ADAPTER), str(report),
                 "--repo", "https://github.com/owner/repo", "--pr", "1",
                 "--base", "aaa", "--head", "bbb", "--out", str(out)],
                text=True, capture_output=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(doc["findings"]), 1)
            self.assertEqual(doc["findings"][0]["file"], "src/a.txt")


@unittest.skipUnless(HAVE_YAML, "PyYAML required; run under uv run --with pyyaml")
class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = SourceFixture(self.root)
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps(_manifest(self.source)), encoding="utf-8")
        self.task = self.root / "task"
        r = subprocess.run(
            [sys.executable, str(MATERIALIZE), "--manifest", str(manifest_path), "--out", str(self.task)],
            text=True, capture_output=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_replay_report_through_runner_produces_candidate(self) -> None:
        report = self.root / "given.md"
        report.write_text(REPORT_TEMPLATE.format(base=self.source.base, head=self.source.head), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(RUNNER), "--task", str(self.task), "--report", str(report),
             "--adapter-python", sys.executable],
            text=True, capture_output=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        candidate = self.task / "run" / "candidate.json"
        self.assertTrue(candidate.is_file())
        doc = json.loads(candidate.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(doc["findings"]), 1)
        self.assertTrue((self.task / "run" / "review.md").is_file())

    def test_prompt_names_target_and_revision(self) -> None:
        manifest = _manifest(self.source)
        prompt = run_review.build_prompt(manifest, self.task, "fixture-1", self.root / "tmp")
        self.assertIn(str(self.task / "work-item.md"), prompt)
        self.assertIn(self.source.head, prompt)
        self.assertIn(str(self.task / "repo"), prompt)


if __name__ == "__main__":
    unittest.main()
