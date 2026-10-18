"""Resolutions for Unresolved call sites (S4).

Unresolved call sites (dynamic dispatch, reflection, framework callbacks)
are resolved through a resolutions input file read by `contracts resolve`.
Each applied resolution is persisted in `resolutions.toml` at the repository
root and consumed by `generate`, so a resolution survives regeneration and
`check` stays green after `resolve`. Every applied resolution also appends
a decision-log entry (kind `unresolved`, R4: the question and its later
resolution).

Store / input format (TOML, one [[resolution]] per entry):

    [[resolution]]
    target    = "obj.notify"          # unresolved target identifier
    call_site = "src/app.py:handler"  # optional; absent = all call sites
    interface = "app:notify"          # assign to this interface ...
    # external = true                 # ... or declare it not a contract call

Exactly one of `interface` / `external` is required per entry.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

RESOLUTIONS_NAME = "resolutions.toml"


class ResolutionError(Exception):
    """Invalid resolutions file or resolution entry; message names the problem."""


@dataclass(frozen=True)
class Resolution:
    target: str
    interface: str | None  # None when external
    call_site: CallSite | None  # None = every call site of the target
    external: bool

    @property
    def key(self) -> tuple[str, str | None]:
        """Identity: one resolution per (target, call site)."""
        return (self.target, self.call_site.file if self.call_site else None)

    def describe(self) -> str:
        site = f"{self.call_site.file}:{self.call_site.symbol}" if self.call_site \
            else "(all call sites)"
        outcome = "external" if self.external else f"interface {self.interface}"
        return f"[{self.target}] {site} -> {outcome}"


def parse_resolutions_text(text: str, source_name: str) -> list[Resolution]:
    """Parse and validate a resolutions TOML document; raises ResolutionError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ResolutionError(f"{source_name} is not valid TOML: {exc}") from exc
    raw_entries = data.get("resolution", [])
    if not isinstance(raw_entries, list):
        raise ResolutionError(f"{source_name}: [[resolution]] must be an array of tables")
    unknown = set(data) - {"resolution"}
    if unknown:
        raise ResolutionError(
            f"{source_name}: unknown top-level keys: {', '.join(sorted(unknown))}"
        )
    resolutions: list[Resolution] = []
    for i, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ResolutionError(f"{source_name}: resolution #{i + 1} must be a table")
        prefix = f"{source_name}: resolution #{i + 1}"
        target = raw.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ResolutionError(f"{prefix}: invalid field 'target': non-empty string required")
        interface = raw.get("interface")
        external = raw.get("external", False)
        if (interface is None) == (not external):
            raise ResolutionError(
                f"{prefix}: exactly one of 'interface' or 'external = true' is required"
            )
        if interface is not None and (not isinstance(interface, str) or not interface.strip()):
            raise ResolutionError(f"{prefix}: invalid field 'interface': non-empty string required")
        if not isinstance(external, bool):
            raise ResolutionError(f"{prefix}: invalid field 'external': boolean required")
        call_site = None
        if raw.get("call_site") is not None:
            from .generate import CallSite  # lazy: generate imports this module
            raw_site = raw["call_site"]
            if not isinstance(raw_site, str) or raw_site.count(":") < 1:
                raise ResolutionError(
                    f"{prefix}: invalid field 'call_site': expected 'file:symbol'"
                )
            file, _, symbol = raw_site.rpartition(":")
            if not file or not symbol:
                raise ResolutionError(
                    f"{prefix}: invalid field 'call_site': expected 'file:symbol'"
                )
            call_site = CallSite(file=file, symbol=symbol)
        resolutions.append(Resolution(
            target=target.strip(),
            interface=interface.strip() if interface else None,
            call_site=call_site,
            external=bool(external),
        ))
    return resolutions


def load_resolutions(repo_root: Path) -> list[Resolution]:
    """Load the durable resolutions store; empty list when the file is absent."""
    path = repo_root / RESOLUTIONS_NAME
    if not path.is_file():
        return []
    return parse_resolutions_text(path.read_text(encoding="utf-8"), RESOLUTIONS_NAME)


def render_resolutions(resolutions: list[Resolution]) -> str:
    """Deterministic TOML rendering of the resolutions store."""
    lines: list[str] = []
    for r in sorted(resolutions, key=lambda r: (r.target,
                                                r.call_site.file if r.call_site else "",
                                                r.call_site.symbol if r.call_site else "")):
        lines.append("[[resolution]]")
        lines.append(f'target = "{r.target}"')
        if r.call_site is not None:
            lines.append(f'call_site = "{r.call_site.file}:{r.call_site.symbol}"')
        if r.external:
            lines.append("external = true")
        else:
            lines.append(f'interface = "{r.interface}"')
        lines.append("")
    return "\n".join(lines)


def save_resolutions(repo_root: Path, resolutions: list[Resolution]) -> Path:
    path = repo_root / RESOLUTIONS_NAME
    path.write_text(render_resolutions(resolutions), encoding="utf-8")
    return path
