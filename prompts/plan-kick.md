---
description: Kick off a herdr plan agent and have it construct a plan for an issue
argument-hint: "<agent-name> <issue-ref> [-- directives]"
---

The plan is always built from the project root: the cwd of the session
invoking this prompt is the project root and must be the agent pane's cwd.

`$1` is the herdr agent name. Correlated requests address the agent's
**pane id**, not the agent name: before dispatching, resolve the pane id
once (step 2) and use it as the `worker` identity for `agent_request` and
when handing off to /plan-drive.

Kick off and plan: agent $1, issue $2. Anything after `--` is an operator
directive: pass it to the agent verbatim as additional context alongside the
issue. Directives carry the operator's decisions and constraints — do not
paraphrase or re-prioritize them.

Requires the agent-mailbox pi extension in this session (`agent_request`,
`agent_wait` tools available). If they are not, report NEEDS_INPUT saying so —
do not degrade to sleep-based or pane-state polling.

1. Start (or reuse) the agent, spawning it idle — do NOT submit the kickoff
   prompt through the script. Precondition: the `herdr-plan-agent` wrapper
   must be on PATH (the pi install does not put package `bin` entries there —
   see the README Installation section); if it is not found, report
   NEEDS_INPUT saying so.

   herdr-plan-agent $1

   (No --cwd override and no prompt argument: the wrapper runs the agent in
   its own $PWD, which is this session's cwd = the project root. The kickoff
   message is registered in step 2 and then DELIVERED to the pane in a
   single follow-up `herdr agent prompt` — see step 2. Delivery is one
   shot, never a sleep-and-recheck loop.)

   Build the kickoff message inline: it must instruct the agent to load issue
   $2 (plus any extra context), run the `plan-work` skill, and follow its
   sizing: small → solve directly and report; larger → produce the
   review-gated plan written to disk under `.todo/` in the agent's cwd
   (`.todo` is gitignored — NEVER `git add`/`git commit` it). The plan header
   MUST carry the issue reference. On completion the agent reports the plan
   file path, the issue number, and the number of units in the plan (for the
   small path: a `solved directly` report instead), and stops.

2. Resolve the worker's pane id, then dispatch the kickoff as a correlated
   request and block on its outcome:

   - Resolve the pane id for agent `$1`: `herdr agent get $1` and parse
     `pane_id` from its JSON. This pane id is what the extension bound the
     agent's session identity under (via `HERDR_PANE_ID`); the agent name
     alone is NOT a valid `agent_request` worker. If the agent has no pane
     id (not started), report the failure and stop.
   - `agent_request` with worker set to the resolved **pane id** and the
     kickoff message → returns a `requestId`. If the request fails (worker
     unreachable), report the failure and stop.

     `agent_request` only registers and settles the request in the mailbox
     — it does NOT put the message in front of the agent. Delivery is your
     job, in the same step, via a single blocking prompt to the pane:

     herdr agent prompt $1 -- "Request <requestId>: <full kickoff message
     text from step 1>. You MUST answer this request via
     agent_reply(requestId, ...) with your status (DONE | NEEDS_INPUT |
     BLOCKED | FAILED) and report. Do not answer any other way — an
     un-replied request never settles."

     The delivered message MUST carry all three parts: (a) the kickoff
     instruction text, (b) the `requestId`, (c) the explicit obligation to
     respond with `agent_reply(requestId, ...)`.

     This `herdr agent prompt` is delivery only — a single blocking call.
     Never use `herdr agent prompt` as a wait/polling mechanism; blocking on
     the outcome is `agent_wait` on the `requestId` below.
   - `agent_wait` on that `requestId` with a generous `timeoutMs` (plan
     construction takes minutes; use 900000). The wait resolves with the
     agent's reply (status + report) or times out — the reply only exists
     because the agent answered via `agent_reply`, which is why the
     delivery step above is mandatory.
   - On timeout the request stays pending: re-arm `agent_wait` on the same
     `requestId` once. If a second wait also times out, diagnose with one
     `herdr agent read $1 --source recent --lines 60` (a single read, not a
     polling loop) and escalate to the operator.

3. Gate on the reply's status:

   - `DONE` → report back to the operator: agent name, issue, plan path,
     number of units (parse them from the report; for a solved-directly
     small issue, report that the issue was closed directly).
   - `NEEDS_INPUT` or `BLOCKED` → surface the agent's questions verbatim and
     stop. Do not attempt to answer on the operator's behalf, and do not
     start execution.
   - `FAILED` or a stopped-without-result outcome → treat as blocked: report
     the failure and stop.

This prompt ends at plan construction for the larger path; a small issue
may be solved directly and reported. Execution of a produced plan is driven
by /plan-drive —
pass it the resolved pane id (not the agent name) as its argument.
