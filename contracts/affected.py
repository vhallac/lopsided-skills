"""`contracts affected` — interfaces affected by a diff (S5).

Given a change set (a git ref diffed against the working tree, or a file
listing changed paths), reports the interfaces whose call sites touch the
changed files, with a liveness flag: an interface all of whose registered
call sites no longer exist in the source is "possibly dead".
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from typing import TextIO
from pathlib import Path

from . import generate as generate_mod
from .cli import EXIT_FAIL, EXIT_OK, EXIT_USAGE, find_repo_root
from .generate import CallSite
from .registry import parse_registry


@dataclass
class AffectedInterface:
    call_sites: set[CallSite] = field(default_factory=set)
    removed_sites: set[CallSite] = field(default_factory=set)

    @property
    def possibly_dead(self) -> bool:
        return bool(self.call_sites) and self.call_sites == self.removed_sites


def _changed_from_ref(root: Path, ref: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", ref],
        capture_output=True, text=True, check=True,
    )
    return [l for l in out.stdout.splitlines() if l]


def _changed_from_file(path: Path | TextIO) -> list[str]:
    text = path.read_text(encoding="utf-8") if isinstance(path, Path) else path.read()
    return [l.strip() for l in text.splitlines() if l.strip()]


def changed_files(root: Path, diff: str) -> list[str]:
    """Resolve --diff value: '-', a git ref, or a path to a newline-separated list."""
    if diff == "-":
        return _changed_from_file(sys.stdin)  # type: ignore[arg-type]
    candidate = root / diff
    if candidate.is_file():
        return _changed_from_file(candidate)
    return _changed_from_ref(root, diff)


def affected_interfaces(root: Path, registry_text: str, cfg,
                        changed: list[str]) -> dict[str, AffectedInterface]:
    """Interfaces with registered call sites in changed files + liveness.

    Liveness compares the on-disk registry with a fresh extraction from
    source: a call site that no longer appears in the source is removed;
    an interface whose registered call sites are all removed is possibly
    dead.
    """
    reg = parse_registry(registry_text)
    fresh_interfaces, fresh_unresolved = generate_mod._collect(root, cfg)
    fresh_reg = parse_registry(
        generate_mod.render_registry(fresh_interfaces, fresh_unresolved)
    )
    changed_set = set(changed)
    result: dict[str, AffectedInterface] = {}
    for ident, iface in reg.interfaces.items():
        sites_in_changed = {s for s in iface.call_sites if s.file in changed_set}
        if not sites_in_changed:
            continue
        info = result.setdefault(ident, AffectedInterface())
        info.call_sites = sites_in_changed
        fresh_sites = fresh_reg.interfaces.get(ident)
        fresh_set = fresh_sites.call_sites if fresh_sites else set()
        info.removed_sites = sites_in_changed - fresh_set
    return result


def render_affected(affected: dict[str, AffectedInterface]) -> str:
    if not affected:
        return "no affected interfaces"
    lines = [f"{len(affected)} affected interface(s):"]
    for ident in sorted(affected):
        info = affected[ident]
        state = "POSSIBLY DEAD" if info.possibly_dead else "live"
        lines.append(f"  {ident} ({state})")
        for site in sorted(info.call_sites, key=lambda s: (s.file, s.symbol)):
            mark = "removed" if site in info.removed_sites else "present"
            lines.append(f"    - {site.file}:{site.symbol} [{mark}]")
    return "\n".join(lines)


def main_affected(args) -> int:
    root = find_repo_root()
    registry_path = root / generate_mod.REGISTRY_NAME
    if not registry_path.is_file():
        print(f"contracts: no {generate_mod.REGISTRY_NAME} — run `contracts generate` first")
        return EXIT_FAIL
    try:
        changed = changed_files(root, args.diff)
    except subprocess.CalledProcessError as exc:
        print(
            f"contracts affected: invalid --diff ref {args.diff!r}: "
            f"git diff failed ({exc.stderr.strip() or 'unknown git error'})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    affected = affected_interfaces(
        root, registry_path.read_text(encoding="utf-8"), args.config, changed
    )
    print(render_affected(affected))
    return EXIT_OK
