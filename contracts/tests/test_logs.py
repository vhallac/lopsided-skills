"""Tests for log append (S6) and append-only check (S7)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from contracts.logs import (
    DECISION_LOG,
    KNOWLEDGE_LOG,
    LogEntryError,
    append_entry,
    build_decision_entry,
    build_knowledge_entry,
    check_append_only,
)
from contracts.cli import EXIT_FAIL, EXIT_OK, main


def _write_config(root: Path) -> None:
    (root / "contracts.toml").write_text(
        '[source]\ntree = ["src"]\n', encoding="utf-8"
    )


def _init_git_repo(root: Path) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    def git(*argv):
        subprocess.run(["git", *argv], cwd=root, check=True, env=env,
                       capture_output=True)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "init")


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write_config(self.root)
        os.chdir(self.root)
        self.addCleanup(self._tmp.cleanup)


class TestBuildEntry(unittest.TestCase):
    def test_valid_decision_entry(self):
        entry = build_decision_entry(
            "2026-10-18", "issue-8", "merge", ["a.B", "c.d"],
            "merge a.B into c.d", "whole contract fits",
        )
        self.assertIn("## 2026-10-18 | issue-8 | merge\n", entry)
        self.assertIn("- affected: a.B, c.d\n", entry)
        self.assertIn("- reason: whole contract fits\n", entry)

    def test_unknown_kind_rejected_naming_field(self):
        with self.assertRaises(LogEntryError) as cm:
            build_decision_entry("2026-10-18", "issue-8", "rewrite",
                                 ["a"], "x", "y")
        self.assertIn("kind", str(cm.exception))

    def test_bad_date_rejected_naming_field(self):
        with self.assertRaises(LogEntryError) as cm:
            build_decision_entry("18-10-2026", "issue-8", "fix", ["a"], "x", "y")
        self.assertIn("date", str(cm.exception))

    def test_empty_reason_rejected_naming_field(self):
        with self.assertRaises(LogEntryError) as cm:
            build_decision_entry("2026-10-18", "issue-8", "fix", ["a"], "x", "  ")
        self.assertIn("reason", str(cm.exception))

    def test_empty_affected_rejected_naming_field(self):
        with self.assertRaises(LogEntryError) as cm:
            build_decision_entry("2026-10-18", "issue-8", "fix", [], "x", "y")
        self.assertIn("affected", str(cm.exception))

    def test_knowledge_entry_valid_and_bad_rationale_rejected(self):
        entry = build_knowledge_entry("2026-10-18", "issue-8", ["a.B"],
                                      "kept separate", "different change rates")
        self.assertIn("| knowledge\n", entry)
        self.assertIn("- outcome: kept separate\n", entry)
        with self.assertRaises(LogEntryError) as cm:
            build_knowledge_entry("2026-10-18", "issue-8", ["a.B"], "o", "")
        self.assertIn("rationale", str(cm.exception))


class TestAppend(_Base):
    def test_append_creates_and_grows(self):
        first = build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d1", "r1")
        append_entry(self.root, DECISION_LOG, first)
        second = build_decision_entry("2026-10-18", "i2", "fix", ["b"], "d2", "r2")
        append_entry(self.root, DECISION_LOG, second)
        text = (self.root / DECISION_LOG).read_text(encoding="utf-8")
        self.assertIn(first, text)
        self.assertTrue(text.endswith(second))

    def test_append_to_file_without_trailing_newline(self):
        (self.root / DECISION_LOG).write_text("old entry no newline", encoding="utf-8")
        entry = build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d", "r")
        append_entry(self.root, DECISION_LOG, entry)
        text = (self.root / DECISION_LOG).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("old entry no newline\n"))


class TestAppendOnlyCheck(_Base):
    def test_unchanged_log_ok(self):
        entry = build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d", "r")
        append_entry(self.root, DECISION_LOG, entry)
        (self.root / KNOWLEDGE_LOG).write_text("", encoding="utf-8")
        _init_git_repo(self.root)
        self.assertEqual(check_append_only(self.root, [DECISION_LOG, KNOWLEDGE_LOG]), [])

    def test_appended_only_ok(self):
        append_entry(self.root, DECISION_LOG,
                     build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d", "r"))
        _init_git_repo(self.root)
        append_entry(self.root, DECISION_LOG,
                     build_decision_entry("2026-10-18", "i2", "fix", ["b"], "d2", "r2"))
        self.assertEqual(check_append_only(self.root, [DECISION_LOG]), [])

    def test_modification_of_earlier_content_detected(self):
        append_entry(self.root, DECISION_LOG,
                     build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d", "r"))
        _init_git_repo(self.root)
        path = self.root / DECISION_LOG
        path.write_text(path.read_text(encoding="utf-8").replace("d", "EDITED"),
                        encoding="utf-8")
        violations = check_append_only(self.root, [DECISION_LOG])
        self.assertEqual(len(violations), 1)
        self.assertIn(DECISION_LOG, violations[0])

    def test_truncation_detected(self):
        append_entry(self.root, DECISION_LOG,
                     build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d", "r"))
        append_entry(self.root, DECISION_LOG,
                     build_decision_entry("2026-10-18", "i2", "fix", ["b"], "d2", "r2"))
        _init_git_repo(self.root)
        (self.root / DECISION_LOG).write_text("", encoding="utf-8")
        self.assertEqual(len(check_append_only(self.root, [DECISION_LOG])), 1)

    def test_deletion_detected(self):
        append_entry(self.root, DECISION_LOG,
                     build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d", "r"))
        _init_git_repo(self.root)
        (self.root / DECISION_LOG).unlink()
        self.assertEqual(len(check_append_only(self.root, [DECISION_LOG])), 1)

    def test_base_content_injection(self):
        violations = check_append_only(
            self.root, [DECISION_LOG],
            base_content={DECISION_LOG: "committed\n"})
        self.assertEqual(len(violations), 1)


class TestLogCLI(_Base):
    def test_append_via_cli_writes_entry(self):
        rc = main(["log", "append", "--log", "decision", "--date", "2026-10-18",
                   "--work-item", "issue-8", "--kind", "fix",
                   "--affected", "a.B", "--decision", "d", "--reason", "r"])
        self.assertEqual(rc, EXIT_OK)
        text = (self.root / DECISION_LOG).read_text(encoding="utf-8")
        self.assertIn("## 2026-10-18 | issue-8 | fix\n", text)

    def test_append_malformed_rejected_with_failing_field(self):
        rc = main(["log", "append", "--log", "decision", "--date", "bad",
                   "--work-item", "issue-8", "--kind", "fix",
                   "--affected", "a", "--decision", "d", "--reason", "r"])
        self.assertEqual(rc, EXIT_FAIL)
        self.assertFalse((self.root / DECISION_LOG).exists())

    def test_append_unknown_kind_rejected(self):
        rc = main(["log", "append", "--log", "decision", "--date", "2026-10-18",
                   "--work-item", "issue-8", "--kind", "nope",
                   "--affected", "a", "--decision", "d", "--reason", "r"])
        self.assertEqual(rc, EXIT_FAIL)

    def test_knowledge_append_via_cli(self):
        rc = main(["log", "append", "--log", "knowledge", "--date", "2026-10-18",
                   "--work-item", "issue-8", "--interfaces", "a.B, c.d",
                   "--outcome", "kept", "--rationale", "rates differ"])
        self.assertEqual(rc, EXIT_OK)
        text = (self.root / KNOWLEDGE_LOG).read_text(encoding="utf-8")
        self.assertIn("- interfaces: a.B, c.d\n", text)

    def test_check_ok_then_fail_on_truncation(self):
        append_entry(self.root, DECISION_LOG,
                     build_decision_entry("2026-10-18", "i1", "fix", ["a"], "d", "r"))
        _init_git_repo(self.root)
        self.assertEqual(main(["log", "check"]), EXIT_OK)
        (self.root / DECISION_LOG).write_text("## tampered\n", encoding="utf-8")
        self.assertEqual(main(["log", "check"]), EXIT_FAIL)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
