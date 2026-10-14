#!/usr/bin/env python3
"""Maintain a validated, local-only zettelkasten note store."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ID_PATTERN = r"[0-9]+(?:\.[0-9]+)*"
ID_RE = re.compile(rf"^{ID_PATTERN}$")
INDEX_ANNOTATED_RE = re.compile(
    rf"^({ID_PATTERN}) — "
    rf"(.*) "
    rf"(?:\[(draft|verified|settled|obsolete)\]|\[superseded → ({ID_PATTERN})\])$"
)
INDEX_RE = re.compile(rf"^({ID_PATTERN}) — (.+)$")
STATUSES = ("draft", "verified", "settled", "obsolete", "superseded")
LINK_RE = re.compile(
    rf"^([→←]) ({ID_PATTERN}) "
    r"\((extends|questions|supports|contradicts|analogous)\): (.+)$"
)
LINK_KINDS = ("extends", "questions", "supports", "contradicts", "analogous")
NOTE_FILES = ("zettel.md", "zettel-index.md")
TRANSITIONS = {
    ("draft", "verified"),
    ("verified", "settled"),
    ("draft", "obsolete"),
    ("verified", "obsolete"),
    ("settled", "obsolete"),
}
RATIONALE_STATUSES = ("verified", "settled")
STATE_FILE = ".store-state"
SKILL_HINT = "see the zettelkasten-notetaking skill for the proper repair procedure"
GUARD_FILE = "READ-ME-FIRST-use-skill-zettelkasten-notetaking.md"
GUARD_BODY = """STOP — READ BEFORE TOUCHING ANYTHING

This note store is managed by the **zettelkasten-notetaking** skill.

- Do NOT hand-edit `zettel.md`, `zettel-index.md`, or `.store-state`.
- All mutations go through `store.py` (see the zettelkasten-notetaking skill
  for the exact commands and repair procedure).
- This file is protected: commits that modify or delete it are rejected by
  the pre-commit hook, and `store.py` recreates it if it is ever deleted.
"""
GITIGNORE_FILE = ".gitignore"
GITIGNORE_BODY = ".DS_Store\n"
STAGE_FILES = (*NOTE_FILES, STATE_FILE, GUARD_FILE, GITIGNORE_FILE)


class StoreError(RuntimeError):
    """A store precondition or validation error."""


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    line: int
    end: int
    body_lines: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class Link:
    source: str
    arrow: str
    target: str
    kind: str
    line: int


@dataclass(frozen=True)
class IndexEntry:
    id: str
    title: str
    line: int
    status: str
    successor: str | None


@dataclass(frozen=True)
class Validation:
    errors: list[str]
    warnings: list[str]
    card_count: int
    link_count: int


def duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return repeated


def parse_cards(text: str, label: str, errors: list[str]) -> list[Card]:
    lines = text.splitlines()
    separators = [i for i, line in enumerate(lines) if line == "---"]
    if not separators:
        errors.append(f"{label}: no card separators (`---`) found")
        return []
    if any(line.strip() for line in lines[: separators[0]]):
        errors.append(f"{label}: content before first card separator")

    cards: list[Card] = []
    boundaries = separators + [len(lines)]
    for number, start in enumerate(separators):
        end = boundaries[number + 1]
        nonblank = [(i, lines[i]) for i in range(start + 1, end) if lines[i].strip()]
        if not nonblank:
            errors.append(f"{label}:{start + 1}: empty card")
            continue
        id_line, heading = nonblank[0]
        title_item = nonblank[1] if len(nonblank) > 1 else None
        if not heading.startswith("# ") or not ID_RE.fullmatch(heading[2:]):
            errors.append(f"{label}:{id_line + 1}: expected `# <numeric.dotted.id>`")
            continue
        card_id = heading[2:]
        if title_item is None or not title_item[1].startswith("## ") or not title_item[1][3:].strip():
            errors.append(f"{label}:{id_line + 1}: card {card_id} needs a non-empty H2 title")
            continue
        title_line, title_heading = title_item
        title = title_heading[3:].strip()
        for i in range(title_line + 1, end):
            if lines[i].startswith("# ") or lines[i].startswith("## "):
                errors.append(f"{label}:{i + 1}: unexpected card heading")
        cards.append(
            Card(
                id=card_id,
                title=title,
                line=id_line + 1,
                end=end,
                body_lines=tuple((i + 1, lines[i]) for i in range(title_line + 1, end)),
            )
        )
    return cards


def parse_index(text: str, label: str, errors: list[str]) -> list[IndexEntry]:
    entries: list[IndexEntry] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        annotated = INDEX_ANNOTATED_RE.fullmatch(line)
        match = annotated or INDEX_RE.fullmatch(line)
        if not match:
            errors.append(f"{label}:{line_number}: expected `ID — Title [status]`")
            continue
        status, successor = (annotated.group(3), annotated.group(4)) if annotated else (None, None)
        card_id, title = match.group(1), match.group(2)
        if successor is not None:
            status = "superseded"
        entries.append(
            IndexEntry(
                id=card_id,
                title=title,
                line=line_number,
                status=status or "draft",
                successor=successor,
            )
        )
    return entries


def validate_text(cards_text: str, index_text: str) -> Validation:
    errors: list[str] = []
    warnings: list[str] = []
    cards = parse_cards(cards_text, "zettel.md", errors)
    entries = parse_index(index_text, "zettel-index.md", errors)
    card_ids = [card.id for card in cards]
    index_ids = [entry.id for entry in entries]

    for card_id in sorted(duplicates(card_ids)):
        errors.append(f"zettel.md: duplicate card ID {card_id}")
    for card_id in sorted(duplicates(index_ids)):
        errors.append(f"zettel-index.md: duplicate index ID {card_id}")

    card_by_id = {card.id: card for card in cards}
    index_by_id = {entry.id: entry for entry in entries}
    for card in cards:
        indexed = index_by_id.get(card.id)
        if indexed is None:
            errors.append(f"zettel-index.md: card {card.id} is missing from index")
        elif indexed.title != card.title:
            errors.append(
                f"zettel-index.md:{indexed.line}: title for {card.id} is {indexed.title!r}, "
                f"expected {card.title!r}"
            )
        if "." in card.id:
            parent = card.id.rsplit(".", 1)[0]
            if parent not in card_by_id:
                errors.append(f"zettel.md:{card.line}: parent {parent} does not exist")
    for entry in entries:
        if entry.id not in card_by_id:
            errors.append(f"zettel-index.md:{entry.line}: index ID {entry.id} has no card")
        if entry.successor is not None and entry.successor not in card_by_id:
            errors.append(
                f"zettel-index.md:{entry.line}: successor {entry.successor} "
                f"of superseded card {entry.id} does not exist"
            )

    for card in cards:
        positions = [
            i
            for i, candidate in enumerate(cards)
            if candidate.id == card.id or candidate.id.startswith(card.id + ".")
        ]
        if positions and positions[0] != card_ids.index(card.id):
            errors.append(f"zettel.md:{card.line}: descendants appear before {card.id}")
        if positions and positions != list(range(positions[0], positions[-1] + 1)):
            errors.append(f"zettel.md:{card.line}: subtree {card.id} is not contiguous")

    links: list[Link] = []
    for card in cards:
        for line_number, line in card.body_lines:
            if not line.startswith(("→", "←")):
                continue
            match = LINK_RE.fullmatch(line)
            if not match:
                errors.append(f"zettel.md:{line_number}: malformed typed link")
                continue
            arrow, target, kind, why = match.groups()
            if not why.strip():
                errors.append(f"zettel.md:{line_number}: link needs a why clause")
            links.append(Link(card.id, arrow, target, kind, line_number))

    keys = [(link.source, link.arrow, link.target, link.kind) for link in links]
    for key in sorted(duplicates(["|".join(item) for item in keys])):
        source, arrow, target, kind = key.split("|")
        errors.append(f"zettel.md: duplicate link {source} {arrow} {target} ({kind})")
    link_set = set(keys)
    linked_ids: set[str] = set()
    for link in links:
        if link.target not in card_by_id:
            errors.append(f"zettel.md:{link.line}: link target {link.target} does not exist")
            continue
        linked_ids.update((link.source, link.target))
        reverse_arrow = "←" if link.arrow == "→" else "→"
        if (link.target, reverse_arrow, link.source, link.kind) not in link_set:
            errors.append(
                f"zettel.md:{link.line}: missing reciprocal {reverse_arrow} link "
                f"from {link.target} to {link.source} ({link.kind})"
            )

    orphans = sorted(set(card_ids) - linked_ids)
    if orphans:
        warnings.append(f"orphan cards (no typed links): {', '.join(orphans)}")
    return Validation(errors, warnings, len(cards), len(links) // 2)


def store_paths(root: Path) -> tuple[Path, Path, Path]:
    notes = root / ".notes"
    cards = notes / "zettel.md"
    index = notes / "zettel-index.md"
    if not notes.is_dir():
        raise StoreError(f"missing notes directory: {notes}")
    if not cards.is_file() or not index.is_file():
        raise StoreError(".notes must contain zettel.md and zettel-index.md")
    return notes, cards, index


def read_store(root: Path) -> tuple[Path, Path, Path, str, str]:
    notes, cards, index = store_paths(root)
    return notes, cards, index, cards.read_text(encoding="utf-8"), index.read_text(encoding="utf-8")


def require_valid(cards_text: str, index_text: str) -> Validation:
    result = validate_text(cards_text, index_text)
    if result.errors:
        raise StoreError("; ".join(result.errors))
    return result


def git(notes: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(notes), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def ensure_gitignore(notes: Path) -> bool:
    """Ensure .notes/.gitignore ignores .DS_Store; return True if modified."""
    gitignore = notes / GITIGNORE_FILE
    if not gitignore.is_file():
        gitignore.write_text(GITIGNORE_BODY, encoding="utf-8")
        return True
    content = gitignore.read_text(encoding="utf-8")
    if any(line.rstrip() == ".DS_Store" for line in content.splitlines()):
        return False
    # Append instead of overwriting so user-customized ignore rules survive.
    if not content.endswith("\n"):
        content += "\n"
    gitignore.write_text(content + GITIGNORE_BODY, encoding="utf-8")
    return True


def ensure_local_repository(notes: Path) -> None:
    if not (notes / ".git").exists():
        result = subprocess.run(
            ["git", "init", "--quiet", str(notes)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            raise StoreError(result.stderr.strip() or "git init failed")
    remotes = git(notes, "remote").stdout.splitlines()
    if remotes:
        raise StoreError("local notes repository has configured remote(s): " + ", ".join(remotes))
    if not git(notes, "config", "--get", "user.name", check=False).stdout.strip():
        git(notes, "config", "user.name", "Local Notes")
    if not git(notes, "config", "--get", "user.email", check=False).stdout.strip():
        git(notes, "config", "user.email", "local-notes@localhost")


def note_hashes(cards_text: str, index_text: str) -> str:
    lines = [
        f"{name} {hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        for name, text in (("zettel.md", cards_text), ("zettel-index.md", index_text))
    ]
    return "\n".join(lines) + "\n"


def require_ticket_match(notes: Path, cards_text: str, index_text: str) -> None:
    state = notes / STATE_FILE
    if not state.is_file():
        raise StoreError(
            f"missing .notes/{STATE_FILE}; run `store.py init <project-root>` first ({SKILL_HINT})"
        )
    if state.read_text(encoding="utf-8") != note_hashes(cards_text, index_text):
        raise StoreError(
            "note files were modified outside store.py; hand edits are not allowed. "
            f"{SKILL_HINT}"
        )


def ensure_guard(notes: Path) -> bool:
    """Resurrect the guard file if missing or altered; return True if rewritten."""
    guard = notes / GUARD_FILE
    if guard.is_file() and guard.read_text(encoding="utf-8") == GUARD_BODY:
        return False
    guard.write_text(GUARD_BODY, encoding="utf-8")
    return True


def require_clean(notes: Path) -> None:
    status = git(notes, "status", "--porcelain").stdout
    if status:
        raise StoreError("local notes repository has uncommitted changes")


def commit(notes: Path, message: str) -> str:
    cards_text = (notes / NOTE_FILES[0]).read_text(encoding="utf-8")
    index_text = (notes / NOTE_FILES[1]).read_text(encoding="utf-8")
    (notes / STATE_FILE).write_text(note_hashes(cards_text, index_text), encoding="utf-8")
    result = git(notes, "add", "--", *STAGE_FILES, check=False)
    if result.returncode:
        raise StoreError(result.stderr.strip() or "could not stage note files")
    result = git(notes, "commit", "--only", "-m", message, "--", *STAGE_FILES, check=False)
    if result.returncode:
        raise StoreError(result.stderr.strip() or "local notes commit failed")
    require_clean(notes)
    return git(notes, "rev-parse", "--short", "HEAD").stdout.strip()


def initialize(root: Path) -> str:
    notes, _cards, _index, cards_text, index_text = read_store(root)
    require_valid(cards_text, index_text)
    ensure_local_repository(notes)
    install_hook(notes)
    ensure_gitignore(notes)
    has_head = git(notes, "rev-parse", "--verify", "HEAD", check=False).returncode == 0
    guard_rewritten = ensure_guard(notes)
    if guard_rewritten and has_head and git(notes, "status", "--porcelain").stdout.strip():
        state = notes / STATE_FILE
        if state.is_file() and state.read_text(encoding="utf-8") != note_hashes(cards_text, index_text):
            raise StoreError(
                "note files were modified outside store.py; hand edits are not allowed. "
                f"{SKILL_HINT}"
            )
        commit_hash = commit(notes, "notes: restore guard file")
        return f"OK: guard file restored at {commit_hash}"
    status = git(notes, "status", "--porcelain").stdout
    if has_head and status.strip():
        touched = {line[3:] if line[1:2] == " " else line[2:].lstrip() for line in status.splitlines()}
        if touched == {GITIGNORE_FILE}:
            commit_hash = commit(notes, "notes: add .gitignore")
            return f"OK: local notes history is ready; .gitignore added at {commit_hash}"
    if not has_head:
        commit_hash = commit(notes, "notes: initialize history")
        return f"OK: initialized local notes history at {commit_hash}"
    require_clean(notes)
    cards_text = (notes / NOTE_FILES[0]).read_text(encoding="utf-8")
    index_text = (notes / NOTE_FILES[1]).read_text(encoding="utf-8")
    state = notes / STATE_FILE
    if not state.is_file():
        state.write_text(note_hashes(cards_text, index_text), encoding="utf-8")
        commit_hash = commit(notes, "notes: add store state tracking")
        return f"OK: local notes history is ready; state tracking added at {commit_hash}"
    if state.read_text(encoding="utf-8") != note_hashes(cards_text, index_text):
        raise StoreError(
            f".notes/{STATE_FILE} does not match the committed note files; "
            f"run `store.py validate`, then `store.py re-ticket <project-root>` if valid, or restore from history ({SKILL_HINT})"
        )
    return "OK: local notes history is ready"


def install_hook(notes: Path) -> None:
    hooks = notes / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    store_script = Path(__file__).resolve()
    body = (
        "#!/bin/sh\n"
        "# Installed by store.py (zettelkasten-notetaking). Do not edit or bypass.\n"
        f'exec python3 "{store_script}" hook-verify "{notes.parent}"\n'
    )
    if not hook.is_file() or hook.read_text(encoding="utf-8") != body:
        hook.write_text(body, encoding="utf-8")
        hook.chmod(0o755)


def hook_verify(root: Path) -> None:
    notes, _cards, _index = store_paths(root)

    def staged(name: str) -> str:
        result = git(notes, "show", f":{name}", check=False)
        if result.returncode:
            raise StoreError(f"{name} is not staged for commit")
        return result.stdout

    if staged(STATE_FILE) != note_hashes(staged(NOTE_FILES[0]), staged(NOTE_FILES[1])):
        raise StoreError(
            "commit rejected: note content does not match the store state written by store.py; "
            f"hand edits are not allowed ({SKILL_HINT})"
        )
    guard_stage = git(notes, "show", f":{GUARD_FILE}", check=False)
    if guard_stage.returncode:
        raise StoreError(
            f"commit rejected: {GUARD_FILE} was deleted or is missing from staging; "
            "this file is a protected part of the store "
            f"({SKILL_HINT})"
        )
    if guard_stage.stdout != GUARD_BODY:
        raise StoreError(
            f"commit rejected: {GUARD_FILE} was modified; it is a protected, immutable "
            f"part of the store ({SKILL_HINT})"
        )


def re_ticket(root: Path) -> str:
    notes, _cards, _index, cards_text, index_text = read_store(root)
    require_valid(cards_text, index_text)
    ensure_guard(notes)
    require_clean(notes)
    if (notes / STATE_FILE).read_text(encoding="utf-8") == note_hashes(cards_text, index_text):
        return "OK: store state already matches"
    commit_hash = commit(notes, "notes: refresh store state")
    return f"OK: store state refreshed at {commit_hash}"


def prepare_history(root: Path) -> Path:
    initialize(root)
    notes, _cards, _index = store_paths(root)
    ensure_guard(notes)
    install_hook(notes)
    require_clean(notes)
    return notes


TITLE_MAX_CHARS = 80
BODY_MAX_CHARS = 600


def validate_card_content(title: str, body: str) -> tuple[str, str]:
    if not title.strip() or "\n" in title or "\r" in title:
        raise StoreError("title must be one non-empty line")
    title = title.strip()
    if len(title) > TITLE_MAX_CHARS:
        raise StoreError(
            f"title must be at most {TITLE_MAX_CHARS} characters (got {len(title)}); "
            "split the idea instead"
        )
    body = body.strip()
    if not body:
        raise StoreError("body must be non-empty")
    if len(body) > BODY_MAX_CHARS:
        raise StoreError(
            f"body must be at most {BODY_MAX_CHARS} characters (got {len(body)}); "
            "split the idea instead"
        )
    for line in body.splitlines():
        if line == "---" or line.startswith(("# ", "## ", "→", "←")):
            raise StoreError("body cannot contain card separators, headings, or typed links")
    return title, body


def expected_id(card_id: str, cards: list[Card]) -> None:
    if not ID_RE.fullmatch(card_id):
        raise StoreError("card ID must be numeric and dotted")
    ids = {card.id for card in cards}
    if card_id in ids:
        raise StoreError(f"duplicate card ID {card_id}: IDs are never reused")
    if "." not in card_id:
        top_level = [int(card.id) for card in cards if "." not in card.id]
        wanted = str(max(top_level, default=0) + 1)
    else:
        parent, leaf = card_id.rsplit(".", 1)
        if parent not in ids:
            raise StoreError(f"parent {parent} does not exist")
        siblings = [
            int(card.id.rsplit(".", 1)[1])
            for card in cards
            if "." in card.id and card.id.rsplit(".", 1)[0] == parent
        ]
        wanted = f"{parent}.{max(siblings, default=0) + 1}"
    if card_id != wanted:
        raise StoreError(f"card ID must be next available ID {wanted}")


def render_card(card_id: str, title: str, body: str) -> list[str]:
    return ["---", "", f"# {card_id}", "", f"## {title}", "", *body.splitlines(), ""]


def add_card(root: Path, card_id: str, title: str, body: str) -> str:
    notes, cards_path, index_path, cards_text, index_text = read_store(root)
    require_ticket_match(notes, cards_text, index_text)
    require_valid(cards_text, index_text)
    errors: list[str] = []
    cards = parse_cards(cards_text, "zettel.md", errors)
    if errors:
        raise StoreError("; ".join(errors))
    expected_id(card_id, cards)
    title, body = validate_card_content(title, body)

    lines = cards_text.splitlines()
    if "." in card_id:
        parent = card_id.rsplit(".", 1)[0]
        last_descendant = max(
            (card for card in cards if card.id == parent or card.id.startswith(parent + ".")),
            key=lambda card: cards.index(card),
        )
        insert_at = last_descendant.end
        lines[insert_at:insert_at] = render_card(card_id, title, body)
    else:
        lines.extend(render_card(card_id, title, body))
    candidate_cards = "\n".join(lines) + "\n"
    candidate_index = index_text.rstrip("\n") + f"\n{card_id} — {title}\n"
    require_valid(candidate_cards, candidate_index)

    prepare_history(root)
    cards_path.write_text(candidate_cards, encoding="utf-8")
    index_path.write_text(candidate_index, encoding="utf-8")
    require_valid(cards_path.read_text(encoding="utf-8"), index_path.read_text(encoding="utf-8"))
    commit_hash = commit(notes, f"notes: add {card_id}")
    return f"OK: added {card_id} ({commit_hash})"


def validate_link_input(source: str, target: str, kind: str, why: str, cards: list[Card]) -> None:
    ids = {card.id for card in cards}
    if source not in ids or target not in ids:
        raise StoreError("link source and target must both exist")
    if source == target:
        raise StoreError("a card cannot link to itself")
    if kind not in LINK_KINDS:
        raise StoreError(f"link kind must be one of: {', '.join(LINK_KINDS)}")
    if not why.strip() or "\n" in why or "\r" in why:
        raise StoreError("link why must be one non-empty line")


def add_link(root: Path, source: str, target: str, kind: str, why: str) -> str:
    notes, cards_path, _index_path, cards_text, index_text = read_store(root)
    require_ticket_match(notes, cards_text, index_text)
    require_valid(cards_text, index_text)
    errors: list[str] = []
    cards = parse_cards(cards_text, "zettel.md", errors)
    if errors:
        raise StoreError("; ".join(errors))
    validate_link_input(source, target, kind, why, cards)
    existing = [
        Link(card.id, match.group(1), match.group(2), match.group(3), line_number)
        for card in cards
        for line_number, line in card.body_lines
        if (match := LINK_RE.fullmatch(line))
    ]
    if any(link.source == source and link.target == target and link.kind == kind for link in existing):
        raise StoreError(f"duplicate link {source} to {target} ({kind})")

    insertions = sorted(
        ((card.end, line) for card, line in (
            (next(card for card in cards if card.id == source), f"→ {target} ({kind}): {why.strip()}"),
            (next(card for card in cards if card.id == target), f"← {source} ({kind}): {why.strip()}"),
        )),
        reverse=True,
    )
    lines = cards_text.splitlines()
    for position, line in insertions:
        lines.insert(position, line)
    candidate_cards = "\n".join(lines) + "\n"
    require_valid(candidate_cards, index_text)

    prepare_history(root)
    cards_path.write_text(candidate_cards, encoding="utf-8")
    require_valid(cards_path.read_text(encoding="utf-8"), index_text)
    commit_hash = commit(notes, f"notes: link {source} {kind} {target}")
    return f"OK: linked {source} to {target} ({commit_hash})"


def set_status(root: Path, card_id: str, status: str, rationale: str | None) -> str:
    if status not in STATUSES or status in ("draft", "superseded"):
        raise StoreError(
            "set-status target must be one of: verified, settled, obsolete "
            "(draft is implicit; superseded is set by supersede)"
        )
    notes, _cards_path, index_path, cards_text, index_text = read_store(root)
    require_ticket_match(notes, cards_text, index_text)
    require_valid(cards_text, index_text)
    entries = parse_index(index_text, "zettel-index.md", [])
    entry = next((e for e in entries if e.id == card_id), None)
    if entry is None:
        raise StoreError(f"card {card_id} is not in the index")
    if (entry.status, status) not in TRANSITIONS:
        raise StoreError(f"illegal transition {entry.status} -> {status}")
    rationale = rationale.strip() if rationale else ""
    if status in RATIONALE_STATUSES:
        if not rationale or "\n" in rationale or "\r" in rationale:
            raise StoreError(
                f"transition to {status} requires a one-line --rationale "
                "(recorded in the local commit message)"
            )
    lines = index_text.splitlines()
    lines[entry.line - 1] = f"{card_id} — {entry.title} [{status}]"
    candidate_index = "\n".join(lines) + "\n"
    require_valid(cards_text, candidate_index)

    prepare_history(root)
    index_path.write_text(candidate_index, encoding="utf-8")
    require_valid(cards_text, index_path.read_text(encoding="utf-8"))
    message = f"notes: set {card_id} {status}"
    if rationale:
        message = f"{message} — {rationale}"
    commit_hash = commit(notes, message)
    return f"OK: set {card_id} to {status} ({commit_hash})"


def next_available_id(cards: list[Card]) -> str:
    """The next top-level card ID, matching the expected_id rule for new roots."""
    tops = [int(card.id) for card in cards if "." not in card.id]
    return str(max(tops, default=0) + 1)


def supersede(root: Path, card_id: str, title: str, body: str, rationale: str | None) -> str:
    notes, cards_path, index_path, cards_text, index_text = read_store(root)
    require_ticket_match(notes, cards_text, index_text)
    require_valid(cards_text, index_text)
    errors: list[str] = []
    cards = parse_cards(cards_text, "zettel.md", errors)
    if errors:
        raise StoreError("; ".join(errors))
    if card_id not in {card.id for card in cards}:
        raise StoreError(f"card {card_id} does not exist")
    entries = parse_index(index_text, "zettel-index.md", [])
    entry = next((e for e in entries if e.id == card_id), None)
    if entry is None:
        raise StoreError(f"card {card_id} is not in the index")
    if entry.status == "superseded":
        raise StoreError(f"card {card_id} is already superseded")
    title, body = validate_card_content(title, body)
    successor_id = next_available_id(cards)

    candidate_cards = "\n".join(
        [*cards_text.splitlines(), *render_card(successor_id, title, body)]
    ) + "\n"
    lines = index_text.splitlines()
    lines[entry.line - 1] = f"{card_id} — {entry.title} [superseded → {successor_id}]"
    candidate_index = "\n".join([*lines, f"{successor_id} — {title}"]) + "\n"
    require_valid(candidate_cards, candidate_index)

    prepare_history(root)
    cards_path.write_text(candidate_cards, encoding="utf-8")
    index_path.write_text(candidate_index, encoding="utf-8")
    require_valid(
        cards_path.read_text(encoding="utf-8"), index_path.read_text(encoding="utf-8")
    )
    message = f"notes: supersede {card_id} by {successor_id}"
    if rationale and rationale.strip():
        message = f"{message} — {rationale.strip()}"
    commit_hash = commit(notes, message)
    return f"OK: superseded {card_id} by {successor_id} ({commit_hash})"


def print_validation(root: Path) -> int:
    _notes, _cards, _index, cards_text, index_text = read_store(root)
    result = validate_text(cards_text, index_text)
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if result.errors:
        print(f"FAILED: {len(result.errors)} error(s)", file=sys.stderr)
        return 1
    print(f"OK: {result.card_count} cards, {result.link_count} reciprocal link pair(s)")
    return 0


def body_argument(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body
    return Path(args.body_file).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "validate"):
        command = commands.add_parser(name)
        command.add_argument("root")

    add_card_parser = commands.add_parser("add-card")
    add_card_parser.add_argument("root")
    add_card_parser.add_argument("--id", required=True)
    add_card_parser.add_argument("--title", required=True)
    body_group = add_card_parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")

    add_link_parser = commands.add_parser("add-link")
    add_link_parser.add_argument("root")
    add_link_parser.add_argument("--from", dest="source", required=True)
    add_link_parser.add_argument("--to", dest="target", required=True)
    add_link_parser.add_argument("--kind", required=True)
    add_link_parser.add_argument("--why", required=True)

    set_status_parser = commands.add_parser("set-status")
    set_status_parser.add_argument("root")
    set_status_parser.add_argument("--id", required=True)
    set_status_parser.add_argument("--status", required=True)
    set_status_parser.add_argument("--rationale")

    supersede_parser = commands.add_parser("supersede")
    supersede_parser.add_argument("root")
    supersede_parser.add_argument("--id", required=True)
    supersede_parser.add_argument("--title", required=True)
    body_group = supersede_parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")
    supersede_parser.add_argument("--rationale")

    hook_parser = commands.add_parser("hook-verify")
    hook_parser.add_argument("root")
    re_ticket_parser = commands.add_parser("re-ticket")
    re_ticket_parser.add_argument("root")

    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        if args.command == "validate":
            return print_validation(root)
        if args.command == "init":
            print(initialize(root))
        elif args.command == "add-card":
            print(add_card(root, args.id, args.title, body_argument(args)))
        elif args.command == "set-status":
            print(set_status(root, args.id, args.status, args.rationale))
        elif args.command == "supersede":
            print(supersede(root, args.id, args.title, body_argument(args), args.rationale))
        elif args.command == "hook-verify":
            hook_verify(root)
            print("OK: staged note content matches the store state")
        elif args.command == "re-ticket":
            print(re_ticket(root))
        else:
            print(add_link(root, args.source, args.target, args.kind, args.why))
    except (StoreError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
