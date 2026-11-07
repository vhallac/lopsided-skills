---
description: Kick off a herdr plan agent and have it construct a plan for an issue (no execution)
argument-hint: "<agent-name> <issue-ref> [-- directives]"
---

The plan is always built from the project root: the cwd of the session
invoking this prompt is the project root and must be the agent pane's cwd.

Kick off and plan: agent $1, issue $2. Anything after `--` is an operator
directive: pass it to the agent verbatim as additional context alongside the
issue. Directives carry the operator's decisions and constraints — do not
paraphrase or re-prioritize them.

Requires the agent-mailbox pi extension in this session (`agent_request`,
`agent_wait` tools available). If they are not, report NEEDS_INPUT saying so —
do not degrade to sleep-based or pane-state polling.

1. Start (or reuse) the agent, spawning it idle — do NOT submit the kickoff
   prompt through the script:

   herdr-plan-agent $1 --cwd .

   (No --cwd override: the script defaults to its own $PWD, which is this
   session's cwd = the project root. No prompt argument: the kickoff is
   dispatched as a correlated request in step 2, not via `herdr agent prompt`.)

   Build the kickoff message inline: it must instruct the agent to load issue
   $2 (plus any extra context), run the `plan-work` skill, and follow its
   sizing: small → solve directly and report; larger → produce the
   review-gated plan written to disk under `.todo/` in the agent's cwd
   (`.todo` is gitignored — NEVER `git add`/`git commit` it). The plan header
   MUST carry the issue reference. On completion the agent reports the plan
   file path and the issue number, and stops — no execution.

2. Dispatch the kickoff as a correlated request and block on its outcome:

   - `agent_request` with worker `$1` and the kickoff message → returns a
     `requestId`. If the request fails (worker unreachable), report the
     failure and stop. Do NOT fall back to `herdr agent prompt` sleep-and-
     recheck loops.
   - `agent_wait` on that `requestId` with a generous `timeoutMs` (plan
     construction takes minutes; use 900000). The wait resolves with the
     agent's reply (status + report) or times out.
   - On timeout the request stays pending: re-arm `agent_wait` on the same
     `requestId` once. If a second wait also times out, diagnose with one
     `herdr agent read $1 --source recent --lines 60` (a single read, not a
     polling loop) and escalate to the operator.

3. Gate on the reply's status:

   - `DONE` → report back to the operator: agent name, issue, plan path,
     number of units (parse them from the report).
   - `NEEDS_INPUT` or `BLOCKED` → surface the agent's questions verbatim and
     stop. Do not attempt to answer on the operator's behalf, and do not
     start execution.
   - `FAILED` or a stopped-without-result outcome → treat as blocked: report
     the failure and stop.

This prompt ends at plan construction. Execution is driven by /plan-drive.
