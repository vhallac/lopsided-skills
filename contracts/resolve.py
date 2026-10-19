"""`contracts resolve` — apply resolutions to Unresolved call sites (S4).

Reads a resolutions input file, validates every entry against the current
source-derived Unresolved section (nothing is mutated when any entry is
invalid — the error names the entry and field), merges valid entries into
the durable `resolutions.toml`, regenerates `registry.md`, and appends one
decision-log entry (kind `unresolved`: the question and its later
resolution, R4) per applied resolution.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import generate as generate_mod
from .cli import EXIT_FAIL, EXIT_OK, find_repo_root
from .generate import UnresolvedTarget
from .generate import REGISTRY_NAME
from .logs import DECISION_LOG, LogEntryError, append_entry, build_decision_entry
from .resolutions import (
    RESOLUTIONS_NAME,
    Resolution,
    ResolutionError,
    load_resolutions,
    parse_resolutions_text,
    save_resolutions,
)


def _validate_against_source(entries: list[Resolution], existing_keys: set,
                             interfaces, unresolved) -> None:
    """Reject any entry that cannot be applied; message names entry and field.

    existing_keys is updated in place with each entry's key, so duplicate
    keys within the input file are rejected too.
    """
    for i, r in enumerate(entries):
        prefix = f"resolution #{i + 1} ({r.describe()})"
        if r.key in existing_keys:
            raise ResolutionError(f"{prefix}: already resolved in {RESOLUTIONS_NAME}")
        existing_keys.add(r.key)
        sites: UnresolvedTarget | None = unresolved.get(r.target)
        if sites is None:
            raise ResolutionError(
                f"{prefix}: unknown unresolved target [{r.target}] — run `contracts generate` "
                f"and check the registry's Unresolved section"
            )
        if r.call_site is not None and r.call_site not in sites.call_sites:
            raise ResolutionError(
                f"{prefix}: [{r.target}] has no call site "
                f"{r.call_site.file}:{r.call_site.symbol}"
            )
        if not r.external and r.interface not in interfaces:
            raise ResolutionError(
                f"{prefix}: unknown interface {r.interface} — resolutions may only "
                f"assign call sites to interfaces that exist"
            )


def _prune_stale(root, args) -> int:
    """Recovery path (R2.F1): drop stale entries from resolutions.toml.

    Every store entry is replayed against a fresh source snapshot, one at a
    time; entries that fail are stale. Nothing is mutated unless the pruned
    store still applies cleanly — then the store is saved, the registry is
    regenerated, and one decision-log entry records the pruned targets.
    """
    store = load_resolutions(root)
    interfaces, unresolved = generate_mod._collect(root, args.config)
    def _snapshot() -> tuple[dict, dict]:
        return (
            {k: v for k, v in interfaces.items()},
            {k: UnresolvedTarget(set(v.call_sites)) for k, v in unresolved.items()},
        )

    kept: list[Resolution] = []
    pruned: list[Resolution] = []
    scratch_interfaces, scratch_unresolved = _snapshot()
    fresh_interfaces, fresh_unresolved = _snapshot()
    for r in store:
        try:
            generate_mod.apply_resolutions(scratch_interfaces,
                                           scratch_unresolved, [r])
            kept.append(r)
        except ResolutionError:
            pruned.append(r)
    if not pruned:
        print("contracts resolve: no stale entries in " + RESOLUTIONS_NAME)
        return EXIT_OK
    # The pruned store must still apply cleanly before anything is mutated.
    try:
        generate_mod.apply_resolutions(fresh_interfaces, fresh_unresolved, kept)
    except ResolutionError as exc:
        print(f"contracts resolve: {exc}", file=sys.stderr)
        return EXIT_FAIL
    try:
        entry = build_decision_entry(
            date=args.date,
            work_item=args.work_item,
            kind="unresolved",
            affected=[f"{RESOLUTIONS_NAME}: pruned stale {r.describe()}"
                      for r in pruned],
            decision="pruned stale resolution entries: "
                     + "; ".join(r.describe() for r in pruned),
            reason=args.reason,
        )
        append_entry(root, DECISION_LOG, entry)
        save_resolutions(root, kept)
        text = generate_mod.generate(root, args.config)
        (root / generate_mod.REGISTRY_NAME).write_text(text, encoding="utf-8")
    except (ResolutionError, LogEntryError) as exc:
        print(f"contracts resolve: {exc}", file=sys.stderr)
        return EXIT_FAIL
    for r in pruned:
        print(f"pruned stale: {r.describe()}")
    print(f"registry regenerated; kept {len(kept)} of {len(store)} entries")
    return EXIT_OK


def main_resolve(args) -> int:
    root = find_repo_root()
    if getattr(args, "prune_stale", False):
        if args.input is not None:
            print("contracts resolve: --prune-stale and --input are mutually exclusive",
                  file=sys.stderr)
            return EXIT_FAIL
        return _prune_stale(root, args)
    if args.input is None:
        print("contracts resolve: --input is required (or use --prune-stale)",
              file=sys.stderr)
        return EXIT_FAIL
    input_path = Path(args.input)
    if args.input == "-":
        input_text = sys.stdin.read()
        input_name = "-"
    elif not input_path.is_file():
        print(f"contracts resolve: resolutions input not found: {input_path}",
              file=sys.stderr)
        return EXIT_FAIL
    else:
        input_text = input_path.read_text(encoding="utf-8")
        input_name = str(input_path)
    try:
        entries = parse_resolutions_text(input_text, input_name)
    except ResolutionError as exc:
        print(f"contracts resolve: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if not entries:
        print("contracts resolve: resolutions input contains no [[resolution]] entries",
              file=sys.stderr)
        return EXIT_FAIL

    store = load_resolutions(root)
    interfaces, unresolved = generate_mod._collect(root, args.config)
    # Pre-merge dry run (nothing is mutated here): replay the durable store
    # against the fresh snapshot, then validate the new entries against the
    # post-store state and dry-apply them. Any failure — a stale store, an
    # entry invalidated by an earlier entry in the same file, a duplicate
    # entry — rejects the whole input file before any mutation.
    try:
        generate_mod.apply_resolutions(interfaces, unresolved, store)
        _validate_against_source(entries, {r.key for r in store}, interfaces, unresolved)
        generate_mod.apply_resolutions(interfaces, unresolved, entries)
    except ResolutionError as exc:
        print(f"contracts resolve: {exc}", file=sys.stderr)
        return EXIT_FAIL

    # All entries validated — mutate: store, registry, decision log.
    try:
        for r in entries:
            entry = build_decision_entry(
                date=args.date,
                work_item=args.work_item,
                kind="unresolved",
                affected=[f"{RESOLUTIONS_NAME}: {r.describe()}"],
                decision=f"resolved unresolved call site: {r.describe()}",
                reason=args.reason,
            )
            append_entry(root, DECISION_LOG, entry)
        save_resolutions(root, store + entries)
        text = generate_mod.generate(root, args.config)
        (root / generate_mod.REGISTRY_NAME).write_text(text, encoding="utf-8")
    except (ResolutionError, LogEntryError) as exc:
        print(f"contracts resolve: {exc}", file=sys.stderr)
        return EXIT_FAIL
    for r in entries:
        print(f"resolved: {r.describe()}")
    print(f"registry regenerated; {len(entries)} decision-log entr"
          f"{'y' if len(entries) == 1 else 'ies'} appended")
    return EXIT_OK
