"""Tests for the contracts.toml loader and validation (unit-001)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contracts.config import CONFIG_NAME, ConfigError, load_config, parse_config  # noqa: E402

VALID = """
[source]
tree = ["src"]

[inputs]
patterns = ["web:*"]

[rigid]
patterns = ["web:framework_handler"]
"""


class TestParseConfig(unittest.TestCase):
    def test_valid_minimal(self):
        cfg = parse_config({"source": {"tree": ["src"]}})
        self.assertEqual(cfg.source_trees, ("src",))
        self.assertEqual(cfg.inputs, ())
        self.assertEqual(cfg.lax, ())

    def test_valid_full(self):
        cfg = parse_config(
            {
                "source": {"tree": ["src", "lib"]},
                "inputs": {"patterns": ["a:b"]},
                "outputs": {"patterns": ["c:d"]},
                "lax": {"patterns": ["e:f"]},
                "rigid": {"patterns": ["a:b"]},
            }
        )
        self.assertEqual(cfg.source_trees, ("src", "lib"))
        self.assertEqual(cfg.inputs, ("a:b",))
        self.assertEqual(cfg.rigid, ("a:b",))  # independent axes: both allowed

    def test_missing_source_tree_refuses(self):
        with self.assertRaises(ConfigError) as cm:
            parse_config({})
        self.assertIn("[source] tree is required", str(cm.exception))

    def test_unknown_top_level_section_named(self):
        with self.assertRaises(ConfigError) as cm:
            parse_config({"source": {"tree": ["src"]}, "bogus": {}})
        self.assertIn("bogus", str(cm.exception))

    def test_patterns_must_be_strings(self):
        with self.assertRaises(ConfigError) as cm:
            parse_config({"source": {"tree": ["src"]}, "inputs": {"patterns": [1]}})
        self.assertIn("patterns", str(cm.exception))

    def test_unknown_key_named(self):
        with self.assertRaises(ConfigError) as cm:
            parse_config({"source": {"tree": ["src"], "extra": 1}})
        self.assertIn("extra", str(cm.exception))

    def test_all_errors_reported_together(self):
        with self.assertRaises(ConfigError) as cm:
            parse_config({"inputs": {"patterns": 3}, "nope": {}})
        msg = str(cm.exception)
        self.assertIn("[source] tree is required", msg)
        self.assertIn("patterns", msg)
        self.assertIn("nope", msg)


class TestLoadConfig(unittest.TestCase):
    def test_missing_file_refuses_naming_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as cm:
                load_config(Path(tmp))
        self.assertIn(CONFIG_NAME, str(cm.exception))
        self.assertIn("not found", str(cm.exception))

    def test_invalid_toml_refuses_naming_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / CONFIG_NAME).write_text("[source\ntree =", encoding="utf-8")
            with self.assertRaises(ConfigError) as cm:
                load_config(root)
        self.assertIn("not valid TOML", str(cm.exception))

    def test_invalid_semantics_refuse_naming_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / CONFIG_NAME).write_text("[inputs]\npatterns = []\n", encoding="utf-8")
            with self.assertRaises(ConfigError) as cm:
                load_config(root)
        self.assertIn("[source] tree is required", str(cm.exception))

    def test_valid_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / CONFIG_NAME).write_text(VALID, encoding="utf-8")
            cfg = load_config(root)
        self.assertEqual(cfg.source_trees, ("src",))
        self.assertEqual(cfg.inputs, ("web:*",))


if __name__ == "__main__":
    unittest.main()
