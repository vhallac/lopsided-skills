"""registry.md parsing (round-trip of generate.render_registry).

Used by `check` (compare on-disk registry with a fresh regeneration) and
`affected` (query call sites per changed file). The parser mirrors the
renderer's structure exactly; a registry that does not parse is a hard
failure — registry.md is generated, never hand-edited (S9).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .generate import CallSite, Interface, UnresolvedTarget


class RegistryParseError(Exception):
    """Raised when registry.md does not match the generated structure."""


@dataclass
class Registry:
    interfaces: dict[str, Interface] = field(default_factory=dict)
    unresolved: dict[str, UnresolvedTarget] = field(default_factory=dict)


def _parse_call_site(text: str) -> CallSite:
    """Parse `  - file:symbol` into a CallSite (last colon splits symbol)."""
    body = text.strip()
    if not body.startswith("- "):
        raise RegistryParseError(f"bad call-site line: {text!r}")
    rest = body[2:]
    file, sep, symbol = rest.rpartition(":")
    if not sep or not file:
        raise RegistryParseError(f"bad call-site line: {text!r}")
    return CallSite(file=file, symbol=symbol)


def parse_registry(text: str) -> Registry:
    reg = Registry()
    section: str | None = None  # "interfaces" | "unresolved"
    current: str | None = None  # current identifier
    target: Interface | UnresolvedTarget | None = None
    in_list = False

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("<!--"):
            continue
        if line == "# Interface registry":
            continue
        if line.startswith("## "):
            name = line[3:].strip()
            if name == "Interfaces":
                section, current, target, in_list = "interfaces", None, None, False
            elif name == "Unresolved":
                section, current, target, in_list = "unresolved", None, None, False
            else:
                raise RegistryParseError(f"unknown section: {line!r}")
            continue
        if line.startswith("### "):
            current = line[4:].strip()
            if section == "interfaces":
                target = reg.interfaces.setdefault(current, Interface())
            elif section == "unresolved":
                target = reg.unresolved.setdefault(current, UnresolvedTarget())
            else:
                raise RegistryParseError(f"heading outside any section: {line!r}")
            in_list = False
            continue
        if line.startswith("- "):
            body = line[2:]
            if body == "call sites:":
                in_list = True
                continue
            key, _, value = body.partition(": ")
            if key == "direction" and isinstance(target, Interface):
                target.direction = value
                continue
            if key == "authority" and isinstance(target, Interface):
                target.authority = value
                continue
            raise RegistryParseError(f"unexpected list item: {line!r}")
        if line.startswith("  - ") and in_list and target is not None:
            target.call_sites.add(_parse_call_site(line))
            continue
        if line == "(none)":
            continue
        raise RegistryParseError(f"unexpected line: {line!r}")
    return reg
