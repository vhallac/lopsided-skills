#!/usr/bin/env python3
"""Black-box tests for herdr-drive (the report-tail gate)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("herdr-drive")

STUB = """#!/bin/sh
case "$1 $2" in
  "agent prompt") exit 0 ;;
  "agent read") cat "$HERDR_STUB_TAIL" ;;
  *) exit 3 ;;
esac
"""


def tail(status: str, issues: str) -> str:
    """A completion-report-shaped tail."""
    return (
        f"Status: {status}\n"
        "\n"
        "Open Issues:\n"
        f"- {issues}\n"
    )


class TestHerdrDriveGate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.stub_dir = self.tmp / "stub"
        self.stub_dir.mkdir()
        stub = self.stub_dir / "herdr"
        stub.write_text(STUB)
        stub.chmod(0o755)
        self.env = dict(os.environ, HERDR_STUB_TAIL="", PATH=f"{self.stub_dir}:{os.environ['PATH']}")

    def run_gate(self, report_tail: str) -> subprocess.CompletedProcess[str]:
        tail_file = self.tmp / "tail.txt"
        tail_file.write_text(report_tail)
        self.env["HERDR_STUB_TAIL"] = str(tail_file)
        return subprocess.run(
            [str(SCRIPT), "--agent", "a", "--issue", "1", "--plan", "p", "U1"],
            env=self.env, capture_output=True, text=True, timeout=30,
        )

    def test_single_block_none_is_done(self):
        r = self.run_gate(tail("DONE", "none"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("unit U1: DONE", r.stdout)

    def test_single_block_real_issue_escalates(self):
        r = self.run_gate(tail("DONE", "F3 — behavior drift in gate"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("ESCALATE DONE-with-open-issues (U1)", r.stdout)

    def test_two_unit_window_classifies_last_report(self):
        # A read window spanning two healthy reports must be classified from
        # the current unit's (last) report, not merged into one.
        r = self.run_gate(tail("DONE", "none") + "\n" + tail("DONE", "none"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("unit U1: DONE", r.stdout)

    def test_duplicate_headers_in_final_report_escalate(self):
        # Two Open Issues blocks inside the final report are ambiguous.
        r = self.run_gate(
            "Status: DONE\n\nOpen Issues:\n- none\n\nOpen Issues:\n- F3 behavior drift\n"
        )
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("ESCALATE UNPARSEABLE (multiple Open Issues blocks, U1)", r.stdout)

    def test_stale_none_before_last_report_not_done(self):
        # Falsification tail from the review: stale 'none' block first, fresh
        # real-issue block second. Must not be classified as clean.
        r = self.run_gate(tail("DONE", "none") + "\n" + tail("DONE", "U2 review finding"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("ESCALATE DONE-with-open-issues (U1)", r.stdout)

    def test_needs_input_escalates(self):
        r = self.run_gate(tail("NEEDS_INPUT", "none"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("ESCALATE NEEDS_INPUT (U1)", r.stdout)

    def test_no_status_line_escalates(self):
        r = self.run_gate("Open Issues:\n- none\n")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("ESCALATE UNPARSEABLE (no status line", r.stdout)


if __name__ == "__main__":
    unittest.main()
