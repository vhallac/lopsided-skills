"""Shared CLI plumbing: subcommand dispatch, exit codes, error conventions.

Exit codes (S8):
    0 — success
    1 — command-specific failure (drift, malformed entry, ...)
    2 — usage error
    3 — config missing/invalid (refuses to run)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_mod

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3

# Subcommand handlers; each maps to main_* with signature
# (args: argparse.Namespace) -> int.
# Lazy-registered handlers (imported in main() to avoid import cycles:
# subcommand modules import find_repo_root from here).
_LAZY_COMMANDS = {
    "generate": (".generate", "main_generate"),
    "check": (".check", "main_check"),
    "affected": (".affected", "main_affected"),
}


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default cwd) to the dir containing contracts.toml."""
    cur = (start or Path.cwd()).resolve()
    while True:
        if (cur / config_mod.CONFIG_NAME).is_file():
            return cur
        if cur.parent == cur:
            raise config_mod.ConfigError(
                f"no {config_mod.CONFIG_NAME} found between here and filesystem root"
            )
        cur = cur.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contracts",
        description="Contract substrate tooling: registry, logs, affected queries.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="generate registry.md from source")
    sub.add_parser("check", help="compare registry.md with source")
    p_affected = sub.add_parser("affected", help="list interfaces affected by a diff")
    p_affected.add_argument("--diff", required=True,
                            help="git ref to diff against, or a file of changed paths")
    p_affected.set_defaults(func_name="main_affected")
    sub.add_parser("log", help="append to or check decision/knowledge logs")
    sub.add_parser("resolve", help="apply resolutions to the registry Unresolved section")
    return parser


def load_config_or_fail(cwd: Path | None = None):
    """Load contracts.toml (searching upward); on failure print and return None."""
    try:
        root = find_repo_root(cwd)
        return config_mod.load_config(root)
    except config_mod.ConfigError as exc:
        print(f"contracts: refusing to run — {exc}", file=sys.stderr)
        return None


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Every command requires valid config; refuse before anything else (issue
    # #8 extension *.a: missing/invalid contracts.toml refuses to run).
    cfg = load_config_or_fail()
    if cfg is None:
        return EXIT_CONFIG
    args.config = cfg
    handler = _LAZY_COMMANDS.get(args.command)
    if handler is not None:
        import importlib

        mod_name, fn_name = handler
        handler = getattr(importlib.import_module(mod_name, __package__), fn_name)
    if handler is None:
        parser.error(f"command not implemented yet: {args.command}")
    return handler(args)
