#!/usr/bin/env python3
"""Positive control for the martian adapter: martian golden -> review-report/1.

Martian golden comments carry no file/line, so the anchor is a placeholder; the
martian judge matches on candidate text only, which is exactly what the adapter
must preserve.

  uv run --with pyyaml python martian_golden_to_report.py GOLDEN.json PR_URL --out oracle.md
"""
from __future__ import annotations

import argparse
import json

import yaml

from reportlib import SEVERITY_REVERSE


def one_line(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("golden")
    ap.add_argument("url")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    golden = json.load(open(args.golden, encoding="utf-8"))
    entry = next((p for p in golden if p.get("url") == args.url), None)
    if entry is None:
        raise SystemExit(f"url not found: {args.url}")
    comments = entry["comments"]

    fm_findings = []
    body = [f"# Review — oracle for {args.url}\n", "## Findings\n"]
    for i, c in enumerate(comments, 1):
        fid = f"F{i}"
        sev = SEVERITY_REVERSE.get(str(c.get("severity", "")).lower(), "Minor")
        summary = one_line(c["comment"])
        fm_findings.append({"id": fid, "severity": sev, "likelihood": "probable", "summary": summary})
        body.append(f"#### {fid} — {sev}: {summary}\n")
        body.append(f"- **Anchor:** `unknown-file:1-1`")
        body.append(f"- **Claim / expected:** {c['comment']}")
        body.append("- **Existing behavior:** as described above.")
        body.append("- **Trigger:** described above.")
        body.append("- **Consequence:** described above.")
        body.append("- **Evidence:** martian golden replay.")
        body.append("- **Likelihood:** probable")
        body.append("- **Recommended correction:** n/a (oracle).\n")

    fm = {
        "schema": "review-report/1",
        "label": "oracle",
        "round": 1,
        "target": args.url,
        "forge": "github",
        "repo": "calcom/cal.com",
        "mode": "change",
        "base": "0" * 40,
        "head": "0" * 40,
        "verdict": "request-changes",
        "findings": fm_findings,
        "unrelated": [],
        "prior": [],
        "waivers": [],
    }
    text = "---\n" + yaml.safe_dump(fm, sort_keys=False, default_flow_style=False) + "---\n\n" + "\n".join(body)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out}: {len(comments)} oracle findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
