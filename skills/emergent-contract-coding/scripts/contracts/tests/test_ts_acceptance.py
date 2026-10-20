"""TypeScript acceptance fixture run (unit-005): the Python acceptance
suite (test_acceptance.py) mirrored over a pure TypeScript fixture.

Covers, against one TS fixture, via the CLI only:
- generate is idempotent and byte-deterministic (S1)
- check is green when the registry matches source, exits non-zero on drift
  naming the offending call sites (S2)
- resolve binds an unresolved target (`<unresolvable>` from instance
  dispatch) to an interface, logs it, survives regeneration, and rejects
  unknown targets (S4 / unresolved-target handling)
- affected lists the interfaces hit by a diff with their call sites, and
  flags removed sites / possibly-dead interfaces (S5)
- log append validates and rejects malformed entries naming the field (S6)
- log check passes when logs only grew, fails non-zero when earlier content
  changed (S7)

Requires tree-sitter; skipped when the TS dependencies are absent.
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
patterns = ["web/api:apiCreate"]

[rigid]
patterns = ["web/api:apiCreate", "ext:*"]
"""

API_SRC = """\
export function apiCreate(x: number): number {
  return x;
}
"""

CALLER_SRC = """\
import { apiCreate } from "./api";

export function run(): number {
  return apiCreate(1);
}
"""

EXTRA_SRC = """\
import { save } from "./helpers";

export function flow(): number {
  save(1);
  return this.handle(2);
}
"""

HELPERS_SRC = """\
export function save(x: number): number {
  return x;
}
"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@unittest.skipUnless(HAS_TS, "tree-sitter dependencies not installed")
class TestTsAcceptance(unittest.TestCase):
    """End-to-end acceptance on a pure TypeScript fixture, via the CLI."""

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
                    p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p
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
        _write(self.root, "src/web/api.ts", API_SRC)
        _write(self.root, "src/web/index.ts", CALLER_SRC)

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
        self.assertIn("### web/api:apiCreate", text)
        self.assertIn("- src/web/index.ts:run", text)

    # --- S2: check green / drift -------------------------------------------

    def test_check_green_then_drift_names_sites(self):
        self.assertEqual(self.run_cli(self.root, "generate").returncode, 0)
        green = self.run_cli(self.root, "check")
        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        self.assertIn("up to date", green.stdout)

        # Drift: a new call site appears in source.
        _write(self.root, "src/web/other.ts",
               'import { apiCreate } from "./api";\n\n'
               "export function go(): number {\n    return apiCreate(2);\n}\n")
        drift = self.run_cli(self.root, "check")
        self.assertEqual(drift.returncode, 1, drift.stdout)
        self.assertIn("out of date", drift.stdout)
        self.assertIn("added call site", drift.stdout)
        self.assertIn("src/web/other.ts:go", drift.stdout)
        self.assertIn("run `contracts generate` to update", drift.stdout)

    # --- S4: resolve an unresolved target (instance dispatch) --------------

    def test_resolve_unresolvable_target_and_survives_regeneration(self):
        _write(self.root, "src/web/extra.ts", EXTRA_SRC)
        _write(self.root, "src/web/helpers.ts", HELPERS_SRC)
        self.assertEqual(self.run_cli(self.root, "generate").returncode, 0)
        reg = (self.root / "registry.md").read_text(encoding="utf-8")
        # save resolves through the relative import; this.handle is
        # instance dispatch -> <unresolvable>.
        self.assertIn("### web/helpers:save", reg)
        self.assertIn("- src/web/extra.ts:flow", reg)
        self.assertIn("<unresolvable>", reg)

        (self.root / "resolutions-input.toml").write_text(
            '[[resolution]]\ntarget = "<unresolvable>"\n'
            'interface = "web/helpers:save"\n', encoding="utf-8")
        proc = self.run_cli(
            self.root, "resolve", "--input",
            str(self.root / "resolutions-input.toml"),
            "--date", "2026-10-20", "--work-item", "#20",
            "--reason", "this.handle is bound to helpers.save via injection",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        registry = (self.root / "registry.md").read_text(encoding="utf-8")
        self.assertNotIn("<unresolvable>", registry)
        self.assertIn("### web/helpers:save", registry)
        self.assertIn("src/web/extra.ts:flow",
                      registry.split("### web/helpers:save")[1])
        decision = (self.root / "decision-log.md").read_text(encoding="utf-8")
        self.assertIn("| #20 | unresolved", decision)
        self.assertIn("<unresolvable>", decision)
        # Resolution survives regeneration; check stays green.
        self.assertEqual(self.run_cli(self.root, "generate").returncode, 0)
        self.assertNotIn("<unresolvable>",
                         (self.root / "registry.md").read_text(encoding="utf-8"))
        check = self.run_cli(self.root, "check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_resolve_unknown_target_rejected(self):
        self.assertEqual(self.run_cli(self.root, "generate").returncode, 0)
        (self.root / "resolutions-input.toml").write_text(
            '[[resolution]]\ntarget = "nope.thing"\nexternal = true\n',
            encoding="utf-8")
        proc = self.run_cli(
            self.root, "resolve", "--input",
            str(self.root / "resolutions-input.toml"),
            "--date", "2026-10-20", "--work-item", "#20", "--reason", "r",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("nope.thing", proc.stderr)
        self.assertFalse((self.root / "resolutions.toml").is_file())
        self.assertFalse((self.root / "decision-log.md").is_file())

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
                      affected(["src/web/unrelated.ts"]))

        # Change touching a call site: interface listed with the site.
        out = affected(["src/web/index.ts"])
        self.assertIn("web/api:apiCreate", out)
        self.assertIn("- src/web/index.ts:run [present]", out)

        # Call site removed from source while registry still has it:
        # flagged as removed, interface possibly dead.
        _write(self.root, "src/web/index.ts",
               "export function run(): number {\n    return 1;\n}\n")
        out = affected(["src/web/index.ts"])
        self.assertIn("- src/web/index.ts:run [removed]", out)
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
                           "--date", "18-10-2026", "--work-item", "#20",
                           "--kind", "merge", "--affected", "web/api:apiCreate",
                           "--decision", "d", "--reason", "r")
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn("rejected", bad.stderr)
        self.assertIn("date", bad.stderr)
        self.assertFalse((self.root / "decision-log.md").is_file(),
                         "rejected entry must not be written")

        # Valid append (S6).
        ok = self.run_cli(self.root, "log", "append", "--log", "decision",
                          "--date", "2026-10-19", "--work-item", "#20",
                          "--kind", "merge",
                          "--affected", "web/api:apiCreate",
                          "--decision", "merge a.B into c.d",
                          "--reason", "fits")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("appended to", ok.stdout)
        self.assertIn("decision-log.md", ok.stdout)

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


@unittest.skipUnless(HAS_TS, "tree-sitter dependencies not installed")
class TestTsExtractorFixes(unittest.TestCase):
    """Regression guards for review round 1 (PR !21): F1 deep `../..`
    import resolution, F2 .tsx parsing."""

    def _collect_tree(self, files: dict[str, str]) -> dict:
        from contracts import ts_extract

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)  # base doubles as the source-tree root
            for rel, text in files.items():
                p = base / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            entries = [
                (rel, base / rel, base) for rel in sorted(files)
            ]
            interfaces, unresolved, _ = ts_extract.collect(base, entries)
        return interfaces, unresolved

    def test_two_level_parent_import_resolves(self):
        """F1: `../../x` from src/services/orders.ts reaches src/x."""
        interfaces, _ = self._collect_tree({
            "core/deep/util.ts": "export function helper(): number {\n  return 1;\n}\n",
            "services/orders.ts": (
                'import { helper } from "../../core/deep/util";\n\n'
                "export function place(): number {\n  return helper();\n}\n"
            ),
        })
        self.assertIn("core/deep/util:helper", interfaces)
        self.assertEqual(
            {s.symbol for s in interfaces["core/deep/util:helper"].call_sites},
            {"place"},
        )

    def test_tsx_call_site_resolves(self):
        """F2: a .tsx file's JSX-embedded call site parses and resolves."""
        interfaces, unresolved = self._collect_tree({
            "src/web/handler.ts": "export function handler(): void {}\n",
            "src/web/button.tsx": (
                'import { handler } from "./handler";\n\n'
                "export function Button() {\n"
                "  return <div onClick={handler()}>ok</div>;\n"
                "}\n"
            ),
        })
        self.assertIn("src/web/handler:handler", interfaces)
        self.assertIn("src/web/button.tsx", {
            s.file for s in interfaces["src/web/handler:handler"].call_sites
        })


if __name__ == "__main__":
    unittest.main()
