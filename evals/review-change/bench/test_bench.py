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
import os
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
import score  # noqa: E402

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

# claim: bench-harness-SC-8/GUAR/test_surfaces_git_stderr_on_failure
# claim text: when the clone or fetch fails, the raised error carries the
#   failing command's stderr.
# scenario: Scenario: Materializer surfaces git stderr on failure — When the clone or fetch fails Then the raised error carries the failing command's stderr.
    def test_surfaces_git_stderr_on_failure(self) -> None:
        missing = self.root / "does-not-exist"
        manifest = _manifest(self.source)
        manifest["source"] = str(missing)
        r = self._materialize(self._write_manifest(manifest), self.root / "bad-source")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does-not-exist", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

# claim: bench-harness-SC-9/GUAR/test_refuses_existing_non_directory_out
# claim text: an existing file or symlink-to-file `--out` is refused with the
#   guarded message, not a traceback.
# scenario: Scenario: Materializer rejects an existing non-directory --out — When --out names an existing file or a symlink to one Then the command fails with the guarded message, not a traceback.
    def test_refuses_existing_non_directory_out(self) -> None:
        target = self.root / "existing-file"
        target.write_text("x", encoding="utf-8")
        link = self.root / "file-link"
        link.symlink_to(target)
        for label, path in (("file", target), ("symlink-to-file", link)):
            with self.subTest(out=label):
                r = self._materialize(self._write_manifest(_manifest(self.source)), path)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("not a directory", r.stderr.lower())
                self.assertNotIn("Traceback", r.stderr)


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

# claim: bench-harness-SC-10/GUAR/test_validates_judge_fields_before_pi
# claim text: a reviewbench or martian judge missing a required field raises
#   ManifestError before pi or any adapter runs.
# scenario: Scenario: Runner validates judge fields before invoking pi — When the judge adapter is reviewbench or martian and a required field is absent Then the runner raises ManifestError before running pi or the adapter.
    def test_validates_judge_fields_before_pi(self) -> None:
        manifest = json.loads((self.task / "task.json").read_text(encoding="utf-8"))
        manifest["judge"] = {"adapter": "reviewbench", "repo": "r", "pr": 1}
        (self.task / "task.json").write_text(json.dumps(manifest), encoding="utf-8")
        marker = self.root / "pi-ran-marker"
        fake_pi = self.root / "fake-pi.sh"
        fake_pi.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
        fake_pi.chmod(0o755)
        env = dict(os.environ, PI_BIN=str(fake_pi))
        r = subprocess.run(
            [sys.executable, str(RUNNER), "--task", str(self.task)],
            text=True, capture_output=True, env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("judge", r.stderr.lower())
        self.assertFalse(marker.exists())
        with self.assertRaises(run_review.ManifestError):
            run_review.validate_judge({"judge": {"adapter": "martian", "pr_url": "u"}})
        with self.assertRaises(run_review.ManifestError):
            run_review.validate_judge({"judge": "reviewbench"})

# claim: bench-harness-SC-12/GUAR/test_validates_scoring_config_all_or_nothing
# claim text: a judge scoring config (clone/command/model) given partially or
#   with non-string values raises ManifestError; the complete set passes.
# scenario: Scenario: Runner validates judge scoring config — When the judge block names only some of clone/command/model, or one of them is not a non-empty string, Then the runner raises ManifestError; when all three are non-empty strings the judge validates.
    def test_validates_scoring_config_all_or_nothing(self) -> None:
        base = {"adapter": "reviewbench", "repo": "r", "pr": 1,
                "base": "b", "head": "h"}
        with self.assertRaises(run_review.ManifestError):
            run_review.validate_judge({"judge": {**base, "clone": "/fork", "command": "c"}})
        with self.assertRaises(run_review.ManifestError):
            run_review.validate_judge({"judge": {**base, "clone": "/fork", "model": "m"}})
        with self.assertRaises(run_review.ManifestError):
            run_review.validate_judge(
                {"judge": {**base, "clone": "/fork", "command": "c", "model": 7}})
        with self.assertRaises(run_review.ManifestError):
            run_review.validate_judge(
                {"judge": {**base, "clone": " ", "command": "c", "model": "m"}})
        run_review.validate_judge(
            {"judge": {**base, "clone": "/fork", "command": "npm run judge -- {candidate}",
                       "model": "qwen/qwen3-coder"}})
        # scoring fields are optional when scoring is not requested
        run_review.validate_judge({"judge": dict(base)})

# claim: bench-harness-SC-11/GUAR/test_fails_on_stale_report_instead_of_re_adapting
# claim text: a prior run's report in the private tmpdir is cleared so a pi run
#   that emits nothing fails instead of re-adapting the stale report.
# scenario: Scenario: Runner clears the private tmpdir before a run — When a prior run left a review-*.md in the private tmpdir and pi emits nothing Then the runner fails instead of re-adapting the stale report.
    def test_fails_on_stale_report_instead_of_re_adapting(self) -> None:
        tmpdir = self.task / "run" / "tmp"
        tmpdir.mkdir(parents=True, exist_ok=True)
        stale = tmpdir / "review-stale.md"
        stale.write_text(
            REPORT_TEMPLATE.format(base=self.source.base, head=self.source.head), encoding="utf-8"
        )
        fake_pi = self.root / "silent-pi.sh"
        fake_pi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_pi.chmod(0o755)
        env = dict(os.environ, PI_BIN=str(fake_pi))
        r = subprocess.run(
            [sys.executable, str(RUNNER), "--task", str(self.task), "--adapter-python", sys.executable],
            text=True, capture_output=True, env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no review-", r.stderr)


@unittest.skipUnless(HAVE_YAML, "PyYAML required; run under uv run --with pyyaml")
class ScoreTests(unittest.TestCase):
    RB_RESULTS = BENCH_DIR / "results" / "rb-oracle-results.json"

# claim: bench-harness-SC-13/GUAR/test_normalizes_reviewbench_oracle_fixture
# claim text: normalize_reviewbench maps the recorded reviewbench oracle
#   results to precision/recall/f1 all equal to 1.0.
# scenario: Scenario: Reviewbench oracle normalizes perfectly — When the recorded reviewbench oracle results fixture is passed through normalize_reviewbench Then precision, recall, and f1 are all exactly 1.0.
    @unittest.skipUnless(RB_RESULTS.is_file(), "reviewbench oracle fixture required")
    def test_normalizes_reviewbench_oracle_fixture(self) -> None:
        raw = json.loads(self.RB_RESULTS.read_text(encoding="utf-8"))
        p, r, f = score.normalize_reviewbench(raw)
        self.assertEqual((p, r, f), (1.0, 1.0, 1.0))

    def _scored_manifest(self, root: Path, command: str, **judge_overrides) -> dict:
        return {
            "schema": "review-task/1", "id": "score-fixture",
            "source": str(root / "src"), "base": "aaa", "head": "bbb",
            "judge": {
                "adapter": "reviewbench",
                "repo": "https://github.com/owner/repo", "pr": 1,
                "base": "aaa", "head": "bbb",
                "clone": str(root / "fork"), "command": command, "model": "judge-model-pin",
                **judge_overrides,
            },
        }

    def _run_score(self, manifest: dict, root: Path, candidate: Path | None,
                   candidate_doc: dict | None = None) -> dict:
        (root / "fork").mkdir(exist_ok=True)
        manifest_path = root / "task.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        run_dir = root / "run"
        run_dir.mkdir(exist_ok=True)
        if candidate_doc is not None:
            candidate.write_text(json.dumps(candidate_doc), encoding="utf-8")
        return score.score(manifest, root, candidate, run_dir)

# claim: bench-harness-SC-14/GUAR/test_statuses_generation_failed_empty_judge_failed_scored
# claim text: scoring yields generation-failed when the candidate is missing,
#   empty-candidate for empty findings (judge never invoked), judge-failed on
#   a nonzero judge exit (never a synthesized score), and scored with 1.0/1.0/1.0
#   metrics when the stub judge copies the oracle fixture to {out}.
# scenario: Scenario: Scoring status mapping end to end — When the candidate is absent, has empty findings, the judge exits nonzero, and the judge emits oracle results respectively Then the score status is generation-failed, empty-candidate, judge-failed (no score), and scored with precision/recall/f1 1.0 respectively.
    def test_statuses_generation_failed_empty_judge_failed_scored(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            boom = f"cp {self.RB_RESULTS} {{out}} && exit 1"
            # generation-failed: no candidate at all, judge never invoked
            s = self._run_score(self._scored_manifest(root, boom), root,
                                root / "run" / "candidate.json")
            self.assertEqual(s["status"], "generation-failed")
            self.assertIsNone(s["precision"])
            # empty-candidate: empty findings never reach the judge
            empty = root / "run" / "candidate.json"
            s = self._run_score(self._scored_manifest(root, boom), root, empty,
                                {"pr": {}, "findings": []})
            self.assertEqual(s["status"], "empty-candidate")
            # judge-failed: nonzero exit recorded, not synthesized as a score
            cand = root / "run" / "candidate.json"
            s = self._run_score(self._scored_manifest(root, "exit 3"), root, cand,
                                {"pr": {}, "findings": [{"file": "a"}]})
            self.assertEqual(s["status"], "judge-failed")
            self.assertEqual(s["raw_output"], str(root / "run" / "judge-output.json"))
            # scored: stub judge copies the oracle results to {out}
            ok = f"cp {self.RB_RESULTS} {{out}}"
            s = self._run_score(self._scored_manifest(root, ok), root, cand,
                                {"pr": {}, "findings": [{"file": "a"}]})
            self.assertEqual(s["status"], "scored")
            self.assertEqual((s["precision"], s["recall"], s["f1"]), (1.0, 1.0, 1.0))
            self.assertEqual(s["judge_model"], "judge-model-pin")
            self.assertEqual(s["schema"], score.SCHEMA)

    def test_paths_with_spaces_survive_judge_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # task dir with a space exercises {candidate}/{out} quoting
            root = Path(td) / "task dir with space"
            root.mkdir()
            manifest = self._scored_manifest(
                root, f"cp {self.RB_RESULTS} {{out}}")
            s = self._run_score(
                manifest, root, root / "run" / "candidate.json",
                {"pr": {}, "findings": [{"file": "a"}]})
            self.assertEqual(s["status"], "scored")
            self.assertEqual((s["precision"], s["recall"], s["f1"]), (1.0, 1.0, 1.0))

    def test_cli_writes_run_score_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self._scored_manifest(
                root, f"cp {self.RB_RESULTS} {{out}}")
            (root / "task.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "fork").mkdir()
            run_dir = root / "run"
            run_dir.mkdir()
            cand = run_dir / "candidate.json"
            cand.write_text(json.dumps({"pr": {}, "findings": [{"file": "a"}]}),
                            encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(BENCH_DIR / "score.py"), "--task", str(root)],
                text=True, capture_output=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["status"], "scored")
            self.assertEqual(doc["task"], "score-fixture")


# claim: bench-harness-SC-15/GUAR/test_runner_wires_scoring
# claim text: one run of run_review.py emits review.md, the adapted candidate,
#   and score.json, with the summary carrying the score status.
# scenario: Scenario: Runner wires scoring — Given a task with scoring config and a stub judge that scores When run_review.py replays a report Then run/ holds review.md, candidate.json, and score.json with status scored, and the summary reports scored.
class WiringTests(unittest.TestCase):
    RB_RESULTS = BENCH_DIR / "results" / "rb-oracle-results.json"

    @unittest.skipUnless(RB_RESULTS.is_file(), "reviewbench oracle fixture required")
    def _task(self, root: Path, command: str) -> Path:
        manifest = {
            "schema": "review-task/1", "id": "wiring-fixture",
            "source": str(root / "src"), "base": "aaa", "head": "bbb",
            "judge": {
                "adapter": "reviewbench",
                "repo": "https://github.com/owner/repo", "pr": 1,
                "base": "aaa", "head": "bbb",
                "clone": str(root / "fork"), "command": command,
                "model": "judge-model-pin",
            },
        }
        (root / "fork").mkdir()
        (root / "task.json").write_text(json.dumps(manifest), encoding="utf-8")
        return root

    def _run_runner(self, root: Path, report: Path, *extra: str):
        return subprocess.run(
            [sys.executable, str(RUNNER), "--task", str(root), "--report", str(report),
             "--adapter-python", sys.executable, *extra],
            text=True, capture_output=True,
        )

    @unittest.skipUnless(RB_RESULTS.is_file(), "reviewbench oracle fixture required")
    def test_runner_wires_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self._task(root, f"cp {self.RB_RESULTS} {{out}}")
            report = root / "given.md"
            report.write_text(REPORT_TEMPLATE.format(base="aaa", head="bbb"), encoding="utf-8")
            r = self._run_runner(task, report)
            self.assertEqual(r.returncode, 0, r.stderr)
            run_dir = task / "run"
            self.assertTrue((run_dir / "review.md").is_file())
            self.assertTrue((run_dir / "candidate.json").is_file())
            score_doc = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
            self.assertEqual(score_doc["status"], "scored")
            summary = json.loads(r.stdout[r.stdout.index("{"):])  # adapter line precedes the summary
            self.assertEqual(summary["status"], "scored")
            self.assertEqual(summary["score"], str(run_dir / "score.json"))

    @unittest.skipUnless(RB_RESULTS.is_file(), "reviewbench oracle fixture required")
    def test_runner_propagates_failure_status_as_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self._task(root, "exit 3")
            report = root / "given.md"
            report.write_text(REPORT_TEMPLATE.format(base="aaa", head="bbb"), encoding="utf-8")
            r = self._run_runner(task, report)
            self.assertEqual(r.returncode, 1)
            score_doc = json.loads((task / "run" / "score.json").read_text(encoding="utf-8"))
            self.assertEqual(score_doc["status"], "judge-failed")
            self.assertIsNone(score_doc["precision"])  # never a synthesized 0
            self.assertEqual(json.loads(r.stdout[r.stdout.index("{"):])["status"], "judge-failed")

    @unittest.skipUnless(RB_RESULTS.is_file(), "reviewbench oracle fixture required")
    def test_no_score_skips_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self._task(root, f"cp {self.RB_RESULTS} {{out}}")
            report = root / "given.md"
            report.write_text(REPORT_TEMPLATE.format(base="aaa", head="bbb"), encoding="utf-8")
            r = self._run_runner(task, report, "--no-score")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((task / "run" / "score.json").exists())
            self.assertNotIn("status", json.loads(r.stdout[r.stdout.index("{"):]))

    def test_candidate_without_findings_key_is_not_empty(self) -> None:
        # martian benchmark_data / candidates.json shapes carry no findings key;
        # emptiness is the judge's call, not the bridge's
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "benchmark_data.json"
            p.write_text(json.dumps({"https://example/pr/1": {"reviews": []}}), encoding="utf-8")
            self.assertEqual(score.read_candidate_status(p), "ok")


if __name__ == "__main__":
    unittest.main()
