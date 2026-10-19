"""Log append + append-only check (S6, S7).

The decision log (decision-log.md) and knowledge log (knowledge-log.md) live
at the repository root and are append-only (R4/R5). Writes go only through
`contracts log append`, which validates the entry format and rejects anything
malformed with the failing field named. `contracts log check` verifies each
log only grew relative to the last commit, with earlier content
byte-identical; exit non-zero otherwise.

Entry format (deterministic, one block per entry):

    ## <date> | <work-item> | <kind>
    - affected: <comma-separated interfaces/call sites>
    - decision: <decision text>
    - reason: <reason text>

Knowledge-log entries use `interfaces`/`outcome`/`rationale` fields and
`knowledge` as the kind marker.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .cli import EXIT_FAIL, EXIT_OK

DECISION_LOG = "decision-log.md"
KNOWLEDGE_LOG = "knowledge-log.md"

# Entry kinds (R4). `knowledge` is the marker for knowledge-log entries (R5).
KINDS = frozenset({
    "merge", "divorce", "leave", "divergence", "wish-declined",
    "fix", "bug-echo", "drift", "unresolved",
})
KNOWLEDGE_KIND = "knowledge"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LogEntryError(Exception):
    """Malformed log entry; message names the failing field."""


def _validate_common(date: str, work_item: str, fields: dict[str, str]) -> None:
    if not _DATE_RE.match(date or ""):
        raise LogEntryError(f"invalid field 'date': expected YYYY-MM-DD, got {date!r}")
    if not (work_item or "").strip():
        raise LogEntryError("empty field 'work-item': non-empty work-item reference required")
    for name, value in fields.items():
        if not (value or "").strip():
            raise LogEntryError(f"empty field '{name}': non-empty value required")


def build_decision_entry(date: str, work_item: str, kind: str,
                         affected: list[str], decision: str, reason: str) -> str:
    """Build a decision-log entry block; raises LogEntryError on a bad field."""
    if kind not in KINDS:
        raise LogEntryError(
            f"invalid field 'kind': {kind!r} not one of {', '.join(sorted(KINDS))}"
        )
    if not affected or not all(a.strip() for a in affected):
        raise LogEntryError("empty field 'affected': at least one affected interface required")
    _validate_common(date, work_item, {"decision": decision, "reason": reason})
    return (
        f"## {date} | {work_item} | {kind}\n"
        f"- affected: {', '.join(a.strip() for a in affected)}\n"
        f"- decision: {decision.strip()}\n"
        f"- reason: {reason.strip()}\n"
    )


def build_knowledge_entry(date: str, work_item: str, interfaces: list[str],
                          outcome: str, rationale: str) -> str:
    """Build a knowledge-log entry block; raises LogEntryError on a bad field."""
    if not interfaces or not all(i.strip() for i in interfaces):
        raise LogEntryError("empty field 'interfaces': at least one interface required")
    _validate_common(date, work_item, {"outcome": outcome, "rationale": rationale})
    return (
        f"## {date} | {work_item} | {KNOWLEDGE_KIND}\n"
        f"- interfaces: {', '.join(i.strip() for i in interfaces)}\n"
        f"- outcome: {outcome.strip()}\n"
        f"- rationale: {rationale.strip()}\n"
    )


def append_entry(root: Path, log_name: str, entry: str) -> Path:
    """Append an entry block to the log, keeping the file newline-terminated."""
    path = root / log_name
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    if current and not current.endswith("\n"):
        current += "\n"
    path.write_text(current + entry, encoding="utf-8")
    return path


def check_append_only(root: Path, log_names: list[str],
                      base_content: dict[str, str | None] | None = None) -> list[str]:
    """Verify each log only grew since the last commit (S7).

    For each log: the working-tree file must start with the committed content
    byte-identical, followed only by appended bytes. base_content overrides
    the committed source (tests). A log missing from HEAD and present in the
    working tree is fine (first append). A log present in HEAD but deleted
    in the working tree is a violation.
    """
    violations: list[str] = []
    for name in log_names:
        path = root / name
        if base_content is not None:
            base = base_content.get(name)
        else:
            base = _git_show(root, name)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current is None:
            if base is not None:
                violations.append(f"{name}: log deleted or unreadable in working tree")
            continue
        if base is None:
            continue
        if not current.startswith(base):
            violations.append(
                f"{name}: earlier content modified or truncated relative to last commit"
            )
    return violations


def _git_show(root: Path, name: str) -> str | None:
    """Committed content of `name` at HEAD, or None if absent."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{name}"], cwd=root,
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def main_log(args) -> int:
    """Handle `contracts log append ...` and `contracts log check`."""
    root = args.root
    if args.log_command == "check":
        violations = check_append_only(root, [DECISION_LOG, KNOWLEDGE_LOG])
        if violations:
            for v in violations:
                print(f"contracts log: FAIL — {v}", file=sys.stderr)
            return EXIT_FAIL
        print("contracts log: OK — append-only check passed")
        return EXIT_OK

    # append
    a = args
    try:
        if a.which_log == "decision":
            entry = build_decision_entry(
                a.date, a.work_item, a.kind,
                [x for x in a.affected.split(",")] if a.affected else [],
                a.decision, a.reason,
            )
            log_name = DECISION_LOG
        else:
            entry = build_knowledge_entry(
                a.date, a.work_item,
                [x for x in a.interfaces.split(",")] if a.interfaces else [],
                a.outcome, a.rationale,
            )
            log_name = KNOWLEDGE_LOG
    except LogEntryError as exc:
        print(f"contracts log append: rejected — {exc}", file=sys.stderr)
        return EXIT_FAIL
    path = append_entry(root, log_name, entry)
    print(f"contracts log append: appended to {path}")
    return EXIT_OK
