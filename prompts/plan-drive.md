---
description: Drive one or more herdr plan agents through plan execution — request, wait, gate
argument-hint: "<agent-pane-id> [-- directives]"
---

Drive the herdr agent(s): $1 is the agent's **pane id** (or pane ids before
`--`) — the identity the mailbox tools address, resolved from the agent name
by /plan-kick. For `herdr` CLI commands, which take the agent name, resolve
the name once per session: `herdr agent list` and look up the entry whose
`pane_id` matches the pane id.

Anything after `--` in the arguments is an operator directive. Carry it as a
standing constraint for this drive session: quote it exactly when relaying to
agents, apply it in every gate decision, and never paraphrase or drop it. If
the directive conflicts with a plan unit, surface the conflict to the operator
instead of silently deviating.

You are the intermediary between the operator and one or more pi agents
running in herdr panes (each with the semblr extension). Each agent is
executing a plan from `.todo/` unit by unit.

Requires the agent-mailbox pi extension in this session (`agent_request`,
`agent_wait`, `agent_list`, `agent_rebind`, `agent_cancel` tools available).
If they are not, report NEEDS_INPUT saying so — do not degrade to sleep-based
or pane-state polling. There are NO sleep-based completion loops in this
prompt: every wait is correlated to a specific requestId.

## Step 0 — bind the issue (once per agent, before driving)

Resolve the agent's issue number from its plan file, never from the operator's
memory:

1. Find the plan file in the agent's cwd (`.todo/`) and grep its header for
   the issue reference (e.g. `issue #NN`, `Refs:`). The plan file is the
   source of truth — do NOT spend an agent round asking the agent for its
   binding.
2. Only if the plan cannot be located or its header names no issue, ask the
   agent once via a correlated request (`agent_request` to the worker pane id,
   then deliver the question to the pane via a single blocking
   `herdr agent prompt` carrying the question, the returned `requestId`, and
   the obligation to answer via `agent_reply(requestId, ...)`, then
   `agent_wait` on that `requestId`). If
   even then the plan and the agent disagree, or no issue is named, that is a
   `BLOCKED` gate condition — surface it and stop; do not guess a number.
3. Record `issue #NN`, the plan path, and the agent's PR (if one exists yet)
   as the agent's binding. Every subsequent instruction, review call, and
   publish-review report for that agent uses this issue number — the
   operator never has to repeat it.

If the binding is already known from a previous drive session for the same
agent, skip re-binding unless the agent reports a different plan. Your job is to move each agent
forward one unit at a time, and to apply the completion gate strictly.

## The drive loop (per agent, repeat)

1. **Dispatch the next unit as a correlated request**: `agent_request` with
   worker set to the pane id `$1` and message:
   "Execute unit U<n> of the plan for issue #NN in <plan path>, then report
   per the completion report format." (The unit names come from the plan's
   unit list, in order, skipping completed ones. Keep the message minimal.)
   - The tool returns a `requestId`. Record it against the unit in your
     ledger.
   - `agent_request` only registers and settles the request in the mailbox
     — it does NOT put the instruction in front of the agent. Deliver it
     yourself, in the same step, via a single blocking prompt to the pane:

     herdr agent prompt $1 -- "Request <requestId>: Execute unit U<n> of
     the plan for issue #NN in <plan path>, then report per the completion
     report format. You MUST answer this request via agent_reply(requestId,
     ...) with your status (DONE | NEEDS_INPUT | BLOCKED | FAILED) and
     report. Do not answer any other way."

     The delivered message MUST carry all three parts: (a) the unit
     instruction text, (b) the `requestId`, (c) the explicit obligation to
     respond with `agent_reply(requestId, ...)`.

     This `herdr agent prompt` is delivery only — a single blocking call.
     Never use `herdr agent prompt` as a wait/polling mechanism; blocking
     on the outcome is `agent_wait` on the `requestId` below.
   - If `agent_request` fails (worker unreachable, dispatch error), the unit
     fails for this round: record the failure against the unit and escalate
     to the operator. Do NOT fall back to repeated `herdr agent prompt`
     calls with sleep-and-recheck loops.
2. **Wait on the request**: `agent_wait` on the `requestId` with a generous
   `timeoutMs` (a unit takes minutes; use 900000). The wait resolves with the
   worker's reply: its `status` is the completion-report status (`DONE |
   NEEDS_INPUT | BLOCKED | FAILED`) and its `report` is the report text.
   - On timeout the request stays pending and nothing is consumed: re-arm
     `agent_wait` on the same `requestId`. Re-arming a correlated wait is not
     state polling; do not insert sleeps between re-arms. If a re-arm also
     times out with no progress across two consecutive waits, escalate.
   - Distinguish the two non-reply outcomes — they need opposite handling:
     - **Cancelled wait** (the wait itself was interrupted/cancelled):
       nothing was consumed and the request is still pending. Re-arm
       `agent_wait` on the same `requestId` — the unit is not blocked, the
       outcome just has not been picked up.
     - **Settled without a result** (the outcome was consumed and it
       carries no usable reply): that is a FAILED outcome — handle it in
       the step-3 FAILED gate, do not re-arm the wait.
   - The reply's `report` is the completion report; you do not need
     `herdr agent read` for gating. Use a single `herdr agent read
     <agent name> --source recent --lines 60` only as a diagnostic when the
     report
     is empty or unparsable — never as a polling loop.
3. **Gate on the status**:
   - `DONE` and no open issues in the report → mark that unit complete,
     continue to the next unit. Never auto-continue past a reported open
     issue.
   - `NEEDS_INPUT` or `BLOCKED` → surface the report's questions to the
     operator verbatim and stop driving this agent until the operator
     answers.
   - `FAILED` or any open issue → do NOT continue. Summarize the failure and
     the agent's diagnosis for the operator, and wait for a decision (fix,
     retry with instructions, or abort).
4. **Between units**, keep a terse ledger — one line per unit, nothing more:
   `U1 DONE (req r-abc1), U2 DONE (req r-abc2), U3 NEEDS_INPUT (req r-abc3),
   5 left`. Do not re-summarize the agent's reports into a narrative; the
   plan file is the source of truth. Review findings deferred to the PR
   review phase are recorded as one ledger line too (e.g. `deferred: R2.F1
   to review`).

## Interrupted batches and operator intervention

When resuming a drive session (operator cancel/pause/rebind, or a fresh
session taking over), do not assume which units are outstanding. Rebind
FIRST: the pane's session identity may have been replaced, and while this
session runs under a stale identity no pending reply addressed to it is
reachable — `agent_wait` would block forever on outcomes it can never
consume.

1. Call `agent_rebind` for this pane before anything else. If the rebind
   fails, stop and escalate: outstanding requests cannot be consumed until
   it succeeds. Do not skip to `agent_list`/`agent_wait` on a failed
   rebind.
2. `agent_list` shows every pending request with its state and whether a
   reply is waiting. Reconcile it against the plan's unit list and your
   ledger.
3. Re-arm `agent_wait` on any request that already has a reply waiting
   (consume it, gate on it). Requests still pending with no reply are
   re-waited, not re-dispatched — re-dispatching would run the unit twice.
4. Only units with no live request and no recorded outcome are dispatched
   fresh (via the dispatch + delivery steps of the drive loop).

## Mechanical drive via `herdr-drive` (preferred for simple plans)

For plans whose units need no operator judgment between gates, run the
mechanical loop script instead of relaying unit by unit yourself:

    herdr-drive --agent <agent name> --issue <NN> --plan <plan-path> U1 U2 ... U<n>

(pass the remaining unit ids in order). The script submits each unit, reads
only the report tail, gates on the status line, and prints a one-line ledger
per unit. Then:

- Exit 0 → all listed units are done and clean; report the ledger to the
  operator. You never read the individual reports.
- Nonzero exit → the script prints `ESCALATE <status>` plus the captured
  report tail. Apply the gate rules above (step 3) to that escalation: relay
  questions verbatim, stop, wait for the operator.

Use the manual loop (steps 1–4) when a unit needs you to make a judgment
call between gates; use the script when the plan is a straight sequence of
units. Note: `herdr-drive` waits via synchronous `herdr agent prompt --wait`
CLI calls, not correlated requests — it has no sleep loops, but until it is
migrated to request-correlated waits it does not produce per-unit
requestIds; prefer the manual loop when you need that correlation.

## Manual mode (operator drives)

When the operator is driving manually and asks you only to check state:
run `agent_list` (pending requests and reply states) and `herdr agent list`
(pane liveness), then report per-agent: unit in progress, last completion
status, open issues. Do not dispatch new requests unless explicitly asked.

## Orchestration mode

The same loop generalizes to multiple agents: dispatch to each agent as its
own correlated request (you may hold several requestIds at once), gate
per-agent and absolute — no dispatch to an agent whose last report has an
open issue. Escalate to the operator whenever any agent is stuck for more
than one gate check.

## Hard rules

- NEVER auto-continue past a reported open issue, NEEDS_INPUT, BLOCKED, or
  FAILED status. Those stop the loop for that agent.
- NO sleep-based completion loops: no busy-wait re-checking of pane state,
  no `sleep N; herdr agent read` cycles. Every wait is an `agent_wait` on a
  concrete `requestId`; the only repeats are re-arms of that same wait.
- Do not modify the plan's units or skip gates; the agents own their plans.
- When relaying the operator's answers back to an agent, dispatch them as a
  new correlated request quoting the answer exactly; do not paraphrase
  decisions.
