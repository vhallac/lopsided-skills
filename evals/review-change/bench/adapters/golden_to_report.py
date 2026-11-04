#!/usr/bin/env python3
"""Positive control: turn a ReviewBench golden file into a review-report/1.

Feeding the golden findings back through the adapter and then the judge is an
oracle run: recall should be high (the judge should match each candidate to its
source golden). It validates that the adapter preserves the semantic content
the judge needs, independent of the review engine. Only true-positive findings
are replayed; that is the oracle's contract.

  uv run --with pyyaml python golden_to_report.py golden/xxx.json --out oracle.md
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
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    g = json.load(open(args.golden, encoding="utf-8"))
    # Oracle contract: only true positives are replayed.
    findings = [f for f in g["findings"] if f.get("tp_fp") == "tp"]

    fm_findings = []
    body = ["# Review — oracle (golden findings replayed as a review-change report)\n",
            "## Findings\n"]
    for i, f in enumerate(findings, 1):
        fid = f"F{i}"
        sev = SEVERITY_REVERSE.get(str(f.get("severity", "")).lower(), "Minor")
        summary = one_line(f["message"])
        fm_findings.append({"id": fid, "severity": sev, "likelihood": "probable", "summary": summary})
        body.append(f"#### {fid} — {sev}: {summary}\n")
        body.append(f"- **Anchor:** `{f['file']}:{f['start_line']}-{f['end_line']}`")
        body.append(f"- **Claim / expected:** {f['message']}")
        body.append("- **Existing behavior:** as described above.")
        body.append("- **Trigger:** described above.")
        body.append(f"- **Consequence:** {f.get('severity_justification', '')}")
        body.append("- **Evidence:** golden replay.")
        body.append(f"- **Likelihood:** probable")
        body.append("- **Recommended correction:** n/a (oracle).\n")

    fm = {
        "schema": "review-report/1",
        "label": "oracle",
        "round": 1,
        "target": f"pr:{g['pr']['pr_number']}",
        "forge": "github",
        "repo": g["pr"]["repo"].replace("https://github.com/", ""),
        "mode": "change",
        "base": g["pr"]["base"],
        "head": g["pr"]["head"],
        "verdict": "request-changes",
        "findings": fm_findings,
        "unrelated": [],
        "prior": [],
        "waivers": [],
    }
    text = "---\n" + yaml.safe_dump(fm, sort_keys=False, default_flow_style=False) + "---\n\n" + "\n".join(body)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out}: {len(findings)} oracle findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
