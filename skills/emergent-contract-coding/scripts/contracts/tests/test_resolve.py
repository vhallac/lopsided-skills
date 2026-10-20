"""Tests for `contracts resolve` (S4) and resolution-aware generate."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, PACKAGE_ROOT)  # contracts package, whatever the cwd

from contracts.cli import EXIT_FAIL, EXIT_OK, main
from contracts.generate import _collect
from contracts.resolutions import (
    ResolutionError,
    load_resolutions,
    parse_resolutions_text,
    render_resolutions,
)

CONFIG = '[source]\ntree = ["src"]\n'

SRC_MAIN = (
    "import helpers\n"
    "import widgets\n"
    "\n"
    "def flow():\n"
    "    helpers.save(1)\n"
    "    obj.handle(2)\n"
)
SRC_HELPERS = "def save(x):\n    return x\n"
SRC_WIDGETS = "class Widget:\n    def handle(self, x):\n        return x\n"

GOOD_INPUT = """\
[[resolution]]
target = "obj.handle"
interface = "helpers:save"
"""


def _write_project(root: Path) -> None:
    (root / "contracts.toml").write_text(CONFIG, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text(SRC_MAIN, encoding="utf-8")
    (root / "src" / "helpers.py").write_text(SRC_HELPERS, encoding="utf-8")
    (root / "src" / "widgets.py").write_text(SRC_WIDGETS, encoding="utf-8")


def _run(argv, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    return subprocess.run(
        ["python3", "-m", "contracts", *argv], cwd=cwd, env=env,
        capture_output=True, text=True,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestParseResolutions(unittest.TestCase):
    def test_parse_roundtrip(self):
        text = render_resolutions(parse_resolutions_text(GOOD_INPUT, "in.toml"))
        again = parse_resolutions_text(text, "store.toml")
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0].target, "obj.handle")
        self.assertEqual(again[0].interface, "helpers:save")
        self.assertIsNone(again[0].call_site)

    def test_missing_outcome_rejected(self):
        with self.assertRaises(ResolutionError) as cm:
            parse_resolutions_text(
                '[[resolution]]\ntarget = "obj.handle"\n', "in.toml")
        self.assertIn("interface", str(cm.exception))

    def test_both_outcomes_rejected(self):
        with self.assertRaises(ResolutionError):
            parse_resolutions_text(
                '[[resolution]]\ntarget = "t"\ninterface = "a:b"\nexternal = true\n',
                "in.toml")

    def test_empty_target_rejected(self):
        with self.assertRaises(ResolutionError) as cm:
            parse_resolutions_text(
                '[[resolution]]\ntarget = ""\nexternal = true\n', "in.toml")
        self.assertIn("target", str(cm.exception))

    def test_bad_call_site_rejected(self):
        with self.assertRaises(ResolutionError) as cm:
            parse_resolutions_text(
                '[[resolution]]\ntarget = "t"\ncall_site = "nosymbol"\n'
                'external = true\n', "in.toml")
        self.assertIn("call_site", str(cm.exception))

    def test_invalid_toml_rejected(self):
        with self.assertRaises(ResolutionError) as cm:
            parse_resolutions_text("not toml ]", "in.toml")
        self.assertIn("TOML", str(cm.exception))

    def test_unknown_top_level_key_rejected(self):
        with self.assertRaises(ResolutionError) as cm:
            parse_resolutions_text('bogus = 1\n[[resolution]]\ntarget = "t"\n'
                                   'external = true\n', "in.toml")
        self.assertIn("bogus", str(cm.exception))


class TestResolve(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        self.root.mkdir()
        _write_project(self.root)
        self.input = self.root / "resolutions-input.toml"
        self.input.write_text(GOOD_INPUT, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _generate(self):
        self.assertEqual(_run(["generate"], self.root).returncode, EXIT_OK)

    def _registry(self):
        return (self.root / "registry.md").read_text(encoding="utf-8")

    def test_resolve_moves_site_into_interface_and_logs(self):
        self._generate()
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8",
                       "--reason", "obj.handle is Widget.handle via injection"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        registry = self._registry()
        self.assertNotIn("obj.handle", registry)
        self.assertIn("### helpers:save", registry)
        self.assertIn("src/main.py:flow", registry.split("### helpers:save")[1])
        decision = (self.root / "decision-log.md").read_text(encoding="utf-8")
        self.assertIn("| #8 | unresolved", decision)
        self.assertIn("obj.handle", decision)
        self.assertIn("reason: obj.handle is Widget.handle via injection", decision)
        # durable store written
        store = load_resolutions(self.root)
        self.assertEqual(len(store), 1)
        self.assertEqual(store[0].target, "obj.handle")

    def test_stdin_dash_input(self):
        """'-' reads the resolutions input from stdin (design decision 008)."""
        self._generate()
        result = subprocess.run(
            ["python3", "-m", "contracts", "resolve", "--input", "-",
             "--date", "2026-10-18", "--work-item", "#8", "--reason", "r"],
            cwd=self.root, env=dict(os.environ, PYTHONPATH=str(REPO_ROOT)),
            input=GOOD_INPUT, capture_output=True, text=True)
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        store = load_resolutions(self.root)
        self.assertEqual(len(store), 1)
        self.assertEqual(store[0].target, "obj.handle")

    def test_resolution_survives_regeneration_and_check_stays_green(self):
        self._generate()
        _run(["resolve", "--input", str(self.input), "--date", "2026-10-18",
              "--work-item", "#8", "--reason", "r"], self.root)
        self._generate()  # regenerate over the resolved registry
        self.assertNotIn("obj.handle", self._registry())
        check = _run(["check"], self.root)
        self.assertEqual(check.returncode, EXIT_OK, check.stdout + check.stderr)

    def test_external_resolution_drops_site(self):
        self.input.write_text(
            '[[resolution]]\ntarget = "obj.handle"\nexternal = true\n',
            encoding="utf-8")
        self._generate()
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8",
                       "--reason", "framework callback, not a contract call"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        registry = self._registry()
        self.assertNotIn("obj.handle", registry)

    def test_single_call_site_resolution(self):
        self.input.write_text(
            '[[resolution]]\ntarget = "obj.handle"\n'
            'call_site = "src/main.py:flow"\ninterface = "helpers:save"\n',
            encoding="utf-8")
        self._generate()
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        # only one call site exists for obj.handle, so the target empties out
        self.assertIn("## Unresolved\n\n(none)", self._registry())
        self.assertNotIn("obj.handle", self._registry())

    def test_unknown_target_rejected_names_entry(self):
        self._generate()
        self.input.write_text(
            '[[resolution]]\ntarget = "nope.thing"\nexternal = true\n',
            encoding="utf-8")
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("nope.thing", result.stderr)
        self.assertFalse((self.root / "resolutions.toml").exists())
        self.assertFalse((self.root / "decision-log.md").exists())

    def test_unknown_interface_rejected(self):
        self._generate()
        self.input.write_text(
            '[[resolution]]\ntarget = "obj.handle"\ninterface = "nope:thing"\n',
            encoding="utf-8")
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("nope:thing", result.stderr)

    def test_already_resolved_rejected(self):
        self._generate()
        _run(["resolve", "--input", str(self.input), "--date", "2026-10-18",
              "--work-item", "#8", "--reason", "r"], self.root)
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#9", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("already resolved", result.stderr)

    def test_invalid_entry_blocks_everything(self):
        self._generate()
        self.input.write_text(
            GOOD_INPUT + '[[resolution]]\ntarget = "nope"\nexternal = true\n',
            encoding="utf-8")
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertFalse((self.root / "resolutions.toml").exists())
        self.assertFalse((self.root / "decision-log.md").exists())

    def test_entry_invalidated_by_earlier_entry_rejected(self):
        """F1: entry #2 invalidated by entry #1 fails the pre-merge dry run;
        nothing is mutated and generate/check still succeed afterwards."""
        self._generate()
        self.input.write_text(
            GOOD_INPUT
            + '[[resolution]]\ntarget = "obj.handle"\nexternal = true\n',
            encoding="utf-8")
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8",
                       "--reason", "r"], self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("resolution #2", result.stderr)
        self.assertFalse((self.root / "resolutions.toml").exists())
        self.assertFalse((self.root / "decision-log.md").exists())
        self.assertEqual(_run(["generate"], self.root).returncode, EXIT_OK)
        self.assertEqual(_run(["check"], self.root).returncode, EXIT_OK)

    def test_duplicate_identical_entries_rejected(self):
        self._generate()
        self.input.write_text(GOOD_INPUT + GOOD_INPUT, encoding="utf-8")
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8",
                       "--reason", "r"], self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertFalse((self.root / "resolutions.toml").exists())

    def test_stale_store_rejected_before_mutation(self):
        """F1: an already-stale store rejects resolve up front (named error,
        nothing mutated) instead of failing mid-mutation in generate."""
        self._generate()
        _run(["resolve", "--input", str(self.input), "--date", "2026-10-18",
              "--work-item", "#8", "--reason", "r"], self.root)
        store_before = (self.root / "resolutions.toml").read_text(encoding="utf-8")
        log_before = (self.root / "decision-log.md").read_text(encoding="utf-8")
        # Remove the resolved call site from the source: store becomes stale.
        (self.root / "src" / "main.py").write_text(
            "import helpers\n\ndef flow():\n    helpers.save(1)\n",
            encoding="utf-8")
        (self.root / "registry.md").unlink()
        (self.root / "decision-log.md").unlink()
        self.input.write_text(
            '[[resolution]]\ntarget = "helpers.save"\nexternal = true\n',
            encoding="utf-8")
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-19", "--work-item", "#9",
                       "--reason", "r"], self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("stale", result.stderr)
        self.assertEqual((self.root / "resolutions.toml").read_text(encoding="utf-8"),
                         store_before)

    def test_bad_log_fields_rejected(self):
        self._generate()
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "18-10-2026", "--work-item", "#8", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("date", result.stderr)

    def test_empty_reason_rejected(self):
        self._generate()
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8", "--reason", " "],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("reason", result.stderr)

    def test_missing_input_file(self):
        self._generate()
        result = _run(["resolve", "--input", str(self.root / "absent.toml"),
                       "--date", "2026-10-18", "--work-item", "#8", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("not found", result.stderr)

    def test_empty_input_rejected(self):
        self._generate()
        self.input.write_text("", encoding="utf-8")
        result = _run(["resolve", "--input", str(self.input),
                       "--date", "2026-10-18", "--work-item", "#8", "--reason", "r"],
                      self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("no [[resolution]]", result.stderr)


class TestStaleResolutions(unittest.TestCase):
    """A stale store entry is drift: generate fails loudly, never silently."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        self.root.mkdir()
        _write_project(self.root)
        self.assertEqual(_run(["generate"], self.root).returncode, EXIT_OK)
        (self.root / "resolutions-input.toml").write_text(GOOD_INPUT, encoding="utf-8")
        self.assertEqual(_run(["resolve", "--input",
                               str(self.root / "resolutions-input.toml"),
                               "--date", "2026-10-18", "--work-item", "#8",
                               "--reason", "r"], self.root).returncode, EXIT_OK)

    def tearDown(self):
        self._tmp.cleanup()

    def test_stale_target_fails_generate(self):
        (self.root / "src" / "main.py").write_text(
            "import helpers\n\ndef flow():\n    helpers.save(1)\n",
            encoding="utf-8")
        result = _run(["generate"], self.root)
        self.assertEqual(result.returncode, EXIT_FAIL)
        self.assertIn("stale resolution", result.stderr)
        self.assertIn("obj.handle", result.stderr)

if __name__ == "__main__":
    unittest.main()
