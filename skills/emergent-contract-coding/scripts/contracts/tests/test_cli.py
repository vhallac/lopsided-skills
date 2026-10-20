"""Black-box tests for the contracts CLI skeleton (unit-001)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Sibling test modules (test_generate) must be importable regardless of how
# the suite was invoked: as top-level modules (discover tests/) or as the
# tests package (python -m unittest from the package root).
sys.path.insert(0, str(Path(__file__).resolve().parent))


class TestCli(unittest.TestCase):
    def run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "contracts", *args],
            cwd=cwd or REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )

    def test_missing_config_refuses_with_config_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli("generate", cwd=Path(tmp))
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertIn("contracts.toml", proc.stderr)
        self.assertIn("no contracts.toml found", proc.stderr)

    def test_invalid_config_refuses_with_config_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "contracts.toml").write_text("[inputs]\n", encoding="utf-8")
            proc = self.run_cli("check", cwd=root)
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertIn("[source] tree is required", proc.stderr)

    def test_invalid_config_wins_over_missing_handler(self):
        # Config refusal (exit 3) happens before any subcommand behavior;
        # every command is implemented now, so resolve's own required flags
        # must not mask the config refusal.
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(
                "resolve", "--input", "in.toml", "--date", "2026-10-18",
                "--work-item", "#8", "--reason", "r", cwd=Path(tmp),
            )
        self.assertEqual(proc.returncode, 3)

    def test_success_output_is_human_readable_summary(self):
        # S8: success gives a human-readable summary line on stdout (exit 0).
        from test_generate import CONFIG, _write
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "contracts.toml").write_text(CONFIG, encoding="utf-8")
            _write(root, "src/pkg/api.py", "def api_create(x):\n    return x\n")
            proc = self.run_cli("generate", cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("registry written", proc.stdout)


class TestUsageAndHelp(unittest.TestCase):
    """S8: meaningful exit codes and usage/help text for every command."""

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "contracts", *args],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )

    def test_no_arguments_is_usage_error(self):
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stderr)

    def test_unknown_command_is_usage_error(self):
        proc = self.run_cli("frobnicate")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid choice", proc.stderr)

    def test_missing_required_flag_names_the_flag(self):
        proc = self.run_cli("affected")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--diff", proc.stderr)

    def test_log_without_subcommand_is_usage_error(self):
        proc = self.run_cli("log")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stderr)

    def test_top_level_help_lists_all_subcommands(self):
        proc = self.run_cli("--help")
        self.assertEqual(proc.returncode, 0)
        for cmd in ("generate", "check", "affected", "log", "resolve"):
            self.assertIn(cmd, proc.stdout + proc.stderr)

    def test_subcommand_help_mentions_flags(self):
        proc = self.run_cli("resolve", "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--input", proc.stdout)
        self.assertIn("--work-item", proc.stdout)


if __name__ == "__main__":
    unittest.main()
