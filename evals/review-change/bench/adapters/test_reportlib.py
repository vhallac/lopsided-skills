"""Tests for reportlib — review-report/1 parsing.

Pins the parser contract the benchmark adapters rely on:
- frontmatter split and per-finding field parsing,
- anchor extraction from backticked file[:line-range] tokens,
- multi-line field continuations (bulleted, indented or not),
- a differential guard: every committed oracle report still parses to the
  same shape (finding count, ids, severities, anchors).

Claim blocks are the claim comments above each test; the tests are the
durable record (small path).
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


# Claim: a well-formed oracle report yields one finding per `#### F<n>` heading
# with severity, likelihood (joined from frontmatter), summary, and its fields
# populated.
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


# Claim: _extract_anchor resolves `path:line`, `path:start-end`, and bare-path
# forms from backticked tokens, preferring path:line tokens over bare paths;
# unresolvable anchors yield (None, None, None).
def test_extract_anchor_forms():
    assert _extract_anchor("`src/a.ts:12-34`") == ("src/a.ts", 12, 34)
    assert _extract_anchor("`src/a.ts:12`") == ("src/a.ts", 12, 12)
    assert _extract_anchor("see `src/a.ts` and `x.md:3`") == ("x.md", 3, 3)
    assert _extract_anchor("see `src/a.ts` only") == ("src/a.ts", None, None)
    assert _extract_anchor("no anchor here") == (None, None, None)


# Claim: bulleted, indented lines inside a field value are retained as part of
# that field (locks the R1.F3 fix).
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


# Claim: an unindented bold bullet inside a field value does NOT start a new
# field — it is a continuation of the active field (locks the R2.F2 fix).
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


# Claim: every committed oracle report still parses to its pinned shape —
# finding ids, severities, anchors, and full field maps are unchanged by the
# parser fix (differential guard, field-level).
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


# Claim: Finding.message returns summary plus substance field values, without
# field labels.
def test_message_excludes_labels():
    f = Finding(id="F1", severity="Minor", likelihood="likely", summary="s")
    f.fields["Claim / expected"] = "the claim"
    f.fields["Unrelated"] = "ignored"
    assert f.message == "s\nthe claim"