"""Tests for `contracts generate` (S1/S3/S4): ast extraction, columns,
Unresolved section, byte determinism, black-box CLI behavior."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, PACKAGE_ROOT)  # contracts package, whatever the cwd

from contracts import config as config_mod
from contracts import generate as generate_mod

CONFIG = """\
[source]
tree = ["src"]

[inputs]
patterns = ["pkg.api:api_*"]

[rigid]
patterns = ["pkg.api:api_*", "ext:*"]
"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class GenerateUnitTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "contracts.toml").write_text(CONFIG, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def generate(self) -> str:
        cfg = config_mod.load_config(self.root)
        return generate_mod.generate(self.root, cfg)

    def test_extract_import_and_local_calls(self):
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", """\
def api_create(x):
    return x

def helper():
    return api_create(1)
""")
        _write(self.root, "src/app.py", """\
from pkg.api import api_create

def run():
    return api_create(2)
""")
        reg = self.generate()
        self.assertIn("### pkg.api:api_create", reg)
        self.assertIn("  - src/app.py:run", reg)
        self.assertIn("  - src/pkg/api.py:helper", reg)

    def test_direction_and_authority_independent(self):
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", """\
def api_create(x):
    return x

def plain():
    return 1

def caller():
    api_create(1)
    return plain()
""")
        reg = self.generate()
        block = reg.split("### pkg.api:api_create\n")[1].split("###")[0]
        self.assertIn("- direction: input", block)
        self.assertIn("- authority: rigid", block)
        block = reg.split("### pkg.api:plain\n")[1].split("###")[0]
        self.assertIn("- direction: internal", block)
        self.assertIn("- authority: lax", block)

    def test_unresolved_section_present(self):
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/app.py", """\
import extlib

def run(obj):
    obj.method()          # instance attribute: unresolved
    return extlib.fn()    # outside source trees: external, defaults to rigid
""")
        reg = self.generate()
        self.assertIn("## Unresolved", reg)
        self.assertIn("### obj.method", reg)
        self.assertIn("### extlib:fn", reg)
        self.assertIn("- authority: rigid", reg.split("### extlib:fn")[1].split("###")[0])
        self.assertIn("  - src/app.py:run", reg)

    def test_empty_unresolved_explicit(self):
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/m.py", """\
def f():
    pass

def g():
    return f()
""")
        reg = self.generate()
        self.assertIn("## Unresolved\n\n(none)", reg)

    def test_determinism_two_runs_byte_identical(self):
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", """\
def api_create(x):
    return x
""")
        _write(self.root, "src/app.py", """\
from pkg.api import api_create
import other

def run(obj):
    api_create(1)
    obj.m()
    return other.fn(2)
""")
        first = self.generate()
        second = self.generate()
        self.assertEqual(first, second)

    def test_stable_ordering_ignores_line_numbers(self):
        """Call site identity is file + symbol; reordering lines within a
        function must not change the registry."""
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", "def api_create(x):\n    return x\n")
        body_v1 = "from pkg.api import api_create\n\ndef run():\n    api_create(1)\n    api_create(2)\n"
        body_v2 = "from pkg.api import api_create\n\ndef run():\n    api_create(2)\n    api_create(1)\n\n# extra comment\n"
        _write(self.root, "src/app.py", body_v1)
        first = self.generate()
        _write(self.root, "src/app.py", body_v2)
        second = self.generate()
        self.assertEqual(first, second)


class GenerateCliTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "contracts.toml").write_text(CONFIG, encoding="utf-8")
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", "def api_create(x):\n    return x\n")
        _write(self.root, "src/app.py", "from pkg.api import api_create\n\ndef run():\n    return api_create(1)\n")

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv, cwd=None):
        env = dict(os.environ, PYTHONPATH=PACKAGE_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "contracts", *argv],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_generate_writes_registry_exit_zero(self):
        proc = self.run_cli("generate")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        reg = (self.root / "registry.md").read_text(encoding="utf-8")
        self.assertIn("### pkg.api:api_create", reg)
        self.assertIn("## Unresolved", reg)

    def test_generate_from_subdirectory_finds_root(self):
        proc = self.run_cli("generate", cwd=self.root / "src")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.root / "registry.md").is_file())

    def test_generated_registry_deterministic_via_cli(self):
        self.run_cli("generate")
        first = (self.root / "registry.md").read_bytes()
        self.run_cli("generate")
        second = (self.root / "registry.md").read_bytes()
        self.assertEqual(first, second)


class TestTsGuardDegradation(unittest.TestCase):
    """R2.F1 regression (PR !21 review round 2): _register_ts() must probe
    tree-sitter itself. Pre-fix it only imported ts_extract (which defers
    its tree-sitter imports to collect time), so the guard never fired and
    a mixed tree made `generate` crash with ModuleNotFoundError instead of
    degrading to a Python-only registry (SKILL.md: bare-environment rule,
    decision 009)."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "contracts.toml").write_text(CONFIG, encoding="utf-8")
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", "def api_create(x):\n    return x\n")
        _write(self.root, "src/app.py",
               "from pkg.api import api_create\n\ndef run():\n    return api_create(1)\n")
        _write(self.root, "src/ui.ts",
               'import { api_create } from "./pkg/api";\n\n'
               "export function render(): number {\n  return api_create(2);\n}\n")
        # Stub that makes `import tree_sitter` fail with ImportError no
        # matter whether the real dependency is installed: first position
        # on sys.path shadows any real install.
        self._stub = Path(self._tmp.name) / "_ts_stub"
        self._stub.mkdir()
        (self._stub / "tree_sitter.py").write_text(
            'raise ImportError("stubbed out for TestTsGuardDegradation")\n',
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(self._stub), PACKAGE_ROOT]
            + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
        )
        return subprocess.run(
            [sys.executable, "-m", "contracts", *argv],
            cwd=self.root,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_mixed_tree_degrades_to_python_only(self):
        proc = self.run_cli("generate")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        reg = (self.root / "registry.md").read_text(encoding="utf-8")
        self.assertIn("### pkg.api:api_create", reg)
        self.assertNotIn(".ts", reg)  # ui.ts unclaimed -> skipped


if __name__ == "__main__":
    unittest.main()
