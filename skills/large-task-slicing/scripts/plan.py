#!/usr/bin/env python3
"""Maintain a validated, append-only work-unit plan for a large task.

The LLM decides a unit's label, contract, and when to verify it. The script owns
every mechanical mutation: unit IDs, placement, checkbox state, the appended
event trail (added/done/blocked/cancelled), and validation. There is deliberately
NO edit/rewrite/reorder command — changing intent is only ever `cancel` + `add-unit`,
so provenance survives by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PLAN_FILE = "task_plan.md"
STATE_FILE = ".plan-state"
FINDINGS_FILE = "findings.md"
PROGRESS_FILE = "progress.md"
SKILL_HINT = "see the large-task-slicing skill for the proper repair procedure"
GUARD_FILE = "READ-ME-FIRST-use-skill-large-task-slicing.md"
GUARD_BODY = """STOP — READ BEFORE TOUCHING ANYTHING

This plan is managed by the **large-task-slicing** skill.

- Do NOT hand-edit `task_plan.md`; all plan changes go through `plan.py`
  (see the large-task-slicing skill for the exact commands and repair procedure).
- `findings.md` and `progress.md` are free-form and hand-edited.
- This file is protected: `plan.py` recreates it if it is ever deleted.
"""
# The same note rides at the top of task_plan.md as YAML frontmatter, so an
# agent that reads only the plan still sees the instruction.
PLAN_FRONTMATTER = (
    "---\nguard: |\n"
    + "\n".join("  " + line if line else "" for line in GUARD_BODY.rstrip("\n").split("\n"))
    + "\n---\n"
)

CONTRACT_KEYS = ("input", "scope", "output", "verify")
FALSIFY_KINDS = ("mutation", "input", "none")
BLOCK_KINDS = ("code", "test", "mechanical", "requirement")

# Checkbox state -> meaning, derived from the unit's last event:
#   [ ] open    [x] done    [!] blocked    [-] cancelled
STATE_OPEN, STATE_DONE, STATE_BLOCKED, STATE_CANCELLED = " ", "x", "!", "-"

UNIT_HEADER_RE = re.compile(r"^- \[([ x!-])\] (unit-\d+) — (.+)$")
CONTRACT_RE = re.compile(r"^  - (input|scope|output|verify|falsify): (.*)$")
EVENT_RE = re.compile(
    r"^  - (added|done|blocked|cancelled) (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
    r"( \[[a-z]+\])?: (.*)$"
)
NEXT_ID_RE = re.compile(r"^unit-(\d+)$")


class PlanError(RuntimeError):
    """A plan precondition or validation error."""


@dataclass(frozen=True)
class Unit:
    id: str
    state: str
    label: str
    header_idx: int
    end_idx: int  # exclusive: start of the next unit header, or end of file


@dataclass(frozen=True)
class Event:
    verb: str
    timestamp: str
    kind: str | None
    text: str
    line: int


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unit_count: int = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- falsifiers -------------------------------------------------------------

def validate_falsify_entry(entry: str, where: str) -> None:
    """Validate one `falsify` entry: `<kind>[: text]` with per-kind rules.

    - kind must be mutation, input, or none
    - none carries only a reason and requires it
    - mutation/input carry `label: expected failure` so `complete --falsify-outcome`
      can match outcomes to them by label
    """
    kind, sep, text = entry.partition(":")
    if kind.strip() not in FALSIFY_KINDS:
        raise PlanError(
            f"{where}: falsify kind must be one of: {', '.join(FALSIFY_KINDS)}"
        )
    text = text.strip()
    if kind.strip() == "none":
        if not text:
            raise PlanError(f"{where}: falsify kind `none` requires a reason")
        return
    if not sep:
        raise PlanError(
            f"{where}: falsify entry {entry!r} must be `<kind>: label: expected failure` "
            "(mutation/input) or `none: reason`"
        )
    label, sep2, rest = text.partition(":")
    if not label.strip() or not rest.strip():
        raise PlanError(
            f"{where}: falsify entry {entry!r} must be `<kind>: label: expected failure` "
            "(mutation/input) or `none: reason`"
        )


def falsify_entries(contract: dict[str, str]) -> list[str]:
    raw = contract.get("falsify", "")
    return raw.splitlines() if raw else []


def validate_falsify_entries(contract: dict[str, str], where: str) -> None:
    for entry in falsify_entries(contract):
        validate_falsify_entry(entry, where)


def falsify_labels(contract: dict[str, str]) -> list[str]:
    """Labels of declared mutation/input falsifiers, in declaration order."""
    labels: list[str] = []
    for entry in falsify_entries(contract):
        kind, _, text = entry.partition(":")
        if kind.strip() in ("mutation", "input"):
            labels.append(text.strip().partition(":")[0].strip())
    return labels


# --- paths and ticket -------------------------------------------------------

def plan_paths(root: Path) -> tuple[Path, Path]:
    return root / ".todo", root / ".todo" / PLAN_FILE


def ensure_guard(todo: Path) -> bool:
    """Resurrect the guard file if missing or altered; return True if rewritten."""
    guard = todo / GUARD_FILE
    if guard.is_file() and guard.read_text(encoding="utf-8") == GUARD_BODY:
        return False
    guard.write_text(GUARD_BODY, encoding="utf-8")
    return True


def read_plan_text(root: Path) -> str:
    _todo, plan = plan_paths(root)
    if not plan.is_file():
        raise PlanError(
            f"missing {plan}; there is no plan to work on. Start one with "
            f"`plan.py init` ({SKILL_HINT})"
        )
    return plan.read_text(encoding="utf-8")


def plan_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() + "\n"


def require_ticket_match(root: Path, text: str) -> None:
    todo, _plan = plan_paths(root)
    state = todo / STATE_FILE
    if not state.is_file():
        raise PlanError(
            f"missing .todo/{STATE_FILE}; run `plan.py init <root>` first ({SKILL_HINT})"
        )
    if state.read_text(encoding="utf-8") != plan_hash(text):
        raise PlanError(
            "the plan file was modified outside plan.py; hand edits are not allowed. "
            f"{SKILL_HINT}"
        )


def write_ticket(root: Path, text: str) -> None:
    todo, _plan = plan_paths(root)
    (todo / STATE_FILE).write_text(plan_hash(text), encoding="utf-8")


# --- parsing ----------------------------------------------------------------

def find_units(lines: list[str]) -> list[Unit]:
    headers = [i for i, line in enumerate(lines) if UNIT_HEADER_RE.match(line)]
    units: list[Unit] = []
    for number, header_idx in enumerate(headers):
        match = UNIT_HEADER_RE.match(lines[header_idx])
        assert match is not None
        end_idx = headers[number + 1] if number + 1 < len(headers) else len(lines)
        units.append(Unit(match.group(2), match.group(1), match.group(3), header_idx, end_idx))
    return units


def find_unit(lines: list[str], unit_id: str) -> Unit:
    for unit in find_units(lines):
        if unit.id == unit_id:
            return unit
    raise PlanError(f"no unit {unit_id} in the plan")


def block_end(lines: list[str], unit: Unit) -> int:
    """Where to append a new event: after the unit's last non-blank sub-line."""
    end = unit.end_idx
    while end > unit.header_idx + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def parse_subitems(lines: list[str], unit: Unit) -> tuple[dict[str, str], list[Event]]:
    contract: dict[str, str] = {}
    events: list[Event] = []
    kind: str | None = None
    key = ""
    verb = ""
    ts = ""
    tag: str | None = None
    line_no = 0
    parts: list[str] = []

    def flush() -> None:
        nonlocal kind, key, verb, ts, tag, line_no, parts
        if kind is None:
            return
        text = "\n".join(parts)
        if kind == "contract":
            if key == "falsify":  # falsify repeats; join entries with newlines
                contract[key] = f"{contract[key]}\n{text}" if key in contract else text
            else:
                contract[key] = text
        else:
            events.append(Event(verb, ts, tag, text, line_no))
        kind, parts = None, []

    for idx in range(unit.header_idx + 1, unit.end_idx):
        line = lines[idx]
        contract_match = CONTRACT_RE.match(line)
        event_match = EVENT_RE.match(line)
        if contract_match:
            flush()
            kind, key, parts = "contract", contract_match.group(1), [contract_match.group(2)]
        elif event_match:
            flush()
            verb, ts, tag_raw, first = event_match.groups()
            kind, tag, line_no, parts = "event", (tag_raw[2:-1] if tag_raw else None), idx, [first]
        elif kind is not None:
            parts.append(line[4:] if line.startswith("    ") else line)
        # A stray line before any sub-item is reported by validate_text.
    flush()
    return contract, events


def expected_state(events: list[Event]) -> str:
    if not events:
        return STATE_OPEN
    return {
        "done": STATE_DONE,
        "cancelled": STATE_CANCELLED,
        "blocked": STATE_BLOCKED,
    }.get(events[-1].verb, STATE_OPEN)


# --- validation -------------------------------------------------------------

def validate_text(text: str) -> Validation:
    result = Validation()
    if not text.startswith(PLAN_FRONTMATTER):
        result.errors.append(
            f"{PLAN_FILE}: missing or altered guard frontmatter at the top of the file"
        )
    if "## Work units" not in text:
        result.errors.append(f"{PLAN_FILE}: missing `## Work units` section")
        return result
    lines = text.splitlines()
    units = find_units(lines)
    result.unit_count = len(units)
    if not units:
        result.warnings.append("no work units yet")
    seen: set[str] = set()
    for unit in units:
        where = f"{PLAN_FILE}:{unit.header_idx + 1}"
        if unit.id in seen:
            result.errors.append(f"{where}: duplicate unit ID {unit.id}")
        seen.add(unit.id)
        for idx in range(unit.header_idx + 1, unit.end_idx):
            line = lines[idx]
            if CONTRACT_RE.match(line) or EVENT_RE.match(line) or not line.strip():
                continue
            if not line.startswith("    "):
                result.errors.append(f"{where}: unexpected line in unit {unit.id}: {line!r}")
        contract, events = parse_subitems(lines, unit)
        for key in CONTRACT_KEYS:
            if key not in contract:
                result.errors.append(f"{where}: unit {unit.id} is missing `{key}`")
            elif not contract[key].strip():
                result.errors.append(f"{where}: unit {unit.id} has empty `{key}`")
        for event in events:
            if event.verb == "blocked" and event.kind not in BLOCK_KINDS:
                result.errors.append(
                    f"{PLAN_FILE}:{event.line + 1}: blocked event has invalid kind {event.kind!r}"
                )
        try:
            validate_falsify_entries(contract, where)
        except PlanError as error:
            result.errors.append(str(error))
        wanted = expected_state(events)
        if unit.state != wanted:
            result.errors.append(
                f"{where}: unit {unit.id} state [{unit.state}] does not match its "
                f"last event (expected [{wanted}])"
            )
    return result


def require_valid(text: str) -> Validation:
    result = validate_text(text)
    if result.errors:
        raise PlanError("; ".join(result.errors))
    return result


# --- rendering --------------------------------------------------------------

def render_unit_block(unit_id: str, label: str, contract: dict[str, str], added_note: str, falsify: list[str] | None = None) -> list[str]:
    if not label.strip() or "\n" in label:
        raise PlanError("label must be one non-empty line")
    out = [f"- [ ] {unit_id} — {label.strip()}"]
    for key in CONTRACT_KEYS:
        value = contract[key]
        if not value.strip() or "\n" in value:
            raise PlanError(f"{key} must be one non-empty line")
        out.append(f"  - {key}: {value.strip()}")
    for entry in falsify or []:
        validate_falsify_entry(entry, unit_id)
        out.append(f"  - falsify: {entry}")
    out.append(f"  - added {now_iso()}: {added_note}")
    return out


def render_event(verb: str, kind: str | None, text: str) -> list[str]:
    """One event sub-line; multi-line text continues on 4-space-indented lines."""
    if not text.strip():
        raise PlanError(f"{verb} requires non-empty text")
    stamp = now_iso()
    tag = f" [{kind}]" if kind else ""
    first, *rest = text.split("\n")
    return [f"  - {verb} {stamp}{tag}: {first}", *[f"    {line}" for line in rest]]


# --- commands ---------------------------------------------------------------

def common_git_dir(root: Path) -> Path | None:
    """The repo's *common* git dir (rev-parse --git-common-dir), or None.

    Shared storage that survives `git worktree remove` — in a worktree,
    root/.git is a file, not a directory, so it cannot host anything.
    """
    if not (root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    git_common_dir = proc.stdout.strip() if proc.returncode == 0 else ""
    if not git_common_dir:
        return None
    if not os.path.isabs(git_common_dir):
        git_common_dir = str(root / git_common_dir)
    return Path(git_common_dir)


def default_branch(root: Path) -> str:
    """The repo's default branch (origin/HEAD), falling back to 'main'."""
    try:
        proc = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "main"
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split("/", 1)[-1]
    return "main"


def guard_main_checkout(root: Path, allow: bool) -> None:
    """Refuse `init` in the main checkout or on the default branch (#91).

    plan-work and worktree-management say the main checkout hosts no plans and
    one plan per root; this turns the prose rule into a harness check. Pass
    --allow-main for standalone large-task-slicing use outside a worktree.
    """
    if allow or not (root / ".git").exists():
        return

    def rev(*git_args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *git_args], cwd=root, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    git_dir = rev("rev-parse", "--git-dir")
    git_common = rev("rev-parse", "--git-common-dir")
    branch = rev("rev-parse", "--abbrev-ref", "HEAD")
    if git_dir and git_common:
        if not os.path.isabs(git_dir):
            git_dir = str(root / git_dir)
        if not os.path.isabs(git_common):
            git_common = str(root / git_common)
        if Path(git_dir) == Path(git_common):
            raise PlanError(
                f"{root} is the repository's main worktree; plans live in a "
                "worktree workspace (plan-work step 1.5, worktree-management). "
                "Pass --allow-main to plan in the main checkout anyway."
            )
    if branch and branch != "HEAD" and branch == default_branch(root):
        raise PlanError(
            f"{root} is on the default branch ({branch}); plans live on a "
            "work branch in a worktree workspace. Pass --allow-main to "
            "plan here anyway."
        )


def exclude_from_git(root: Path) -> None:
    """Add .todo patterns to the repo's git exclude (see common_git_dir)."""
    common = common_git_dir(root)
    if common is None:
        return
    info = common / "info"
    try:
        info.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    exclude = info / "exclude"
    existing = exclude.read_text(encoding="utf-8").splitlines() if exclude.is_file() else []
    for pattern in (".todo", ".todo-*.tar.gz"):
        if pattern not in existing:
            with exclude.open("a", encoding="utf-8") as handle:
                if existing and existing[-1] != "":
                    handle.write("\n")
                handle.write(f"{pattern}\n")
            existing.append(pattern)


def init_plan(root: Path, name: str, goal: str, bounds: str, allow_main: bool = False) -> str:
    if not name.strip() or "\n" in name:
        raise PlanError("name must be one non-empty line")
    if not goal.strip() or not bounds.strip():
        raise PlanError("goal and bounds must be non-empty")
    if not root.is_dir():
        raise PlanError(
            f"root directory {root} does not exist; create it first — "
            "init never creates the root, only .todo inside it"
        )
    guard_main_checkout(root, allow_main)
    todo, plan = plan_paths(root)
    if plan.is_file():
        raise PlanError(
            f"a plan already exists at {plan}; resume it or archive it first — "
            "never create a second plan alongside an existing one"
        )
    todo.mkdir(exist_ok=True)
    exclude_from_git(root)
    ensure_guard(todo)

    plan.write_text(
        f"{PLAN_FRONTMATTER}# {name.strip()}\n\n## Goal memory\n\n{goal.strip()}\n\n"
        f"## Bounds\n\n{bounds.strip()}\n\n## Work units\n",
        encoding="utf-8",
    )
    (todo / FINDINGS_FILE).write_text(f"# Findings: {name.strip()}\n", encoding="utf-8")
    (todo / PROGRESS_FILE).write_text(f"# Progress: {name.strip()}\n", encoding="utf-8")
    write_ticket(root, plan.read_text(encoding="utf-8"))
    return f"OK: initialized .todo/ for {name.strip()!r} (0 units)"


def add_unit(root: Path, label: str, contract: dict[str, str], after: str | None, falsify: list[str] | None = None) -> str:
    todo, _plan = plan_paths(root)
    ensure_guard(todo)
    text = read_plan_text(root)
    require_ticket_match(root, text)
    require_valid(text)
    lines = text.splitlines()
    units = find_units(lines)

    next_number = max((int(NEXT_ID_RE.match(u.id).group(1)) for u in units), default=0) + 1
    unit_id = f"unit-{next_number:03d}"

    if after is None:
        note, insert_at = "appended at tail", len(lines)
    else:
        if after == "frontier":
            target = next((u for u in units if u.state in (STATE_OPEN, STATE_BLOCKED)), None)
            if target is None:
                raise PlanError("no open unit to place after (the frontier is empty)")
            anchor = target.id
        else:
            anchor = after
        target = find_unit(lines, anchor)
        note, insert_at = f"placed after {target.id}", block_end(lines, target)

    lines[insert_at:insert_at] = render_unit_block(unit_id, label, contract, note, falsify)
    candidate = "\n".join(lines) + "\n"
    require_valid(candidate)

    _todo, plan = plan_paths(root)
    plan.write_text(candidate, encoding="utf-8")
    write_ticket(root, candidate)
    return f"OK: added {unit_id} ({note})"


def transition(root: Path, unit_id: str, verb: str, kind: str | None, text: str, new_state: str) -> str:
    todo, _plan = plan_paths(root)
    ensure_guard(todo)
    current = read_plan_text(root)
    require_ticket_match(root, current)
    require_valid(current)
    lines = current.splitlines()
    unit = find_unit(lines, unit_id)

    if verb == "done" and unit.state in (STATE_DONE, STATE_CANCELLED):
        raise PlanError(f"{unit_id} is already [{unit.state}]; it cannot be completed again")
    if verb == "cancelled" and unit.state == STATE_DONE:
        raise PlanError(f"{unit_id} is done; a completed unit is never cancelled")
    if verb == "blocked" and unit.state in (STATE_DONE, STATE_CANCELLED):
        raise PlanError(f"{unit_id} is already [{unit.state}]; it cannot be blocked")

    lines[unit.header_idx] = f"- [{new_state}] {unit_id} — {unit.label}"
    insert_at = block_end(lines, unit)
    lines[insert_at:insert_at] = render_event(verb, kind, text)
    candidate = "\n".join(lines) + "\n"
    require_valid(candidate)

    _todo, plan = plan_paths(root)
    plan.write_text(candidate, encoding="utf-8")
    write_ticket(root, candidate)
    return f"OK: {unit_id} -> [{new_state}] ({verb})"


def complete(root: Path, unit_id: str, evidence: str, no_archive: bool = False, falsify_outcomes: list[str] | None = None) -> str:
    outcomes = falsify_outcomes or []
    for outcome in outcomes:
        label, _, rest = outcome.partition(":")
        if not label.strip() or not rest.strip():
            raise PlanError(
                f"falsify-outcome {outcome!r} must be `label: observed failure`"
            )
    text = read_plan_text(root)
    lines = text.splitlines()
    unit = find_unit(lines, unit_id)
    contract, _events = parse_subitems(lines, unit)
    declared = falsify_labels(contract)
    seen: list[str] = []
    for outcome in outcomes:
        label = outcome.partition(":")[0].strip()
        if label not in declared:
            raise PlanError(
                f"falsify-outcome names label {label!r}, which unit {unit_id} "
                "does not declare (declared: " + (", ".join(declared) or "none") + ")"
            )
        if label in seen:
            raise PlanError(f"duplicate falsify-outcome for label {label!r}")
        seen.append(label)
    missing = [label for label in declared if label not in seen]
    if missing:
        raise PlanError(
            f"{unit_id} declares falsifier(s) without recorded outcomes: "
            + ", ".join(missing)
            + "; pass --falsify-outcome 'label: observed failure' for each before completing"
        )
    if outcomes:
        evidence = "\n".join([evidence, *[f"falsify-outcome: {o}" for o in outcomes]])
    result = transition(root, unit_id, "done", None, evidence, STATE_DONE)
    if no_archive:
        result += f"\nNOTE: --no-archive given; plan not archived; run `plan.py archive {root}` to archive it"
        return result
    text = read_plan_text(root)
    units = find_units(text.splitlines())
    if all(u.state in (STATE_DONE, STATE_CANCELLED) for u in units):
        try:
            result += "\n" + archive(root)
        except (PlanError, OSError, tarfile.TarError) as error:
            result += f"\nNOTE: automatic archive failed: {error}; run `plan.py archive {root}` manually"
    return result


def block(root: Path, unit_id: str, kind: str, reason: str) -> str:
    if kind not in BLOCK_KINDS:
        raise PlanError(f"kind must be one of: {', '.join(BLOCK_KINDS)}")
    return transition(root, unit_id, "blocked", kind, reason, STATE_BLOCKED)


def cancel(root: Path, unit_id: str, reason: str) -> str:
    return transition(root, unit_id, "cancelled", None, reason, STATE_CANCELLED)


def status(root: Path) -> str:
    text = read_plan_text(root)
    lines = text.splitlines()
    units = find_units(lines)
    name = next((line[2:] for line in lines if line.startswith("# ")), "plan")
    out = [f"## Plan status — {name}", ""]

    frontier = next((u for u in units if u.state in (STATE_OPEN, STATE_BLOCKED)), None)
    if frontier is not None:
        contract, _events = parse_subitems(lines, frontier)
        out.append(f"Current: {frontier.id} — {frontier.label}")
        for key in CONTRACT_KEYS:
            out.append(f"  - {key}: {contract.get(key, '')}")
    else:
        out.append("Current: none — every unit is terminal")

    buckets: dict[str, list[Unit]] = {STATE_OPEN: [], STATE_DONE: [], STATE_BLOCKED: [], STATE_CANCELLED: []}
    for unit in units:
        buckets[unit.state].append(unit)
    out += [
        "",
        f"Open: {', '.join(u.id for u in buckets[STATE_OPEN]) or 'none'}",
        f"Done: {', '.join(u.id for u in buckets[STATE_DONE]) or 'none'}",
        f"Blocked: {', '.join(u.id for u in buckets[STATE_BLOCKED]) or 'none'}",
        f"Cancelled: {', '.join(u.id for u in buckets[STATE_CANCELLED]) or 'none'}",
        f"Remaining open: {len(buckets[STATE_OPEN]) + len(buckets[STATE_BLOCKED])}",
    ]
    return "\n".join(out)


def history(root: Path) -> str:
    text = read_plan_text(root)
    lines = text.splitlines()
    out: list[str] = []
    for unit in find_units(lines):
        _contract, events = parse_subitems(lines, unit)
        for event in events:
            tag = f" [{event.kind}]" if event.kind else ""
            out.append(f"{unit.id}: {event.verb} {event.timestamp}{tag}: {event.text}")
    return "\n".join(out) if out else "(no events)"


def archive(root: Path) -> str:
    text = read_plan_text(root)
    require_valid(text)
    lines = text.splitlines()
    unfinished = [u.id for u in find_units(lines) if u.state not in (STATE_DONE, STATE_CANCELLED)]
    if unfinished:
        raise PlanError(
            "plan is not complete — unfinished units: " + ", ".join(unfinished)
            + ". Archive refuses unless every unit is done or cancelled."
        )
    todo, _plan = plan_paths(root)
    common = common_git_dir(root)
    if common is None:
        raise PlanError(
            f"{root} is not inside a git repository; the archive must go to the "
            "common git dir so `git worktree remove` cannot destroy it"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_path = common / f".todo-{stamp}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(todo, arcname=".todo")
    if not archive_path.is_file():
        raise PlanError("archive file was not created")
    shutil.rmtree(todo)
    return f"OK: archived .todo/ to {archive_path} and removed .todo/"


def print_validation(root: Path) -> int:
    text = read_plan_text(root)
    result = validate_text(text)
    todo, _plan = plan_paths(root)
    state = todo / STATE_FILE
    if state.is_file() and state.read_text(encoding="utf-8") != plan_hash(text):
        result.warnings.append("task_plan.md was modified outside plan.py (ticket mismatch)")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if result.errors:
        print(f"FAILED: {len(result.errors)} error(s)", file=sys.stderr)
        return 1
    print(f"OK: {result.unit_count} unit(s)")
    return 0


def re_ticket(root: Path) -> str:
    todo, _plan = plan_paths(root)
    ensure_guard(todo)
    text = read_plan_text(root)
    require_valid(text)
    write_ticket(root, text)
    return "OK: plan state ticket refreshed to the validated plan"


# --- CLI --------------------------------------------------------------------

def text_arg(args: argparse.Namespace, name: str) -> str:
    inline = getattr(args, name)
    if inline is not None:
        return inline
    file_value = getattr(args, f"{name}_file")
    if file_value == "-":
        return sys.stdin.read()
    return Path(file_value).read_text(encoding="utf-8")


def add_text_pair(parser: argparse.ArgumentParser, name: str) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(f"--{name}")
    group.add_argument(f"--{name}-file")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init")
    init_parser.add_argument("root")
    init_parser.add_argument("--name", required=True)
    init_parser.add_argument("--allow-main", action="store_true", help="allow init in the main checkout / on the default branch")
    add_text_pair(init_parser, "goal")
    add_text_pair(init_parser, "bounds")

    add_parser = commands.add_parser("add-unit")
    add_parser.add_argument("root")
    add_parser.add_argument("--label", required=True)
    for key in CONTRACT_KEYS:
        add_parser.add_argument(f"--{key}", required=True)
    add_parser.add_argument("--falsify", action="append", default=[], metavar="KIND[: LABEL:] TEXT", help="declared falsifier; repeatable (mutation/input/none)")
    add_parser.add_argument("--after", help="a unit ID, or `frontier` for the first open unit")

    complete_parser = commands.add_parser("complete")
    complete_parser.add_argument("unit")
    complete_parser.add_argument("root")
    complete_parser.add_argument("--evidence", required=True)
    complete_parser.add_argument("--falsify-outcome", action="append", default=[], metavar="LABEL: OBSERVED FAILURE", help="recorded falsifier outcome; repeatable, one per declared mutation/input falsifier")
    complete_parser.add_argument("--no-archive", action="store_true")

    block_parser = commands.add_parser("block")
    block_parser.add_argument("unit")
    block_parser.add_argument("root")
    block_parser.add_argument("--kind", required=True)
    block_parser.add_argument("--reason", required=True)

    cancel_parser = commands.add_parser("cancel")
    cancel_parser.add_argument("unit")
    cancel_parser.add_argument("root")
    cancel_parser.add_argument("--reason", required=True)

    for name in ("status", "history", "archive", "validate", "re-ticket"):
        command = commands.add_parser(name)
        command.add_argument("root")

    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        if args.command == "init":
            print(init_plan(root, args.name, text_arg(args, "goal"), text_arg(args, "bounds"), allow_main=args.allow_main))
        elif args.command == "add-unit":
            contract = {key: getattr(args, key) for key in CONTRACT_KEYS}
            print(add_unit(root, args.label, contract, args.after, falsify=args.falsify))
        elif args.command == "complete":
            print(complete(root, args.unit, args.evidence, args.no_archive, falsify_outcomes=args.falsify_outcome))
        elif args.command == "block":
            print(block(root, args.unit, args.kind, args.reason))
        elif args.command == "cancel":
            print(cancel(root, args.unit, args.reason))
        elif args.command == "status":
            print(status(root))
        elif args.command == "history":
            print(history(root))
        elif args.command == "archive":
            print(archive(root))
        elif args.command == "validate":
            return print_validation(root)
        elif args.command == "re-ticket":
            print(re_ticket(root))
    except (PlanError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
