#!/usr/bin/env python3
"""Black-box tests for plan.py."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("plan.py")

GOAL = "- Final artefacts: the plan\n- Must not lose: provenance"
BOUNDS = "- Work unit: one unit\n- Stop rule: 1 unit per run"


class TestPlanCommands(unittest.TestCase):
    def make_root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        # plan.py archive requires a git repo (archive lands in the common
        # git dir), so give every test root one.
        subprocess.run(["git", "init", "-q", str(root)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return root

    def run_plan(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args, str(root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def init(self, root: Path, name: str = "Task") -> subprocess.CompletedProcess[str]:
        return self.run_plan(
            root, "init", "--name", name, "--goal", GOAL, "--bounds", BOUNDS
        )

    def add_unit(self, root: Path, label: str = "Do the thing", *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_plan(
            root,
            "add-unit",
            "--label", label,
            "--input", "in.md",
            "--scope", "the change",
            "--output", "out.md",
            "--verify", "test -f out.md",
            *extra,
        )

    def plan_text(self, root: Path) -> str:
        return (root / ".todo" / "task_plan.md").read_text(encoding="utf-8")

    # --- init ---

    def test_init_creates_three_files_and_ticket(self) -> None:
        root = self.make_root()
        result = self.init(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        todo = root / ".todo"
        self.assertTrue((todo / "task_plan.md").is_file())
        self.assertTrue((todo / "findings.md").is_file())
        self.assertTrue((todo / "progress.md").is_file())
        self.assertTrue((todo / ".plan-state").is_file())
        text = self.plan_text(root)
        self.assertIn("# Task", text)
        self.assertIn("## Goal memory", text)
        self.assertIn("## Bounds", text)
        self.assertIn("## Work units", text)

    def test_init_creates_guard_file(self) -> None:
        root = self.make_root()
        self.init(root)
        guard = root / ".todo" / "READ-ME-FIRST-use-skill-large-task-slicing.md"
        self.assertTrue(guard.is_file())
        body = guard.read_text(encoding="utf-8")
        self.assertIn("large-task-slicing", body)
        self.assertIn("plan.py", body)

    def test_init_writes_guard_frontmatter(self) -> None:
        root = self.make_root()
        self.init(root)
        text = self.plan_text(root)
        self.assertTrue(text.startswith("---\nguard: |\n"), text[:40])
        self.assertIn("large-task-slicing", text)
        self.assertLess(text.index("---\n", 4), text.index("# Task"))

    def test_mutating_command_resurrects_deleted_guard_file(self) -> None:
        root = self.make_root()
        self.init(root)
        guard = root / ".todo" / "READ-ME-FIRST-use-skill-large-task-slicing.md"
        guard.unlink()
        self.assertEqual(self.add_unit(root, "First").returncode, 0)
        self.assertTrue(guard.is_file())
        self.assertIn("large-task-slicing", guard.read_text(encoding="utf-8"))

    def test_mutating_command_restores_altered_guard_file(self) -> None:
        root = self.make_root()
        self.init(root)
        guard = root / ".todo" / "READ-ME-FIRST-use-skill-large-task-slicing.md"
        guard.write_text("tampered\n", encoding="utf-8")
        self.assertEqual(self.add_unit(root, "First").returncode, 0)
        self.assertNotIn("tampered", guard.read_text(encoding="utf-8"))

    def test_validate_refuses_missing_guard_frontmatter(self) -> None:
        root = self.make_root()
        self.init(root)
        plan = root / ".todo" / "task_plan.md"
        text = plan.read_text(encoding="utf-8")
        plan.write_text(text[text.index("# Task"):], encoding="utf-8")
        result = self.run_plan(root, "validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("guard frontmatter", result.stderr)

    def test_init_refuses_a_second_plan(self) -> None:
        root = self.make_root()
        self.assertEqual(self.init(root).returncode, 0)
        second = self.init(root)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already exists", second.stderr)

    # --- add-unit ---

    def test_add_unit_assigns_increasing_ids_and_appends_at_tail(self) -> None:
        root = self.make_root()
        self.init(root)
        self.assertEqual(self.add_unit(root, "First").returncode, 0)
        self.assertEqual(self.add_unit(root, "Second").returncode, 0)
        text = self.plan_text(root)
        self.assertIn("- [ ] unit-001 — First", text)
        self.assertIn("- [ ] unit-002 — Second", text)
        self.assertLess(text.index("unit-001"), text.index("unit-002"))
        self.assertIn("appended at tail", text)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)

    def test_add_unit_after_places_position_but_keeps_new_id(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root, "First")
        self.add_unit(root, "Second")
        result = self.add_unit(root, "Inserted", "--after", "unit-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.plan_text(root)
        # New unit gets a fresh ID (never renumbered) but sits after unit-001.
        self.assertIn("- [ ] unit-003 — Inserted", text)
        self.assertLess(text.index("unit-001"), text.index("unit-003"))
        self.assertLess(text.index("unit-003"), text.index("unit-002"))
        self.assertIn("placed after unit-001", text)

    def test_add_unit_after_frontier_inserts_after_first_open(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root, "First")
        self.add_unit(root, "Second")
        self.run_plan(root, "complete", "unit-001", "--evidence", "done")
        result = self.add_unit(root, "Amendment", "--after", "frontier")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.plan_text(root)
        self.assertIn("- [ ] unit-003 — Amendment", text)
        self.assertLess(text.index("unit-002"), text.index("unit-003"))

    # --- complete ---

    def test_complete_marks_done_and_records_evidence(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        self.add_unit(root, "Second")  # keep the plan alive past this complete
        result = self.run_plan(root, "complete", "unit-001", "--evidence", "test -f out.md -> ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.plan_text(root)
        self.assertIn("- [x] unit-001", text)
        self.assertIn("done ", text)
        self.assertIn("test -f out.md -> ok", text)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)

    def test_complete_requires_evidence(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        result = self.run_plan(root, "complete", "unit-001")
        self.assertNotEqual(result.returncode, 0)

    def test_complete_accepts_multiline_evidence(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        self.add_unit(root, "Second")
        result = self.run_plan(root, "complete", "unit-001", "--evidence", "line one\nline two\n\nline four")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)
        hist = self.run_plan(root, "history").stdout
        self.assertIn("line one\nline two\n\nline four", hist)

    def test_complete_of_last_unit_archives_automatically(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        result = self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((root / ".todo").exists())
        archives = list((root / ".git").glob(".todo-*.tar.gz"))
        self.assertEqual(len(archives), 1)
        self.assertIn("OK: archived .todo/ to", result.stdout)
        self.assertIn(str(archives[0]), result.stdout)

    def test_complete_last_unit_no_archive_skips_archival(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        result = self.run_plan(root, "complete", "unit-001", "--evidence", "ok", "--no-archive")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((root / ".todo").is_dir())
        self.assertFalse(list((root / ".git").glob(".todo-*.tar.gz")))
        self.assertIn("not archived", result.stdout)
        self.assertIn(str(root), result.stdout)
        # the archive command still works afterwards
        arch = self.run_plan(root, "archive")
        self.assertEqual(arch.returncode, 0, arch.stderr)
        self.assertFalse((root / ".todo").exists())

    def test_complete_last_unit_archive_failure_degrades_to_note(self) -> None:
        # no git repo -> archive() raises
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.init(root)
        self.add_unit(root)
        result = self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOTE: automatic archive failed", result.stdout)
        self.assertTrue((root / ".todo").is_dir())

    def test_complete_of_mid_plan_unit_does_not_archive(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        self.add_unit(root, "Second")
        result = self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((root / ".todo").is_dir())
        self.assertNotIn("archived", result.stdout)

    def test_complete_refuses_terminal_unit(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        self.add_unit(root, "Second")
        self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        again = self.run_plan(root, "complete", "unit-001", "--evidence", "again")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already", again.stderr)

    # --- block ---

    def test_block_records_kind_and_reason(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        result = self.run_plan(root, "block", "unit-001", "--kind", "code", "--reason", "type error")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.plan_text(root)
        self.assertIn("- [!] unit-001", text)
        self.assertIn("blocked ", text)
        self.assertIn("[code]", text)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)

    def test_block_refuses_bad_kind(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        result = self.run_plan(root, "block", "unit-001", "--kind", "flaky", "--reason", "x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kind must be one of", result.stderr)

    # --- cancel ---

    def test_cancel_keeps_label_and_appends_reason(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root, "Obsolete work")
        result = self.run_plan(root, "cancel", "unit-001", "--reason", "no longer needed")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.plan_text(root)
        self.assertIn("- [-] unit-001 — Obsolete work", text)  # label preserved
        self.assertIn("cancelled ", text)
        self.assertIn("no longer needed", text)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)

    def test_cancel_refuses_done_unit(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        self.add_unit(root, "Second")
        self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        result = self.run_plan(root, "cancel", "unit-001", "--reason", "x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("never cancelled", result.stderr)

    # --- status / history ---

    def test_status_reports_frontier_contract_and_buckets(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root, "First")
        self.add_unit(root, "Second")
        self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        out = self.run_plan(root, "status").stdout
        self.assertIn("Current: unit-002 — Second", out)
        self.assertIn("verify: test -f out.md", out)
        self.assertIn("Done: unit-001", out)
        self.assertIn("Remaining open: 1", out)

    def test_history_lists_events_in_order(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root, "First")
        self.add_unit(root, "Second")
        self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        hist = self.run_plan(root, "history").stdout
        self.assertIn("unit-001: added", hist)
        self.assertIn("unit-001: done", hist)
        self.assertLess(hist.index("added"), hist.index("done"))

    # --- archive ---

    def test_archive_refuses_unfinished_then_cleans_up(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        refused = self.run_plan(root, "archive")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not complete", refused.stderr)
        self.assertTrue((root / ".todo").is_dir())

        self.add_unit(root, "Second")
        # completing the remaining units archives automatically (see
        # test_complete_of_last_unit_archives_automatically); .todo/ is gone
        # and a manual archive would just report there is no plan.
        self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        done = self.run_plan(root, "complete", "unit-002", "--evidence", "ok")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((root / ".todo").exists())
        # the archive lands in the common git dir (worktree-safe), not root
        self.assertTrue(list((root / ".git").glob(".todo-*.tar.gz")))

    def test_archive_treats_cancelled_as_terminal(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        self.run_plan(root, "cancel", "unit-001", "--reason", "dropped")
        result = self.run_plan(root, "archive")
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- tamper ticket / repair ---

    def test_hand_edit_blocks_next_command(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root, "First")
        plan = root / ".todo" / "task_plan.md"
        plan.write_text(plan.read_text(encoding="utf-8").replace("First", "Hacked"), encoding="utf-8")
        result = self.add_unit(root, "Another")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("modified outside plan.py", result.stderr)

    def test_re_ticket_blesses_valid_hand_edit(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root, "First")
        plan = root / ".todo" / "task_plan.md"
        # A benign hand edit: refine a label. Valid, but the ticket must be refreshed.
        plan.write_text(
            plan.read_text(encoding="utf-8").replace("— First", "— First (refined)"),
            encoding="utf-8",
        )
        refreshed = self.run_plan(root, "re-ticket")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        follow_up = self.add_unit(root, "Second")
        self.assertEqual(follow_up.returncode, 0, follow_up.stderr)

    def test_re_ticket_refuses_invalid_hand_edit(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        plan = root / ".todo" / "task_plan.md"
        # Invalid: drop the `verify` contract line.
        plan.write_text(
            plan.read_text(encoding="utf-8").replace("  - verify: test -f out.md\n", ""),
            encoding="utf-8",
        )
        refused = self.run_plan(root, "re-ticket")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("missing `verify`", refused.stderr)

    def test_validate_catches_state_mismatch(self) -> None:
        root = self.make_root()
        self.init(root)
        self.add_unit(root)
        plan = root / ".todo" / "task_plan.md"
        # Flip the checkbox to done without a `done` event.
        plan.write_text(
            plan.read_text(encoding="utf-8").replace("- [ ] unit-001", "- [x] unit-001"),
            encoding="utf-8",
        )
        result = self.run_plan(root, "validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match its last event", result.stderr)


    # --- falsify (issue-85) ---

    # claim: issue-85-SC-1/none-falsifier-requires-a-reason/test_add_unit_rejects_none_falsifier_without_reason
    # claim text: an add-unit falsify entry of kind `none` without a reason is rejected; `none:` with a non-empty reason is accepted
    # scenario: Scenario: none falsifier requires a reason — When add-unit is called with falsify "none" and no reason Then add-unit is rejected with an error naming the missing reason; Scenario: none falsifier with reason is accepted — When add-unit is called with falsify "none: pure rename; compiler is the guard" Then the unit record contains that falsify entry verbatim
    def test_add_unit_rejects_none_falsifier_without_reason(self) -> None:
        root = self.make_root()
        self.init(root)
        for bad in ("none", "none:", "none:   "):
            result = self.add_unit(root, "Bad", "--falsify", bad)
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("requires a reason", result.stderr)
            self.assertEqual(self.run_plan(root, "validate").returncode, 0)
        good = self.add_unit(root, "Good", "--falsify", "none: pure rename; compiler is the guard")
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn(
            "  - falsify: none: pure rename; compiler is the guard",
            self.plan_text(root),
        )

    def test_add_unit_rejects_unknown_falsify_kind(self) -> None:
        root = self.make_root()
        self.init(root)
        result = self.add_unit(root, "Bad", "--falsify", "bogus: something went wrong")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kind must be one of", result.stderr)

    # claim: issue-85-SC-2/complete-refuses-without-recorded-falsifier-outcomes/test_complete_falsify_outcome_enforcement
    # claim text: a unit declaring mutation/input falsifiers is refused at complete until every declared falsifier has a recorded outcome; once all outcomes are recorded the unit completes and the outcomes appear in the event trail
    # scenario: Scenario: complete refuses without recorded falsifier outcomes — When complete is called with evidence but no falsify-outcome Then complete is refused and the unit stays open; Scenario: complete accepts once all outcomes are recorded — When complete is called with evidence and a matching falsify-outcome Then the unit is done and the outcome appears in the event trail
    def test_complete_falsify_outcome_enforcement(self) -> None:
        root = self.make_root()
        self.init(root)
        result = self.add_unit(
            root,
            "Guarded",
            "--falsify", "mutation: flip-guard: verify must fail with assertion error",
            "--falsify", "input: dup-label: verify must flag the duplicate",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.add_unit(root, "Second")  # keep the plan alive past this complete
        # refused while outcomes are missing; unit stays open
        refused = self.run_plan(root, "complete", "unit-001", "--evidence", "ok")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("without recorded outcomes", refused.stderr)
        self.assertIn("flip-guard", refused.stderr)
        self.assertIn("- [ ] unit-001", self.plan_text(root))
        # one of two outcomes is still not enough
        partial = self.run_plan(
            root, "complete", "unit-001", "--evidence", "ok",
            "--falsify-outcome", "flip-guard: verify failed with assertion error",
        )
        self.assertNotEqual(partial.returncode, 0)
        self.assertIn("dup-label", partial.stderr)
        # an outcome for an undeclared label is a typo, not a pass
        unknown = self.run_plan(
            root, "complete", "unit-001", "--evidence", "ok",
            "--falsify-outcome", "nope: nothing",
            "--falsify-outcome", "flip-guard: verify failed with assertion error",
            "--falsify-outcome", "dup-label: verify flagged the duplicate",
        )
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("does not declare", unknown.stderr)
        # all outcomes recorded -> completion succeeds and outcomes hit the trail
        done = self.run_plan(
            root, "complete", "unit-001", "--evidence", "verify ok",
            "--falsify-outcome", "flip-guard: verify failed with assertion error",
            "--falsify-outcome", "dup-label: verify flagged the duplicate",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("- [x] unit-001", self.plan_text(root))
        hist = self.run_plan(root, "history").stdout
        self.assertIn("falsify-outcome: flip-guard: verify failed with assertion error", hist)
        self.assertIn("falsify-outcome: dup-label: verify flagged the duplicate", hist)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)

    # claim: issue-85-SC-3/declared-falsifiers-render-next-to-verify-and-survive-round-trips/test_falsify_entries_render_next_to_verify_and_survive_roundtrips
    # claim text: a unit's declared falsify entries render in task_plan.md next to the verify line and survive validate/history round-trips
    # scenario: Scenario: declared falsifiers render next to verify and survive round-trips — Given a unit declaring one mutation and one input falsifier Then task_plan.md lists each falsify entry under the unit And validate and history report the plan as valid
    def test_falsify_entries_render_next_to_verify_and_survive_roundtrips(self) -> None:
        root = self.make_root()
        self.init(root)
        result = self.add_unit(
            root,
            "Guarded",
            "--falsify", "mutation: flip-guard: verify must fail",
            "--falsify", "input: bad-input: verify must reject it",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.plan_text(root)
        self.assertIn("  - falsify: mutation: flip-guard: verify must fail", text)
        self.assertIn("  - falsify: input: bad-input: verify must reject it", text)
        verify_at = text.index("  - verify: test -f out.md")
        self.assertGreater(text.index("  - falsify: mutation"), verify_at)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)
        # the recorded entries survive a history round-trip and re-validation
        self.assertEqual(self.run_plan(root, "re-ticket").returncode, 0)
        self.assertEqual(self.run_plan(root, "validate").returncode, 0)
        self.assertIn("flip-guard", self.plan_text(root))

class TestStdinAlias(unittest.TestCase):
    """'-' as --<key>-file reads stdin; inline '-' stays literal."""

    def make_root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        # plan.py archive requires a git repo (archive lands in the common
        # git dir), so give every test root one.
        subprocess.run(["git", "init", "-q", str(root)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return root

    def run_plan_input(self, stdin_text: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_init_goal_and_bounds_via_stdin(self) -> None:
        root = self.make_root()
        result = self.run_plan_input(
            GOAL,
            "init", "--name", "T", "--goal-file", "-", "--bounds", BOUNDS,
            str(root),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(GOAL, (root / ".todo" / "task_plan.md").read_text(encoding="utf-8"))

    def test_stdin_form_matches_file_form(self) -> None:
        goal_file = self.make_root() / "goal.md"
        goal_file.write_text(GOAL, encoding="utf-8")
        root_a = self.make_root()
        via_stdin = self.run_plan_input(
            GOAL, "init", "--name", "T", "--goal-file", "-", "--bounds", BOUNDS, str(root_a)
        )
        root_b = self.make_root()
        via_file = self.run_plan_input(
            "", "init", "--name", "T", "--goal-file", str(goal_file), "--bounds", BOUNDS, str(root_b)
        )
        self.assertEqual(via_stdin.returncode, 0, via_stdin.stderr)
        self.assertEqual(via_file.returncode, 0, via_file.stderr)
        a = (root_a / ".todo" / "task_plan.md").read_text(encoding="utf-8")
        b = (root_b / ".todo" / "task_plan.md").read_text(encoding="utf-8")
        self.assertEqual(a, b)

    def test_inline_dash_is_literal(self) -> None:
        root = self.make_root()
        result = self.run_plan_input(
            "piped", "init", "--name", "T", "--goal", "-", "--bounds", "b", str(root)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (root / ".todo" / "task_plan.md").read_text(encoding="utf-8")
        self.assertIn("-", text)
        self.assertNotIn("piped", text)


if __name__ == "__main__":
    unittest.main()
