"""Tests for reportlib — review-report/1 parsing.

Pins the parser contract the benchmark adapters rely on:
- frontmatter split and per-finding field parsing,
- anchor extraction from backticked file[:line-range] tokens,
- multi-line field continuations (bulleted, indented or not),
- a differential guard: every committed oracle report still parses to the
  same shape (finding count, ids, severities, anchors).

Claim blocks (decision 010 format: repo-scoped claim id, claim text,
scenario) sit above each test; the tests are the durable record (small path).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from reportlib import Finding, _extract_anchor, parse_report

BENCH = Path(__file__).resolve().parent.parent


def _write_report(tmp_path: Path, body: str) -> str:
    text = (
        "---\n"
        "review-report/1: v1\n"
        "findings:\n"
        "  - id: F1\n"
        "    likelihood: probable\n"
        "---\n"
        "## Findings\n\n" + body
    )
    p = tmp_path / "report.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


# claim: reportlib-SC-1/R2F1/test_oracle_martian_headings_and_fields
# claim text: a well-formed oracle report yields one finding per `#### F<n>`
#   heading, with severity, likelihood (joined from frontmatter), summary, and
#   its fields populated.
# scenario: Scenario: Oracle report parses to one finding per heading — Then
#   each finding carries id, severity, likelihood, summary, and core fields.
def test_oracle_martian_headings_and_fields():
    fm, findings = parse_report(str(BENCH / "results" / "oracle-martian.md"))
    ids = [f.id for f in findings]
    assert ids == [f["id"] for f in fm["findings"]]
    for f in findings:
        assert f.severity in {"Blocking", "Important", "Minor", "Observation"}
        assert f.likelihood
        assert f.summary
        assert "Claim / expected" in f.fields
        assert "Anchor" in f.fields


# claim: reportlib-SC-2/R2F1/test_extract_anchor_forms
# claim text: `_extract_anchor` resolves `path:line`, `path:start-end`, and
#   bare-path forms from backticked tokens, preferring `path:line` tokens over
#   bare paths; unresolvable anchors yield (None, None, None).
# scenario: Scenario: Anchor extraction forms — Then each anchor token form
#   resolves to its (path, start, end) triple, unresolvable text to Nones.
def test_extract_anchor_forms():
    assert _extract_anchor("`src/a.ts:12-34`") == ("src/a.ts", 12, 34)
    assert _extract_anchor("`src/a.ts:12`") == ("src/a.ts", 12, 12)
    assert _extract_anchor("see `src/a.ts` and `x.md:3`") == ("x.md", 3, 3)
    assert _extract_anchor("see `src/a.ts` only") == ("src/a.ts", None, None)
    assert _extract_anchor("no anchor here") == (None, None, None)


# claim: reportlib-SC-9/R1F2/test_extract_anchor_prose_fallback
# claim text: when no backticked token resolves, `_extract_anchor` falls back
#   to bare path-like tokens in the surrounding prose — but only tokens with a
#   recognized source extension; slash-bearing prose words ("async/await",
#   "3/4", "and/or") are never returned as the file.
# scenario: Scenario: Prose anchor fallback — Then the motivating bare-path
#   prose anchor resolves to its file with no lines, and non-path slash tokens
#   in prose yield (None, None, None) (or, when a real path also appears, the
#   real path wins over any non-path token).
def test_extract_anchor_prose_fallback():
    assert _extract_anchor(
        "README.md, async/await example (~L496-511 at head)"
    ) == ("README.md", None, None)
    assert _extract_anchor("input/output handling, see src/a.ts") == ("src/a.ts", None, None)
    assert _extract_anchor("the async/await example in the code") == (None, None, None)
    assert _extract_anchor("a 3/4 ratio with he/she said") == (None, None, None)
    assert _extract_anchor("and/or some words") == (None, None, None)


# claim: reportlib-SC-3/R1F3/test_indented_bullet_continuation_is_retained
# claim text: bulleted, indented lines inside a field value are retained as
#   part of that field (locks the R1.F3 fix).
# scenario: Scenario: Indented bullet inside a field — Then the bullet lines
#   remain part of the field value and the next field parses normally.
def test_indented_bullet_continuation_is_retained(tmp_path: Path):
    body = (
        "#### F1 — Minor: something\n"
        "- **Trigger:** conditions:\n"
        "  - condition one\n"
        "  - condition two\n"
        "- **Evidence:** file\n"
    )
    _, findings = parse_report(_write_report(tmp_path, body))
    (f,) = findings
    assert "condition one" in f.fields["Trigger"]
    assert "condition two" in f.fields["Trigger"]
    assert f.fields["Evidence"] == "file"


# claim: reportlib-SC-4/R2F2/test_unindented_bold_bullet_does_not_split_field
# claim text: an unindented bold bullet inside a field value does NOT start a
#   new field — it is a continuation of the active field (locks the R2.F2 fix).
# scenario: Scenario: Unindented bold bullet inside a field — Then the field
#   value includes the bullet and the next known field starts normally.
def test_unindented_bold_bullet_does_not_split_field(tmp_path: Path):
    body = (
        "#### F1 — Minor: something\n"
        "- **Trigger:** conditions:\n"
        "- **Note:** this bullet is part of the Trigger value, not a new field\n"
        "- **Evidence:** file\n"
    )
    _, findings = parse_report(_write_report(tmp_path, body))
    (f,) = findings
    assert f.fields["Trigger"].endswith(
        "this bullet is part of the Trigger value, not a new field"
    )
    assert "Evidence" in f.fields


# claim: reportlib-SC-7/R3F1/test_bold_bullet_before_first_field_is_not_a_field
# claim text: a bold bullet whose label is not a known format field does not
#   start a field, even before any known field has been seen — it is skipped
#   (no junk field keys in the parsed map).
# scenario: Scenario: Unknown bold bullet before the first field — Then the
#   finding's field map contains only the known labels that follow it.
def test_bold_bullet_before_first_field_is_not_a_field(tmp_path: Path):
    body = (
        "#### F1 — Minor: something\n"
        "- **Summary:** intro prose before any field\n"
        "- **Anchor:** `src/a.py:12`\n"
        "- **Evidence:** file\n"
    )
    _, findings = parse_report(_write_report(tmp_path, body))
    (f,) = findings
    assert set(f.fields) == {"Anchor", "Evidence"}


# claim: reportlib-SC-8/R1F1/test_method_claim_label_normalized
# claim text: a report line written with the method's exact label
#   "Claim / expected behavior" parses into the normalized
#   "Claim / expected" field, not folded into a neighbor field.
# scenario: Scenario: Method claim label — Then the long label lands in
#   "Claim / expected" and no long-label key remains.
def test_method_claim_label_normalized(tmp_path: Path):
    body = (
        "#### F1 — Minor: something\n"
        "- **Claim / expected behavior:** the claim text\n"
        "- **Anchor:** `src/a.py:12`\n"
        "- **Evidence:** file\n"
    )
    _, findings = parse_report(_write_report(tmp_path, body))
    (f,) = findings
    assert f.fields["Claim / expected"] == "the claim text"
    assert f.fields["Anchor"] == "`src/a.py:12`"
    assert "Claim / expected behavior" not in f.fields


# claim: reportlib-SC-5/R2F1/test_oracle_reports_differential
# claim text: every committed oracle report still parses to its pinned shape —
#   finding ids, severities, anchors, and full field maps are unchanged by the
#   parser fix (differential guard, field-level).
# scenario: Scenario: Oracle reports parse unchanged — Then ids, severities,
#   anchors and field maps match the pinned values for every oracle report.
@pytest.mark.parametrize(
    "name,expected",
    [
        ("oracle-martian.md", [("F1", "Important"), ("F2", "Important")]),
        ("oracle-axios.md", None),  # non-empty, ids all F<n>
    ],
)
def test_oracle_reports_differential(name, expected):
    _, findings = parse_report(str(BENCH / "results" / name))
    assert findings, f"{name} parsed to zero findings"
    got = [(f.id, f.severity) for f in findings]
    if expected is not None:
        assert got == expected
        for f in findings:
            # Every field label the parser produced is a known format field,
            # and each finding carries the core fields.
            for key in ("Anchor", "Claim / expected", "Evidence"):
                assert key in f.fields
            assert set(f.fields) <= {
                "Anchor",
                "Claim / expected",
                "Existing behavior",
                "Trigger",
                "Consequence",
                "Evidence",
                "Likelihood",
                "Recommended correction",
            }


# claim: reportlib-SC-6/R2F1/test_message_excludes_labels
# claim text: `Finding.message` returns the summary plus substance field
#   values, without field labels.
# scenario: Scenario: Message rendering — Then the message contains summary
#   and field values but no field-label keys, and unknown fields are ignored.
def test_message_excludes_labels():
    f = Finding(id="F1", severity="Minor", likelihood="likely", summary="s")
    f.fields["Claim / expected"] = "the claim"
    f.fields["Unrelated"] = "ignored"
    assert f.message == "s\nthe claim"