"""Acceptance fixture run (unit-007): issue #8 acceptance demonstrated
end-to-end on a fixture repo.

Covers, against one fixture:
- generate is idempotent and byte-deterministic (S1)
- check is green when the registry matches source, exits non-zero on drift
  naming the offending call sites (S2)
- affected lists the interfaces hit by a diff with their call sites, and
  flags removed sites / possibly-dead interfaces (S5)
- log append validates and rejects malformed entries naming the field (S6)
- log check passes when logs only grew, fails non-zero when earlier content
  changed (S7)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    from contracts import ts_extract as _ts_probe
    _ts_probe._language()  # tree-sitter import is lazy: probe it
    HAS_TS = True
except ImportError:
    HAS_TS = False

CONFIG = """\
[source]
tree = ["src"]

[inputs]
patterns = ["pkg.api:api_*"]

[rigid]
patterns = ["pkg.api:api_*", "ext:*"]
"""

API_SRC = """\
def api_create(x):
    return x
"""

CALLER_SRC = """\
from pkg.api import api_create

def run():
    return api_create(1)
"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


CONFIG_MIXED = """\
[source]
tree = ["src"]

[inputs]
patterns = ["pkg.api:api_*", "web/api:apiCreate"]
"""

TS_API_SRC = """\
export function apiCreate(x: number): number {
  return x;
}
"""

TS_CALLER_SRC = """\
import { apiCreate } from "./api";

export function run(): number {
  return apiCreate(1);
}
"""

JS_UNCLAIMED_SRC = """\
export function apiCreate(x) {
  return x;
}
"""


class TestAcceptance(unittest.TestCase):
    """End-to-end acceptance on a fixture repo, via the CLI only."""

    def run_cli(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "contracts", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    q for q in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if q
                ),
            },
        )

    def git(self, root: Path, *argv: str) -> None:
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", *argv], cwd=root, check=True, env=env,
                       capture_output=True)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "contracts.toml").write_text(CONFIG, encoding="utf-8")
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", API_SRC)
        _write(self.root, "src/app.py", CALLER_SRC)

    # --- S1: generate, idempotence, byte determinism -----------------------

    def test_generate_is_idempotent_and_byte_deterministic(self):
        first = self.run_cli(self.root, "generate")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("registry written", first.stdout)
        reg = self.root / "registry.md"
        self.assertTrue(reg.is_file())
        bytes1 = reg.read_bytes()
        second = self.run_cli(self.root, "generate")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(bytes1, reg.read_bytes(),
                         "second generate must not change a single byte")
        # The registry records the call site under the api interface.
        text = reg.read_text(encoding="utf-8")
        self.assertIn("### pkg.api:api_create", text)
        self.assertIn("- src/app.py:run", text)

    # --- S2: check green / drift -------------------------------------------

    def test_check_green_then_drift_names_sites(self):
        self.assertEqual(self.run_cli(self.root, "generate").returncode, 0)
        green = self.run_cli(self.root, "check")
        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        self.assertIn("up to date", green.stdout)

        # Drift: a new call site appears in source.
        _write(self.root, "src/other.py",
               "from pkg.api import api_create\n\n\ndef go():\n"
               "    return api_create(2)\n")
        drift = self.run_cli(self.root, "check")
        self.assertEqual(drift.returncode, 1, drift.stdout)
        self.assertIn("out of date", drift.stdout)
        self.assertIn("added call site", drift.stdout)
        self.assertIn("src/other.py:go", drift.stdout)
        self.assertIn("run `contracts generate` to update", drift.stdout)

    def test_check_with_stale_store_fails_with_named_error(self):
        # F1: after a resolved call site is removed by an ordinary source
        # edit, check must fail with a named ResolutionError, not a raw
        # traceback (same contract as generate).
        root = self.root
        _write(root, "src/extra.py",
               "import helpers\n\n\ndef flow():\n"
               "    helpers.save(1)\n    obj.handle(2)\n")
        _write(root, "src/helpers.py", "def save(x):\n    return x\n")
        self.assertEqual(self.run_cli(root, "generate").returncode, 0)
        (root / "resolutions-input.toml").write_text(
            '[[resolution]]\ntarget = "obj.handle"\n'
            'interface = "helpers:save"\n', encoding="utf-8")
        proc = self.run_cli(
            root, "resolve", "--input", str(root / "resolutions-input.toml"),
            "--date", "2026-10-19", "--work-item", "#8",
            "--reason", "obj.handle is Widget.handle via injection",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Ordinary source edit removes the resolved call site.
        _write(root, "src/extra.py",
               "import helpers\n\n\ndef flow():\n    helpers.save(1)\n")
        stale = self.run_cli(root, "check")
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        self.assertIn("contracts check:", stale.stderr)
        self.assertIn("stale resolution", stale.stderr)
        self.assertNotIn("Traceback", stale.stderr)

    def test_resolve_prune_stale_recovers_store(self):
        # R2.F1 (recovery half): a stale store must be recoverable with a
        # supported command, not hand-editing resolutions.toml.
        root = self.root
        _write(root, "src/extra.py",
               "import helpers\n\n\ndef flow():\n"
               "    helpers.save(1)\n    obj.handle(2)\n    db.write(3)\n")
        _write(root, "src/helpers.py", "def save(x):\n    return x\n")
        self.assertEqual(self.run_cli(root, "generate").returncode, 0)
        (root / "resolutions-input.toml").write_text(
            '[[resolution]]\ntarget = "obj.handle"\n'
            'interface = "helpers:save"\n'
            '[[resolution]]\ntarget = "db.write"\n'
            'external = true\n', encoding="utf-8")
        proc = self.run_cli(
            root, "resolve", "--input", str(root / "resolutions-input.toml"),
            "--date", "2026-10-19", "--work-item", "#8",
            "--reason", "bind obj.handle; helpers.save is external",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Source edit removes the resolved call site -> one stale entry;
        # the external entry (no call site) stays valid.
        _write(root, "src/extra.py",
               "import helpers\n\n\ndef flow():\n"
               "    helpers.save(1)\n    db.write(3)\n")
        prune = self.run_cli(root, "resolve", "--prune-stale",
                             "--date", "2026-10-20", "--work-item", "#8",
                             "--reason", "call site removed by source edit")
        self.assertEqual(prune.returncode, 0, prune.stdout + prune.stderr)
        self.assertIn("pruned stale: [obj.handle]", prune.stdout)
        self.assertIn("kept 1 of 2 entries", prune.stdout)
        store_text = (root / "resolutions.toml").read_text(encoding="utf-8")
        self.assertNotIn('target = "obj.handle"', store_text)
        self.assertIn('target = "db.write"', store_text)
        log_text = (root / "decision-log.md").read_text(encoding="utf-8")
        self.assertIn("pruned stale resolution entries: [obj.handle]", log_text)
        # Store is clean again: check is green and a second prune is a no-op.
        self.assertEqual(self.run_cli(root, "check").returncode, 0)
        again = self.run_cli(root, "resolve", "--prune-stale",
                             "--date", "2026-10-21", "--work-item", "#8",
                             "--reason", "no-op")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("no stale entries", again.stdout)
        # --prune-stale and --input are mutually exclusive.
        both = self.run_cli(root, "resolve", "--prune-stale", "--input", "x.toml",
                            "--date", "2026-10-22", "--work-item", "#8",
                            "--reason", "conflict")
        self.assertEqual(both.returncode, 1, both.stderr)
        self.assertIn("mutually exclusive", both.stderr)

    # --- S5: affected query --------------------------------------------------

    def test_affected_lists_sites_and_flags_removals(self):
        self.assertEqual(self.run_cli(self.root, "generate").returncode, 0)

        def affected(paths: list[str]) -> str:
            changed = self.root / "changed.txt"
            changed.write_text("\n".join(paths) + "\n", encoding="utf-8")
            proc = self.run_cli(self.root, "affected", "--diff", "changed.txt")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout

        # Unrelated change: nothing affected.
        self.assertIn("no affected interfaces",
                      affected(["src/unrelated.py"]))

        # Change touching a call site: interface listed with the site.
        out = affected(["src/app.py"])
        self.assertIn("pkg.api:api_create", out)
        self.assertIn("- src/app.py:run [present]", out)

        # Call site removed from source while registry still has it:
        # flagged as removed, interface possibly dead.
        _write(self.root, "src/app.py", "def run():\n    return 1\n")
        out = affected(["src/app.py"])
        self.assertIn("- src/app.py:run [removed]", out)
        self.assertIn("POSSIBLY DEAD", out)

    # --- S6/S7: log append + append-only check -------------------------------

    def _commit_all(self) -> None:
        if not (self.root / ".git").is_dir():
            self.git(self.root, "init", "-q")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "c")

    def test_log_reject_malformed_append_and_append_only_check(self):
        self._commit_all()

        # Malformed entry rejected, failing field named (S6).
        bad = self.run_cli(self.root, "log", "append", "--log", "decision",
                           "--date", "18-10-2026", "--work-item", "#8",
                           "--kind", "merge", "--affected", "pkg.api:api_create",
                           "--decision", "d", "--reason", "r")
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn("rejected", bad.stderr)
        self.assertIn("date", bad.stderr)
        self.assertFalse((self.root / "decision-log.md").is_file(),
                         "rejected entry must not be written")

        unknown_kind = self.run_cli(self.root, "log", "append", "--log", "decision",
                                    "--date", "2026-10-18", "--work-item", "#8",
                                    "--kind", "rewrite", "--affected", "x",
                                    "--decision", "d", "--reason", "r")
        self.assertEqual(unknown_kind.returncode, 1)
        self.assertIn("kind", unknown_kind.stderr)

        # Valid appends to both logs (S6).
        ok = self.run_cli(self.root, "log", "append", "--log", "decision",
                          "--date", "2026-10-18", "--work-item", "#8",
                          "--kind", "merge", "--affected", "pkg.api:api_create",
                          "--decision", "merge a.B into c.d", "--reason", "fits")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("appended to", ok.stdout)
        self.assertIn("decision-log.md", ok.stdout)
        ok = self.run_cli(self.root, "log", "append", "--log", "knowledge",
                          "--date", "2026-10-18", "--work-item", "#8",
                          "--interfaces", "pkg.api:api_create",
                          "--outcome", "o", "--rationale", "r")
        self.assertEqual(ok.returncode, 0, ok.stderr)

        # Logs only grew since the commit → check passes (S7).
        growing = self.run_cli(self.root, "log", "check")
        self.assertEqual(growing.returncode, 0, growing.stdout + growing.stderr)
        self.assertIn("append-only check passed", growing.stdout)

        # Modify earlier content → check fails non-zero (S7).
        self._commit_all()
        log = self.root / "decision-log.md"
        text = log.read_text(encoding="utf-8")
        log.write_text(text.replace("merge a.B into c.d", "TAMPERED"),
                       encoding="utf-8")
        tampered = self.run_cli(self.root, "log", "check")
        self.assertEqual(tampered.returncode, 1, tampered.stdout)
        self.assertIn("earlier content modified", tampered.stdout + tampered.stderr)


if __name__ == "__main__":
    unittest.main()


class TestMixedLanguageAcceptance(unittest.TestCase):
    """Unit-004: a source tree holding Python and TypeScript files is
    accepted by config and handled end-to-end; files with unclaimed
    extensions (.js) are skipped. Requires tree-sitter for the TS half."""

    def setUp(self):
        if not HAS_TS:
            self.skipTest("tree-sitter dependencies not installed")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "contracts.toml").write_text(CONFIG_MIXED, encoding="utf-8")
        _write(self.root, "src/pkg/__init__.py", "")
        _write(self.root, "src/pkg/api.py", API_SRC)
        _write(self.root, "src/app.py", CALLER_SRC)
        _write(self.root, "src/web/api.ts", TS_API_SRC)
        _write(self.root, "src/web/index.ts", TS_CALLER_SRC)
        _write(self.root, "src/web/util.js", JS_UNCLAIMED_SRC)

    def run_cli(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "contracts", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    q for q in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if q
                ),
            },
        )

    def test_mixed_tree_end_to_end(self):
        # generate accepts the mixed tree and merges both extractors.
        first = self.run_cli(self.root, "generate")
        self.assertEqual(first.returncode, 0, first.stderr)
        reg = self.root / "registry.md"
        self.assertTrue(reg.is_file())
        text = reg.read_text(encoding="utf-8")
        # Python side of the mixed tree.
        self.assertIn("### pkg.api:api_create", text)
        self.assertIn("- src/app.py:run", text)
        # TypeScript side of the mixed tree.
        self.assertIn("### web/api:apiCreate", text)
        self.assertIn("- src/web/index.ts:run", text)
        # Unclaimed extension (.js) is skipped: no util.js call sites.
        self.assertNotIn("util.js", text)
        # Idempotent: a second generate is byte-identical.
        bytes1 = reg.read_bytes()
        second = self.run_cli(self.root, "generate")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(bytes1, reg.read_bytes())
        # check is green on the freshly generated registry.
        green = self.run_cli(self.root, "check")
        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        self.assertIn("up to date", green.stdout)
