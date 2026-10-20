"""Tests for the TypeScript extractor (tree-sitter): definitions, call
sites, import bindings, Unresolved section, and S3 rigid default.
Skipped when py-tree-sitter / tree-sitter-typescript is not installed."""

import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, PACKAGE_ROOT)  # contracts package, whatever the cwd

from contracts import config as config_mod
from contracts import generate as generate_mod

try:
    from contracts import ts_extract
    ts_extract._language()  # tree-sitter import is lazy: probe it
    HAS_TS = True
except ImportError:
    HAS_TS = False

CONFIG = """\
[source]
tree = ["src"]

[inputs]
patterns = ["services/api:*"]

[rigid]
patterns = ["services/api:api_*"]
"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@unittest.skipUnless(HAS_TS, "tree-sitter dependencies not installed")
class TsExtractUnitTest(unittest.TestCase):
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

    def test_import_named_default_and_local_calls(self):
        _write(self.root, "src/services/api.ts", """\
export function api_create(x: number): number {
    return x;
}

export function helper(): number {
    return api_create(1);
}

export const initialized: boolean = api_create(0) > 0;
""")
        _write(self.root, "src/app.ts", """\
import { api_create, helper as h } from "./services/api";
import api from "./services/api";

export function run(): void {
    api_create(2);
    h();
    api.helper();
}
""")
        text = self.generate()
        self.assertIn("### services/api:api_create", text)
        self.assertIn("### services/api:helper", text)
        # named import call site
        self.assertIn("- src/app.ts:run", text)
        # same-module call site
        self.assertIn("- src/services/api.ts:helper", text)
        self.assertIn("- src/services/api.ts:<module>", text)
        # default import binds to the module itself: api.helper() -> services/api:helper
        self.assertIn("### services/api:helper", text)

    def test_class_and_method_definitions(self):
        _write(self.root, "src/services/orders.ts", """\
export class OrderService {
    static create(): OrderService {
        return new OrderService();
    }
    place(): void {
        this.validate();
    }
    validate(): void {}
}
""")
        _write(self.root, "src/app.ts", """\
import { OrderService } from "./services/orders";

export function run(): void {
    OrderService.create();
}
""")
        text = self.generate()
        self.assertIn("### services/orders:OrderService.create", text)
        self.assertIn("- src/app.ts:run", text)
        # this.validate() is instance dispatch: <unresolvable>, like
        # Python's obj.method(); the enclosing method is the call-site symbol
        self.assertIn("### <unresolvable>", text)
        self.assertIn("- src/services/orders.ts:OrderService.place", text)

    def test_unresolved_targets(self):
        _write(self.root, "src/app.ts", """\
import { missing } from "@/alias/path";

export function run(): void {
    missing();
    const obj = getObj();
    obj.method();
}
""")
        text = self.generate()
        self.assertIn("## Unresolved", text)
        self.assertIn("### missing", text)
        self.assertIn("### obj.method", text)
        self.assertIn("### getObj", text)

    def test_s3_rigid_default_outside_source_trees(self):
        _write(self.root, "src/app.ts", """\
import { helper } from "./services/api";

export function run(): void {
    helper();
}
""")
        _write(self.root, "src/services/api.ts", """\
export function helper(): void {}
""")
        text = self.generate()
        self.assertIn("### services/api:helper", text)
        lines = text.splitlines()
        section = [l for l in lines if l.startswith("### services/api:helper")]
        idx = lines.index(section[0])
        block = "\n".join(lines[idx:idx + 4])
        self.assertIn("- authority: lax", block)
