---
description: Kick off a plan agent via the terminal manager and have it construct a plan for an issue
argument-hint: "<agent-name> <issue-ref> [-- directives]"
---

The plan is always built from the project root: the cwd of the session
invoking this prompt is the project root and must be the agent pane's cwd.

`$1` is the agent name. Correlated requests address the agent's **pane id**,
not the agent name: before dispatching, resolve the pane id once (step 2)
and use it as the `worker` identity for `agent_request` and when handing off
to /plan-drive.

Kick off and plan: agent $1, issue $2. Anything after `--` is an operator
directive: pass it to the agent verbatim as additional context alongside the
issue. Directives carry the operator's decisions and constraints — do not
paraphrase or re-prioritize them.

Requires the agent-mailbox pi extension in this session (`agent_request`,
`agent_wait` tools available). If they are not, report NEEDS_INPUT saying so —
do not degrade to sleep-based or pane-state polling.

## Manager resolution (once per session, before any manager command)

Resolve the terminal manager from the environment — do NOT probe for
availability and do NOT re-resolve later in the prompt:

- `HC_TERMINAL_ID` is set → the manager is `hc`.
- else `HERDR_WORKSPACE_ID` is set → the manager is `herdr`.
- neither is set → report NEEDS_INPUT naming the missing variable and stop.

Bind the neutral operations to the resolved manager's commands. Outside this
block the prompt refers only to the neutral op names — never to concrete
manager commands:

| Neutral op | hc binding | herdr binding |
|---|---|---|
| start/reuse worker | `hc run pi ... --bg` (start; reuse when `hc ls --json` already shows the labeled terminal) | `herdr-plan-agent <name>` wrapper (starts or reuses the existing agent) |
| address map (agent name → pane address) | `hc ls --json` → the terminal labeled/paired with the agent name; its id is the pane address | `herdr agent get <name>` → parse `pane_id` from its JSON |
| deliver message | `hc send <pane-address> "<text>"` (non-blocking paste + enter) | `herdr agent prompt <name> -- "<text>"` (delivery only — never pass `--wait`, never use it as a wait) |
| read pane tail | `hc read <pane-address>` | `herdr agent read <name> --source recent --lines N` |

Wait is not a manager operation: the only wait anywhere in this prompt is
`agent_wait` on a concrete `requestId`.

## Steps

1. **Start (or reuse) the worker** — spawn it idle; do NOT submit the kickoff
   prompt through the start operation. For `hc`, the `herdr-plan-agent`
   wrapper precondition does not apply; for `herdr`, the wrapper must be on
   PATH (the pi install does not put package `bin` entries there — see the
   README Installation section); if it is not found, report NEEDS_INPUT
   saying so. No `--cwd` override and no prompt argument: the worker runs in
   this session's cwd = the project root.

   Build the kickoff message inline: it must instruct the agent to load issue
   $2 (plus any extra context), run the `plan-work` skill, and follow its
   sizing: small → solve directly and report; larger → produce the
   review-gated plan written to disk under `.todo/` in the agent's cwd
   (`.todo` is gitignored — NEVER `git add`/`git commit` it). The plan header
   MUST carry the issue reference. On completion the agent reports the plan
   file path, the issue number, and the number of units in the plan (for the
   small path: a `solved directly` report instead), and stops.

2. **Resolve the pane address, then dispatch the kickoff as a correlated
   request and block on its outcome:**

   - Resolve the pane address for agent `$1` via the address-map op. This
     address is what the extension bound the agent's session identity under;
     the agent name alone is NOT a valid `agent_request` worker. If the
     agent has no pane address (not started), report the failure and stop.
   - `agent_request` with worker set to the resolved **pane address** and the
     kickoff message → returns a `requestId`. If the request fails (worker
     unreachable), report the failure and stop.

     `agent_request` only registers and settles the request in the mailbox
     — it does NOT put the message in front of the agent. Delivery is your
     job, in the same step, via a single non-blocking **deliver** op:

     Request <requestId>: <full kickoff message text from step 1>. You MUST
     answer this request via agent_reply(requestId, ...) with your status
     (DONE | NEEDS_INPUT | BLOCKED | FAILED) and report. Do not answer any
     other way — an un-replied request never settles.

     The delivered message MUST carry all three parts: (a) the kickoff
     instruction text, (b) the `requestId`, (c) the explicit obligation to
     respond with `agent_reply(requestId, ...)`.

     The deliver op is delivery only. Never use it as a wait/polling
     mechanism; blocking on the outcome is `agent_wait` on the `requestId`
     below.
   - `agent_wait` on that `requestId` with a generous `timeoutMs` (plan
     construction takes minutes; use 900000). The wait resolves with the
     agent's reply (status + report) or times out — the reply only exists
     because the agent answered via `agent_reply`, which is why the
     delivery step above is mandatory.
   - On timeout the request stays pending: re-arm `agent_wait` on the same
     `requestId` once. If a second wait also times out, diagnose with one
     read-tail op (60 lines — a single read, not a polling loop) and
     escalate to the operator.

3. **Gate on the reply's status:**

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
pass it the resolved pane address (not the agent name) as its argument.
