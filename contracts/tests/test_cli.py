"""Black-box tests for the contracts CLI skeleton (unit-001)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


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

    def test_implemented_commands_absent_skeleton(self):
        # Skeleton: commands are registered but no handlers yet; the CLI must
        # fail with a meaningful message (not a traceback) for now.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "contracts.toml").write_text(
                '[source]\ntree = ["src"]\n', encoding="utf-8"
            )
            proc = self.run_cli("generate", cwd=root)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not implemented", (proc.stderr + proc.stdout).lower())

    def test_invalid_config_wins_over_missing_handler(self):
        # Config refusal (exit 3) happens regardless of subcommand handler state.
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli("log", cwd=Path(tmp))
        self.assertEqual(proc.returncode, 3)


if __name__ == "__main__":
    unittest.main()
