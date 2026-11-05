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

# claim: bench-harness-SC-1/GUAR/test_checks_out_head_and_writes_work_item
# claim text: materializing a valid `review-task/1` manifest checks out the
#   pinned head commit and writes a work item naming the task id and head.
# scenario: Scenario: Materializer checks out the pinned head and writes a work item — Then the clone's HEAD equals the pinned head, the work item names the branch, base and head, and task.json is written.
    def test_checks_out_head_and_writes_work_item(self) -> None:
        out = self.root / "task"
        r = self._materialize(self._write_manifest(_manifest(self.source)), out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=out / "repo"), self.source.head)
        work_item = (out / "work-item.md").read_text(encoding="utf-8")
        self.assertIn("fixture-1", work_item)
        self.assertIn(self.source.head, work_item)
        self.assertTrue((out / "task.json").is_file())

# claim: bench-harness-SC-2/GUAR/test_rejects_manifest_missing_head
# claim text: a manifest omitting `head` is rejected, naming the missing field.
# scenario: Scenario: Materializer rejects a manifest missing head — When the manifest omits head Then the command fails naming the missing field.
    def test_rejects_manifest_missing_head(self) -> None:
        manifest = _manifest(self.source)
        del manifest["head"]
        r = self._materialize(self._write_manifest(manifest), self.root / "bad")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("head", r.stderr.lower())

# claim: bench-harness-SC-3/GUAR/test_refuses_non_empty_output_without_force
# claim text: a non-empty output directory without `--force` is refused and
#   left untouched.
# scenario: Scenario: Materializer refuses a non-empty output without --force — When the output directory is non-empty and --force is absent Then the command fails and leaves the directory untouched.
    def test_refuses_non_empty_output_without_force(self) -> None:
        out = self.root / "taken"
        out.mkdir()
        (out / "keep").write_text("x", encoding="utf-8")
        r = self._materialize(self._write_manifest(_manifest(self.source)), out)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((out / "keep").is_file())


@unittest.skipUnless(HAVE_YAML, "PyYAML required; run under uv run --with pyyaml")
class AdapterTests(unittest.TestCase):
# claim: bench-harness-SC-4/GUAR/test_report_maps_to_non_empty_candidate
# claim text: a well-formed `review-report/1` maps through the reviewbench
#   adapter to a non-empty candidate with a mapped file.
# scenario: Scenario: reviewbench adapter maps a report to a non-empty candidate — When a review-report/1 is passed to to_reviewbench.py Then candidate.json holds at least one finding with a mapped file.
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

# claim: bench-harness-SC-5/GUAR/test_replay_report_through_runner_produces_candidate
# claim text: the runner given an existing report writes candidate.json and
#   keeps a copy at run/review.md.
# scenario: Scenario: Runner replays a report through the reviewbench adapter — When the runner is given an existing report Then candidate.json is written and a copy is kept at run/review.md.
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

# claim: bench-harness-SC-7/GUAR/test_replay_report_through_martian_adapter
# claim text: the runner given an existing report and a martian judge with a
#   golden fixture writes martian/benchmark_data.json and candidates.json,
#   with candidates.json keyed by the judge pr_url.
# scenario: Scenario: Runner replays a report through the martian adapter — When the runner is given a report and a martian judge with a golden fixture Then martian/benchmark_data.json and martian/candidates.json are written and candidates.json is keyed by the judge pr_url.
    def test_replay_report_through_martian_adapter(self) -> None:
        pr_url = "https://github.com/owner/repo/pull/1"
        golden = self.root / "golden_comments.json"
        golden.write_text(
            json.dumps([{
                "url": pr_url,
                "comments": [{"comment": "sample", "severity": "Minor", "category": "style"}],
            }]),
            encoding="utf-8",
        )
        manifest = _manifest(self.source, judge={
            "adapter": "martian",
            "pr_url": pr_url,
            "golden_comments": str(golden),
        })
        manifest_path = self.root / "martian-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        task = self.root / "martian-task"
        r = subprocess.run(
            [sys.executable, str(MATERIALIZE), "--manifest", str(manifest_path), "--out", str(task)],
            text=True, capture_output=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        report = self.root / "given.md"
        report.write_text(
            REPORT_TEMPLATE.format(base=self.source.base, head=self.source.head), encoding="utf-8"
        )
        r = subprocess.run(
            [sys.executable, str(RUNNER), "--task", str(task), "--report", str(report),
             "--adapter-python", sys.executable],
            text=True, capture_output=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        data = task / "run" / "martian" / "benchmark_data.json"
        candidates = task / "run" / "martian" / "candidates.json"
        self.assertTrue(data.is_file())
        self.assertTrue(candidates.is_file())
        doc = json.loads(candidates.read_text(encoding="utf-8"))
        self.assertIn(pr_url, doc)

# claim: bench-harness-SC-6/GUAR/test_prompt_names_target_and_revision
# claim text: the rendered prompt names the work item, the repository path and
#   the head commit.
# scenario: Scenario: Runner prompt names the target and revision — When build_prompt renders a manifest Then the prompt names the work item, repository and head commit.
    def test_prompt_names_target_and_revision(self) -> None:
        manifest = _manifest(self.source)
        prompt = run_review.build_prompt(manifest, self.task, "fixture-1", self.root / "tmp")
        self.assertIn(str(self.task / "work-item.md"), prompt)
        self.assertIn(self.source.head, prompt)
        self.assertIn(str(self.task / "repo"), prompt)


if __name__ == "__main__":
    unittest.main()
