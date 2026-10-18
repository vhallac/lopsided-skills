"""contracts.toml loader and validation (S3).

Config lives at the repository root as `contracts.toml`:

    [source]
    tree = ["src", "lib"]        # code outside these trees defaults to rigid

    [inputs]                     # input interfaces (glob patterns against
    patterns = ["module:qual"]   #   `module:qualname` identifiers)
    [outputs]
    patterns = [...]
    [lax]
    patterns = [...]
    [rigid]
    patterns = [...]

Direction and change authority are independent axes: an interface may appear
in both [inputs] and [rigid]. Unlisted source-tree code defaults to
internal/lax. Missing or invalid config refuses to run with a meaningful
error naming the problem.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "contracts.toml"

_SECTIONS = ("source", "inputs", "outputs", "lax", "rigid")
_PATTERN_SECTIONS = ("inputs", "outputs", "lax", "rigid")


class ConfigError(Exception):
    """Raised when contracts.toml is missing or invalid. Message names the problem."""


@dataclass(frozen=True)
class Config:
    source_trees: tuple[str, ...]
    inputs: tuple[str, ...] = field(default=())
    outputs: tuple[str, ...] = field(default=())
    lax: tuple[str, ...] = field(default=())
    rigid: tuple[str, ...] = field(default=())


def _load_table(data: dict, section: str, errors: list[str]) -> dict:
    raw = data.get(section, {})
    if not isinstance(raw, dict):
        errors.append(f"[{section}] must be a table, got {type(raw).__name__}")
        return {}
    return raw


def _load_patterns(raw: dict, section: str, errors: list[str]) -> tuple[str, ...]:
    pats = raw.get("patterns", [])
    if isinstance(pats, str):
        pats = [pats]
    if not isinstance(pats, list) or not all(isinstance(p, str) for p in pats):
        errors.append(f"[{section}] patterns must be a list of strings")
        return ()
    return tuple(pats)


def _validate_extra_keys(section: str, raw: dict, allowed: set[str], errors: list[str]) -> None:
    extra = set(raw) - allowed
    if extra:
        errors.append(f"[{section}] has unknown keys: {', '.join(sorted(extra))}")


def parse_config(data: dict) -> Config:
    """Validate an already-parsed TOML mapping; raises ConfigError on any problem."""
    errors: list[str] = []
    unknown = set(data) - set(_SECTIONS)
    if unknown:
        errors.append(f"unknown top-level sections: {', '.join(sorted(unknown))}")

    source = _load_table(data, "source", errors)
    _validate_extra_keys("source", source, {"tree"}, errors)
    tree = source.get("tree", ())
    if isinstance(tree, str):
        tree = [tree]
    if not isinstance(tree, list) or not all(isinstance(t, str) and t for t in tree):
        errors.append("[source] tree must be a non-empty list of path strings")
        tree = ()
    if not tree:
        errors.append("[source] tree is required (list of source directories)")

    axes: dict[str, tuple[str, ...]] = {}
    for section in _PATTERN_SECTIONS:
        table = _load_table(data, section, errors)
        _validate_extra_keys(section, table, {"patterns"}, errors)
        axes[section] = _load_patterns(table, section, errors) or ()

    if errors:
        raise ConfigError("invalid contracts.toml:\n  - " + "\n  - ".join(errors))
    return Config(
        source_trees=tuple(tree),
        inputs=axes["inputs"],
        outputs=axes["outputs"],
        lax=axes["lax"],
        rigid=axes["rigid"],
    )


def load_config(repo_root: Path) -> Config:
    """Load and validate contracts.toml from repo_root."""
    path = repo_root / CONFIG_NAME
    if not path.is_file():
        raise ConfigError(f"{CONFIG_NAME} not found at repository root: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_NAME} is not valid TOML: {exc}") from exc
    return parse_config(data)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0)
