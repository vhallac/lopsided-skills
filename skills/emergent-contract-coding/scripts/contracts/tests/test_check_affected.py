"""Tests for `contracts check` and `contracts affected` (S2/S5): drift
detection naming added/removed call sites, affected-interface query from a
diff, and the liveness flag when call sites are removed."""

import io
import os
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, PACKAGE_ROOT)  # contracts package, whatever the cwd

from contracts import config as config_mod
from contracts import generate as generate_mod
from contracts.check import check, compare_registries
from contracts.affected import affected_interfaces, changed_files, render_affected

CONFIG = """\
[source]
tree = ["src"]

[inputs]
patterns = ["pkg.api:api_*"]
"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


SRC_V1 = """\
from pkg.api import api_create

def run():
    return api_create(1)
"""
SRC_V2_ADDED = """\
from pkg.api import api_create

def run():
    return api_create(1)

def extra():
    return api_create(2)
"""
SRC_V2_REMOVED = "def run():\n    return 0\n"


class _Base(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "contracts.toml").write_text(CONFIG, encoding="utf-8")
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", "def api_create(x):\n    return x\n")
        _write(self.root, "src/app.py", SRC_V1)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        git = ["git", "-C", str(self.root),
               "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def cfg(self):
        return config_mod.load_config(self.root)


class StdinDiffTest(_Base):
    def test_changed_files_stdin_dash(self):
        """'--diff -' reads the changed-file list from stdin (decision 008)."""
        listing = "src/app.py\n\nsrc/pkg/api.py\n"
        (self.root / "changed.txt").write_text(listing, encoding="utf-8")
        expected = changed_files(self.root, str(self.root / "changed.txt"))
        with io.StringIO(listing) as fake_stdin, \
                unittest.mock.patch("sys.stdin", fake_stdin):
            got = changed_files(self.root, "-")
        self.assertEqual(got, expected)
        self.assertEqual(got, ["src/app.py", "src/pkg/api.py"])


class CheckTest(_Base):
    def test_no_drift_when_registry_current(self):
        _write(self.root, "registry.md", generate_mod.generate(self.root, self.cfg()))
        self.assertEqual(check(self.root, self.cfg()), [])

    def test_drift_names_added_call_site(self):
        _write(self.root, "registry.md", generate_mod.generate(self.root, self.cfg()))
        _write(self.root, "src/app.py", SRC_V2_ADDED)
        problems = check(self.root, self.cfg())
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("added call site", problems[0])
        self.assertIn("pkg.api:api_create", problems[0])
        self.assertIn("src/app.py:extra", problems[0])

    def test_drift_names_removed_call_site_and_dead_interface(self):
        _write(self.root, "registry.md", generate_mod.generate(self.root, self.cfg()))
        _write(self.root, "src/app.py", SRC_V2_REMOVED)
        problems = check(self.root, self.cfg())
        joined = "\n".join(problems)
        self.assertIn("removed call site", joined)
        self.assertIn("src/app.py:run", joined)

    def test_missing_registry_is_drift(self):
        problems = check(self.root, self.cfg())
        self.assertTrue(problems)
        self.assertIn("added call site", "\n".join(problems))

    def test_compare_identical_is_empty_and_added_interface_named(self):
        self.assertEqual(compare_registries("x", "x"), [])
        old = generate_mod.generate(self.root, self.cfg())
        _write(self.root, "src/pkg/api.py",
               "def api_create(x):\n    return x\n\ndef api_new():\n    pass\n\ndef caller():\n    return api_new()\n")
        new = generate_mod.generate(self.root, self.cfg())
        report = compare_registries(old, new)
        self.assertIn("added interface   [pkg.api:api_new]", report)
        self.assertIn("added call site   [pkg.api:api_new] src/pkg/api.py:caller", report)


class AffectedTest(_Base):
    def registry(self) -> str:
        return generate_mod.generate(self.root, self.cfg())

    def test_changed_file_lists_affected_interface(self):
        reg = self.registry()
        _write(self.root, "src/app.py", SRC_V2_ADDED)  # uncommitted change vs HEAD
        changed = changed_files(self.root, "HEAD")
        self.assertIn("src/app.py", changed)
        affected = affected_interfaces(self.root, reg, self.cfg(), changed)
        self.assertIn("pkg.api:api_create", affected)
        info = affected["pkg.api:api_create"]
        self.assertFalse(info.possibly_dead)
        self.assertIn("pkg.api:api_create", render_affected(affected))

    def test_unmodified_files_report_nothing(self):
        affected = affected_interfaces(self.root, self.registry(), self.cfg(), ["src/pkg/api.py"])
        self.assertEqual(affected, {})

    def test_removed_call_site_flags_possibly_dead(self):
        reg = self.registry()
        _write(self.root, "src/app.py", SRC_V2_REMOVED)
        affected = affected_interfaces(self.root, reg, self.cfg(), ["src/app.py"])
        info = affected["pkg.api:api_create"]
        self.assertTrue(info.possibly_dead)
        self.assertIn("POSSIBLY DEAD", render_affected(affected))
        self.assertIn("[removed]", render_affected(affected))

    def test_partial_removal_stays_live(self):
        reg = self.registry()
        # another caller still uses the interface (registered first)
        _write(self.root, "src/other.py", "from pkg.api import api_create\n\ndef go():\n    return api_create(9)\n")
        reg = self.registry()
        _write(self.root, "src/app.py", SRC_V2_REMOVED)
        affected = affected_interfaces(self.root, reg, self.cfg(), ["src/app.py", "src/other.py"])
        self.assertFalse(affected["pkg.api:api_create"].possibly_dead)

    def test_diff_file_input(self):
        reg = self.registry()
        listfile = self.root / "changed.txt"
        listfile.write_text("src/app.py\n", encoding="utf-8")
        changed = changed_files(self.root, "changed.txt")
        self.assertEqual(changed, ["src/app.py"])
        self.assertIn("pkg.api:api_create", affected_interfaces(self.root, reg, self.cfg(), changed))


class CheckAffectedCliTest(_Base):
    def run_cli(self, *argv, cwd=None):
        env = dict(os.environ, PYTHONPATH=PACKAGE_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "contracts", *argv],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_check_cli_green_then_red_on_drift(self):
        self.run_cli("generate")
        ok = self.run_cli("check")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        _write(self.root, "src/app.py", SRC_V2_ADDED)
        bad = self.run_cli("check")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("added call site", bad.stdout)
        self.assertIn("src/app.py:extra", bad.stdout)

    def test_affected_cli_reports_live_interface(self):
        self.run_cli("generate")
        _write(self.root, "src/app.py", SRC_V2_ADDED)  # uncommitted change vs HEAD
        proc = self.run_cli("affected", "--diff", "HEAD")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("pkg.api:api_create", proc.stdout)
        self.assertNotIn("POSSIBLY DEAD", proc.stdout)

    def test_affected_cli_requires_diff(self):
        proc = self.run_cli("affected")
        self.assertEqual(proc.returncode, 2)

    def test_affected_cli_bad_diff_ref_is_usage_error(self):
        """F2: an invalid --diff ref prints a named usage error, not a traceback."""
        self.run_cli("generate")
        proc = self.run_cli("affected", "--diff", "nosuchref")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid --diff ref", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
