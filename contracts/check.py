"""`contracts check` — registry.md vs source (S2).

Regenerates the registry in memory and compares it with the on-disk file.
On drift, exits non-zero naming every added/removed call site (and added/
removed interfaces or unresolved targets). A missing registry.md is drift.
"""

from __future__ import annotations

from pathlib import Path

from . import generate as generate_mod
from .cli import EXIT_FAIL, EXIT_OK
from .generate import CallSite, Interface, UnresolvedTarget
from .registry import RegistryParseError, parse_registry


def _site_diff(old: set[CallSite], new: set[CallSite],
               label: str, problems: list[str]) -> None:
    for site in sorted(new - old, key=lambda s: (s.file, s.symbol)):
        problems.append(f"added call site   [{label}] {site.file}:{site.symbol}")
    for site in sorted(old - new, key=lambda s: (s.file, s.symbol)):
        problems.append(f"removed call site [{label}] {site.file}:{site.symbol}")


def compare_registries(old: str, new: str) -> list[str]:
    """Human-readable drift report; empty when identical."""
    if old == new:
        return []
    try:
        old_reg = parse_registry(old)
    except RegistryParseError as exc:
        return [f"registry.md does not parse: {exc}"]
    new_reg = parse_registry(new)
    problems: list[str] = []

    for ident in sorted(set(new_reg.interfaces) - set(old_reg.interfaces)):
        problems.append(f"added interface   [{ident}]")
        for site in sorted(new_reg.interfaces[ident].call_sites,
                           key=lambda s: (s.file, s.symbol)):
            problems.append(f"added call site   [{ident}] {site.file}:{site.symbol}")
    for ident in sorted(set(old_reg.interfaces) - set(new_reg.interfaces)):
        problems.append(f"removed interface [{ident}]")
        for site in sorted(old_reg.interfaces[ident].call_sites,
                           key=lambda s: (s.file, s.symbol)):
            problems.append(f"removed call site [{ident}] {site.file}:{site.symbol}")
    for ident in sorted(set(old_reg.interfaces) & set(new_reg.interfaces)):
        o, n = old_reg.interfaces[ident], new_reg.interfaces[ident]
        if (o.direction, o.authority) != (n.direction, n.authority):
            problems.append(
                f"changed interface [{ident}] "
                f"direction/authority {o.direction}/{o.authority} -> {n.direction}/{n.authority}"
            )
        _site_diff(o.call_sites, n.call_sites, ident, problems)

    for ident in sorted(set(new_reg.unresolved) - set(old_reg.unresolved)):
        problems.append(f"added unresolved target   [{ident}]")
    for ident in sorted(set(old_reg.unresolved) - set(new_reg.unresolved)):
        problems.append(f"removed unresolved target [{ident}]")
    for ident in sorted(set(old_reg.unresolved) & set(new_reg.unresolved)):
        _site_diff(old_reg.unresolved[ident].call_sites,
                   new_reg.unresolved[ident].call_sites, ident, problems)
    return problems


def check(root: Path, cfg) -> list[str]:
    """Return drift problems between on-disk registry.md and source."""
    registry_path = root / generate_mod.REGISTRY_NAME
    on_disk = registry_path.read_text(encoding="utf-8") if registry_path.is_file() else ""
    fresh = generate_mod.generate(root, cfg)
    return compare_registries(on_disk, fresh)


def main_check(args) -> int:
    import sys

    from .cli import find_repo_root
    from .resolutions import ResolutionError

    root = find_repo_root()
    try:
        problems = check(root, args.config)
    except ResolutionError as exc:
        print(f"contracts check: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if not problems:
        print("registry.md is up to date with source")
        return EXIT_OK
    print(f"registry.md is out of date ({len(problems)} problem(s)):")
    for p in problems:
        print(f"  {p}")
    print("run `contracts generate` to update")
    return EXIT_FAIL
