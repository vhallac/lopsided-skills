#!/usr/bin/env python3
"""Black-box tests for store.py."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("store.py")


class TestStoreCommands(unittest.TestCase):
    def make_store(self, cards: str | None = None, index: str | None = None) -> Path:
        root = Path(tempfile.mkdtemp())
        notes = root / ".notes"
        notes.mkdir()
        (notes / "zettel.md").write_text(cards or """---

# 1

## First claim

First body.

---

# 1.1

## Child claim

Child body.

---

# 1.1.1

## Grandchild claim

Grandchild body.

---

# 2

## Second claim

Second body.
""", encoding="utf-8")
        (notes / "zettel-index.md").write_text(index or """1 — First claim
1.1 — Child claim
1.1.1 — Grandchild claim
2 — Second claim
""", encoding="utf-8")
        return root

    def run_store(self, root: Path, *args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args, str(root)],
            text=True,
            input=input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def git(self, root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root / ".notes"), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout

    def test_add_card_places_child_after_parent_subtree_and_commits(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        result = self.run_store(
            root,
            "add-card",
            "--id",
            "1.2",
            "--title",
            "Sibling claim",
            "--body",
            "Sibling body.",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        cards = (root / ".notes/zettel.md").read_text(encoding="utf-8")
        self.assertLess(cards.index("# 1.1.1"), cards.index("# 1.2"))
        self.assertLess(cards.index("# 1.2"), cards.index("# 2"))
        self.assertIn("1.2 — Sibling claim\n", (root / ".notes/zettel-index.md").read_text())
        self.assertEqual(self.run_store(root, "validate").returncode, 0)
        self.assertIn("notes: add 1.2", self.git(root, "log", "--format=%s"))
        self.assertEqual(self.git(root, "status", "--porcelain"), "")

    def test_add_card_rejects_duplicate_id_without_changing_files_or_history(self) -> None:
        root = self.make_store()
        initialized = self.run_store(root, "init")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        cards_path = root / ".notes/zettel.md"
        index_path = root / ".notes/zettel-index.md"
        cards_before = cards_path.read_bytes()
        index_before = index_path.read_bytes()
        head_before = self.git(root, "rev-parse", "HEAD")

        result = self.run_store(
            root,
            "add-card",
            "--id",
            "1.1",
            "--title",
            "Duplicate claim",
            "--body",
            "This must not be written.",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate card ID 1.1", result.stderr)
        self.assertEqual(cards_path.read_bytes(), cards_before)
        self.assertEqual(index_path.read_bytes(), index_before)
        self.assertEqual(self.git(root, "rev-parse", "HEAD"), head_before)

    def test_validate_rejects_duplicate_ids(self) -> None:
        root = self.make_store(
            cards="""---

# 1

## First claim

First body.

---

# 1

## Duplicate claim

Duplicate body.
""",
            index="""1 — First claim
1 — Duplicate claim
""",
        )

        result = self.run_store(root, "validate")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate card ID 1", result.stderr)
        self.assertIn("duplicate index ID 1", result.stderr)

    def test_annotated_index_lines_validate(self) -> None:
        root = self.make_store(
            index="""1 — First claim [verified]
1.1 — Child claim [settled]
1.1.1 — Grandchild claim [superseded → 2]
2 — Second claim [obsolete]
"""
        )

        result = self.run_store(root, "validate")

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_change_store_with_bracket_titles_validates_unchanged(self) -> None:
        cards = """---

# 1

## Costs [USD]

Body.

---

# 2

## Weird ] title

Body.

---

# 3

## Nested [a [b]] c

Body.
"""
        root = self.make_store(
            cards=cards,
            index="1 — Costs [USD]\n2 — Weird ] title\n3 — Nested [a [b]] c\n",
        )

        result = self.run_store(root, "validate")

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_bracket_suffix_is_treated_as_title(self) -> None:
        cards = """---

# 1

## First claim [bogus]

Body.
"""
        root = self.make_store(cards=cards, index="1 — First claim [bogus]\n")

        result = self.run_store(root, "validate")

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_annotated_index_rejects_missing_superseded_successor(self) -> None:
        root = self.make_store(
            index="1 — First claim [superseded → 9]\n2 — Second claim\n"
        )

        result = self.run_store(root, "validate")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("successor 9", result.stderr)

    def test_annotated_index_still_checks_title_match(self) -> None:
        root = self.make_store(index="1 — Wrong title [verified]\n2 — Second claim\n")

        result = self.run_store(root, "validate")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("title for 1 is 'Wrong title'", result.stderr)

    def test_add_link_writes_and_validates_reciprocal_pair(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        result = self.run_store(
            root,
            "add-link",
            "--from",
            "1",
            "--to",
            "2",
            "--kind",
            "supports",
            "--why",
            "The first claim provides the rationale for the second.",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        cards = (root / ".notes/zettel.md").read_text(encoding="utf-8")
        self.assertIn("→ 2 (supports): The first claim provides the rationale for the second.", cards)
        self.assertIn("← 1 (supports): The first claim provides the rationale for the second.", cards)
        self.assertEqual(self.run_store(root, "validate").returncode, 0)
        self.assertIn("notes: link 1 supports 2", self.git(root, "log", "--format=%s"))

    def test_init_refuses_a_remote(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        subprocess.run(
            ["git", "-C", str(root / ".notes"), "remote", "add", "origin", "https://example.invalid/notes.git"],
            check=True,
        )

        result = self.run_store(root, "init")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("configured remote", result.stderr)

    def test_init_writes_state_ticket_and_is_idempotent(self) -> None:
        root = self.make_store()
        first = self.run_store(root, "init")
        self.assertEqual(first.returncode, 0, first.stderr)
        state = root / ".notes/.store-state"
        self.assertTrue(state.is_file())
        self.assertIn(".store-state", self.git(root, "ls-files"))
        hook = root / ".notes/.git/hooks/pre-commit"
        self.assertTrue(hook.is_file())

        second = self.run_store(root, "init")

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("ready", second.stdout)

    def test_hand_edit_blocks_add_card_without_touching_history(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        cards_path = root / ".notes/zettel.md"
        cards_path.write_text(cards_path.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
        head_before = self.git(root, "rev-parse", "HEAD")

        result = self.run_store(root, "add-card", "--id", "3", "--title", "New claim", "--body", "Body.")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("modified outside store.py", result.stderr)
        self.assertIn("zettelkasten-notetaking skill", result.stderr)
        self.assertEqual(self.git(root, "rev-parse", "HEAD"), head_before)

    def test_init_creates_guard_file(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        guard = root / ".notes/READ-ME-FIRST-use-skill-zettelkasten-notetaking.md"
        self.assertTrue(guard.is_file())
        self.assertIn("zettelkasten-notetaking", self.git(root, "show", "HEAD:READ-ME-FIRST-use-skill-zettelkasten-notetaking.md"))

    def test_store_resurrects_deleted_guard_file(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        guard = root / ".notes/READ-ME-FIRST-use-skill-zettelkasten-notetaking.md"
        guard.unlink()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        self.assertTrue(guard.is_file())
        guard.unlink()
        self.assertEqual(self.run_store(root, "re-ticket").returncode, 0)
        self.assertTrue(guard.is_file())

    def test_hook_rejects_guard_deletion_and_modification(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        guard = root / ".notes/READ-ME-FIRST-use-skill-zettelkasten-notetaking.md"
        guard.unlink()
        self.git(root, "add", "-A")
        deleted = subprocess.run(
            ["git", "-C", str(root / ".notes"), "commit", "-m", "delete guard"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertNotEqual(deleted.returncode, 0)
        self.assertIn("was deleted", deleted.stderr + deleted.stdout)
        self.git(root, "reset", "--hard")
        guard.write_text("hacked\n", encoding="utf-8")
        self.git(root, "add", "READ-ME-FIRST-use-skill-zettelkasten-notetaking.md")
        modified = subprocess.run(
            ["git", "-C", str(root / ".notes"), "commit", "-m", "modify guard"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertNotEqual(modified.returncode, 0)
        self.assertIn("was modified", modified.stderr + modified.stdout)

    def test_pre_commit_hook_rejects_hand_edited_commit(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        cards_path = root / ".notes/zettel.md"
        cards_path.write_text(cards_path.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
        self.git(root, "add", "zettel.md")

        result = subprocess.run(
            ["git", "-C", str(root / ".notes"), "commit", "-m", "hand edit"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hand edits are not allowed", result.stderr + result.stdout)

    def test_re_ticket_accepts_validated_committed_hand_edit(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        cards_path = root / ".notes/zettel.md"
        cards_path.write_text(
            cards_path.read_text(encoding="utf-8")
            + "---\n\n# 3\n\n## Third claim\n\nHand-committed body.\n",
            encoding="utf-8",
        )
        index_path = root / ".notes/zettel-index.md"
        index_path.write_text(
            index_path.read_text(encoding="utf-8") + "3 — Third claim\n", encoding="utf-8"
        )
        self.git(root, "add", "zettel.md", "zettel-index.md")
        subprocess.run(
            ["git", "-C", str(root / ".notes"), "commit", "--no-verify", "-m", "hand edit"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        result = self.run_store(root, "re-ticket")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("notes: refresh store state", self.git(root, "log", "--format=%s"))
        follow_up = self.run_store(root, "add-card", "--id", "3.1", "--title", "Child claim", "--body", "Body.")
        self.assertEqual(follow_up.returncode, 0, follow_up.stderr)

    def test_set_status_full_ladder_records_rationale_in_commit(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)

        result = self.run_store(
            root, "set-status", "--id", "2", "--status", "verified",
            "--rationale", "checked against sources",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 — Second claim [verified]\n", (root / ".notes/zettel-index.md").read_text())

        result = self.run_store(
            root, "set-status", "--id", "2", "--status", "settled",
            "--rationale", "stable and relied upon",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 — Second claim [settled]\n", (root / ".notes/zettel-index.md").read_text())

        self.assertIn("notes: set 2 verified — checked against sources", self.git(root, "log", "--format=%s"))
        self.assertIn("notes: set 2 settled — stable and relied upon", self.git(root, "log", "--format=%s"))
        self.assertEqual(self.run_store(root, "validate").returncode, 0)
        self.assertEqual(self.git(root, "status", "--porcelain"), "")

    def test_set_status_to_obsolete_keeps_card_and_links_addressable(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        self.assertEqual(
            self.run_store(root, "add-link", "--from", "2", "--to", "1", "--kind", "extends", "--why", "Refines first.").returncode, 0,
        )

        result = self.run_store(root, "set-status", "--id", "1", "--status", "obsolete")
        self.assertEqual(result.returncode, 0, result.stderr)
        index_text = (root / ".notes/zettel-index.md").read_text()
        self.assertIn("1 — First claim [obsolete]\n", index_text)
        self.assertIn("← 2 (extends): Refines first.", (root / ".notes/zettel.md").read_text())
        self.assertEqual(self.run_store(root, "validate").returncode, 0)

    def test_set_status_rejects_illegal_transitions_and_missing_rationale(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        cards_before = (root / ".notes/zettel.md").read_bytes()

        for case in (
            ("--id", "2", "--status", "settled"),                       # draft -> settled: missing rationale
            ("--id", "2", "--status", "draft"),                          # not a set-status target
            ("--id", "2", "--status", "superseded"),                     # reserved for supersede
            ("--id", "9", "--status", "verified", "--rationale", "r"),   # nonexistent card
        ):
            result = self.run_store(root, "set-status", *case)
            self.assertNotEqual(result.returncode, 0, result.stdout)

        verified = self.run_store(
            root, "set-status", "--id", "2", "--status", "verified", "--rationale", "r",
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        for case in (
            ("--id", "2", "--status", "verified", "--rationale", "again"),  # verified -> verified
            ("--id", "1", "--status", "settled", "--rationale", "r"),       # draft -> settled not in ladder
        ):
            result = self.run_store(root, "set-status", *case)
            self.assertNotEqual(result.returncode, 0, result.stdout)

        self.assertEqual(cards_before, (root / ".notes/zettel.md").read_bytes())

    def test_supersede_captures_successor_and_annotates_in_one_commit(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        head_before = self.git(root, "rev-parse", "HEAD")

        result = self.run_store(
            root, "supersede", "--id", "2",
            "--title", "Better claim",
            "--body", "Sharper body.",
            "--rationale", "replaces 2 with a stronger argument",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("superseded 2 by 3", result.stdout)
        cards = (root / ".notes/zettel.md").read_text(encoding="utf-8")
        self.assertIn("# 3", cards)
        self.assertIn("## Better claim", cards)
        self.assertIn("Sharper body.", cards)
        index_text = (root / ".notes/zettel-index.md").read_text()
        self.assertIn("2 — Second claim [superseded → 3]\n", index_text)
        self.assertIn("3 — Better claim\n", index_text)
        self.assertEqual(self.run_store(root, "validate").returncode, 0)
        # Atomic: exactly one new commit carrying both changes.
        subjects = self.git(root, "log", "--format=%s").splitlines()
        self.assertEqual(subjects[0], "notes: supersede 2 by 3 — replaces 2 with a stronger argument")
        self.assertEqual(head_before, self.git(root, "rev-parse", "HEAD^"))
        self.assertEqual(self.git(root, "status", "--porcelain"), "")

    def test_supersede_never_rewrites_inbound_links(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        self.assertEqual(
            self.run_store(root, "add-link", "--from", "2", "--to", "1", "--kind", "extends", "--why", "Refines first.").returncode, 0,
        )
        link_lines_before = [
            line for line in (root / ".notes/zettel.md").read_text(encoding="utf-8").splitlines()
            if line.startswith(("→", "←"))
        ]

        result = self.run_store(
            root, "supersede", "--id", "2", "--title", "Better claim", "--body", "Sharper body.",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        link_lines_after = [
            line for line in (root / ".notes/zettel.md").read_text(encoding="utf-8").splitlines()
            if line.startswith(("→", "←"))
        ]
        self.assertEqual(link_lines_before, link_lines_after)
        self.assertEqual(self.run_store(root, "validate").returncode, 0)

    def test_supersede_rejects_already_superseded_card_unchanged(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        self.assertEqual(
            self.run_store(root, "supersede", "--id", "2", "--title", "Better claim", "--body", "Sharper body.").returncode, 0,
        )
        cards_before = (root / ".notes/zettel.md").read_bytes()
        index_before = (root / ".notes/zettel-index.md").read_bytes()

        result = self.run_store(root, "supersede", "--id", "2", "--title", "Another claim", "--body", "Body.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already superseded", result.stderr)
        self.assertEqual(cards_before, (root / ".notes/zettel.md").read_bytes())
        self.assertEqual(index_before, (root / ".notes/zettel-index.md").read_bytes())

        # supersede of a nonexistent card is rejected too
        result = self.run_store(root, "supersede", "--id", "9", "--title", "X", "--body", "Y")
        self.assertNotEqual(result.returncode, 0)

    def test_re_ticket_refuses_invalid_store(self) -> None:
        root = self.make_store()
        self.assertEqual(self.run_store(root, "init").returncode, 0)
        cards_path = root / ".notes/zettel.md"
        cards_path.write_text(
            cards_path.read_text(encoding="utf-8")
            + "---\n\n# not-an-id\n\n## Broken claim\n\nBody.\n",
            encoding="utf-8",
        )
        self.git(root, "add", "zettel.md")
        subprocess.run(
            ["git", "-C", str(root / ".notes"), "commit", "--no-verify", "-m", "hand edit"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        result = self.run_store(root, "re-ticket")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected `# <numeric.dotted.id>`", result.stderr)


class TestStdinAlias(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = TestStoreCommands("test_add_card_places_child_after_parent_subtree_and_commits")
        self.root = self.helper.make_store()
        self.assertEqual(self.helper.run_store(self.root, "init").returncode, 0)

    def test_add_card_reads_body_from_stdin(self) -> None:
        result = self.helper.run_store(
            self.root, "add-card", "--id", "3", "--title", "Stdin claim", "--body-file", "-",
            input="Stdin body.\n",
        )
        self.assertEqual(result.returncode, 0)
        cards = (self.root / ".notes/zettel.md").read_text(encoding="utf-8")
        self.assertIn("Stdin body.", cards)

    def test_supersede_reads_body_from_stdin(self) -> None:
        result = self.helper.run_store(
            self.root, "supersede", "--id", "1", "--title", "Superseded claim",
            "--body-file", "-", "--rationale", "why",
            input="New body.\n",
        )
        self.assertEqual(result.returncode, 0)
        cards = (self.root / ".notes/zettel.md").read_text(encoding="utf-8")
        self.assertIn("New body.", cards)

    def test_stdin_form_is_byte_identical_to_file_form(self) -> None:
        file_root = self.helper.make_store()
        stdin_root = self.helper.make_store()
        self.assertEqual(self.helper.run_store(file_root, "init").returncode, 0)
        self.assertEqual(self.helper.run_store(stdin_root, "init").returncode, 0)
        body = Path(tempfile.mkdtemp()) / "body.md"
        body.write_text("Identical body.\n", encoding="utf-8")
        self.assertEqual(
            self.helper.run_store(
                file_root, "add-card", "--id", "3", "--title", "T", "--body-file", str(body),
            ).returncode,
            0,
        )
        self.assertEqual(
            self.helper.run_store(
                stdin_root, "add-card", "--id", "3", "--title", "T", "--body-file", "-",
                input=body.read_text(encoding="utf-8"),
            ).returncode,
            0,
        )
        self.assertEqual(
            (file_root / ".notes/zettel.md").read_bytes(),
            (stdin_root / ".notes/zettel.md").read_bytes(),
        )

    def test_inline_body_dash_is_literal(self) -> None:
        result = self.helper.run_store(self.root, "add-card", "--id", "3", "--title", "T", "--body", "-")
        self.assertEqual(result.returncode, 0)
        cards = (self.root / ".notes/zettel.md").read_text(encoding="utf-8")
        self.assertIn("-", cards)


if __name__ == "__main__":
    unittest.main()
