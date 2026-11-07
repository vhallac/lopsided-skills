#!/usr/bin/env python3
"""Parse a review-change `review-report/1` markdown file into finding dicts.

This is the shared piece of the benchmark adapters. It reads the report the
`review-change` skill writes (YAML frontmatter + `#### F<n> — Severity: summary`
blocks) and pulls out, per finding: id, severity, likelihood, summary, the
anchor's file and line range, and the full body text.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

import yaml

HEADING_RE = re.compile(r"^####\s+(F\d+)\s+[—-]\s+([^:]+):\s*(.*)$")
FIELD_RE = re.compile(r"^-\s+\*\*(.+?):?\*\*\s*(.*)$")
BACKTICK_RE = re.compile(r"`([^`]+)`")
PATH_LINE_RE = re.compile(r"^([\w./@+-]+?):(\d+)(?:-(\d+))?$")
PATH_RE = re.compile(r"^[\w./@+-]*[./][\w./@+-]*$")

# Field labels defined by the review-report/1 format. Only these start a new
# field; any other bold bullet inside a field value is a continuation of that
# value (e.g. an unindented `- **Note:** ...` line must not split the field).
KNOWN_FIELDS = {
    "Anchor",
    "Claim / expected",
    "Claim / expected behavior",
    "Existing behavior",
    "Trigger",
    "Consequence",
    "Evidence",
    "Likelihood",
    "Recommended correction",
}

SEVERITY_MAP = {
    "blocking": "high",
    "important": "high",
    "minor": "medium",
    "observation": "low",
}
SEVERITY_REVERSE = {
    "high": "Important",
    "medium": "Minor",
    "low": "Observation",
    "critical": "Blocking",
}


@dataclass
class Finding:
    id: str
    severity: str
    likelihood: str
    summary: str
    fields: dict[str, str] = field(default_factory=dict)
    file: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    @property
    def message(self) -> str:
        """Text the judge matches on: the substance, not the field labels."""
        parts: list[str] = [self.summary]
        for key in (
            "Claim / expected",
            "Existing behavior",
            "Trigger",
            "Consequence",
            "Evidence",
        ):
            val = self.fields.get(key)
            if val:
                parts.append(val)
        return "\n".join(parts).strip()


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("report does not start with frontmatter")
    end = text.index("\n---", 3)
    fm = yaml.safe_load(text[3:end])
    body = text[end + 4 :]
    return fm, body


def _extract_anchor(anchor_text: str) -> tuple[str | None, int | None, int | None]:
    """Find the first file[:line[-line]] in a backticked anchor string."""
    candidates = BACKTICK_RE.findall(anchor_text)
    # Prefer explicit path:line, then path:line-range, then bare path.
    for tok in candidates:
        m = PATH_LINE_RE.match(tok.strip())
        if m:
            f, s, e = m.group(1), int(m.group(2)), m.group(3)
            return f, s, int(e) if e else s
    for tok in candidates:
        tok = tok.strip()
        # A bare path with slashes or a known source extension.
        if PATH_RE.match(tok) and not tok.startswith("mailbox-ext-") and " " not in tok:
            if "/" in tok or re.search(r"\.(mjs|js|ts|tsx|py|go|java|rb|rs|md|yml|yaml|json|sh|toml)$", tok):
                return tok, None, None
    return None, None, None


def parse_report(path: str) -> tuple[dict, list[Finding]]:
    text = open(path, encoding="utf-8").read()
    fm, body = split_frontmatter(text)

    findings: list[Finding] = []
    current: Finding | None = None
    active_field: str | None = None
    for line in body.splitlines():
        m = HEADING_RE.match(line)
        if m:
            current = Finding(
                id=m.group(1),
                severity=m.group(2).strip(),
                likelihood="",
                summary=m.group(3).strip(),
            )
            findings.append(current)
            active_field = None
            continue
        if current is None:
            continue
        if line.startswith("#### U") or line.startswith("## "):
            current = None
            active_field = None
            continue
        fm2 = FIELD_RE.match(line)
        if fm2:
            key = fm2.group(1).strip()
            # Only the known format field labels start a field; any other
            # bold bullet is a continuation of the active field (or, before
            # any field has started, is skipped).
            if key in KNOWN_FIELDS:
                # The method writes "Claim / expected behavior"; normalize to
                # the short label so consumers see one key.
                if key == "Claim / expected behavior":
                    key = "Claim / expected"
                current.fields[key] = fm2.group(2).strip()
                active_field = key
                continue
            if active_field:
                current.fields[active_field] += " " + line.strip()
            continue
        if active_field and line.strip():
            # continuation of a multi-line field, including bulleted lines
            current.fields[active_field] += " " + line.strip()

    # likelihood comes from frontmatter
    fm_findings = {f["id"]: f for f in (fm.get("findings") or [])}
    for f in findings:
        meta = fm_findings.get(f.id, {})
        f.likelihood = str(meta.get("likelihood", "")).strip()
        anchor = f.fields.get("Anchor", "")
        f.file, f.start_line, f.end_line = _extract_anchor(anchor)

    return fm, findings


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: reportlib.py <report.md>", file=sys.stderr)
        return 2
    fm, findings = parse_report(sys.argv[1])
    print(f"report {sys.argv[1]}: {len(findings)} findings")
    for f in findings:
        print(f"  {f.id} {f.severity}/{f.likelihood} anchor={f.file}:{f.start_line}-{f.end_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
