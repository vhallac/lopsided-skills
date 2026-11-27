---
description: Kick off a plan agent via the terminal manager and have it construct a plan from the operator's task directive
argument-hint: "<agent-name> <task-directive...> [--model <provider>/<model>[:<thinking>]]"
---

The plan is always built from the project root: the cwd of the session
invoking this prompt is the project root and must be the agent pane's cwd.

`$1` is the agent name. The worker's mailbox identity is bound at spawn:
for `hc` it is the `--name <pane-name>` value (the agent name itself, which
must fit the manager's `--name` charset); for `herdr` it is the pane id.
Resolve that identity and the pane address once (step 2) and use the
identity as the `worker` for `agent_request` and when handing off to
/plan-drive. If `$1` does not fit the manager's `--name` charset, report
NEEDS_INPUT — never mangle the name.

Kick off and plan: agent $1, task: ${@:2}.

The task directive — everything after the agent name — is the agent's work
order, not necessarily an issue reference. It may name an issue (then that
issue is what the agent loads) or be a free-form instruction in its own
right ("fix the review findings of PR 95"); in that case the directive
itself is the work input. Pass it verbatim: directives carry the operator's
decisions and constraints — do not paraphrase, re-prioritize, or drop any
of it.

An optional `--model <provider>/<model>[:<thinking>]` flag selects the
worker's model (pi parses the spec natively; pass it through verbatim —
never split or rewrite it). Strip the flag and its value from the invocation
arguments before applying the expansion above, so the task directive stays
verbatim. Pass the model through the start/reuse op only: the model is
pinned at spawn, so on a fresh spawn it takes effect, and when an existing
agent is reused the flag is ignored — say so in the report to the operator.

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
| start/reuse worker | `hc run --bg --cwd <project-root> --name <pane-name> env AGENT_PANE=<pane-name> MAILBOX_DIR=<mailbox-store> pi [--model <spec>]` (start; reuse when `hc ls --json` already shows that name) | `herdr-plan-agent <name> [--model <spec>]` wrapper (starts or reuses the existing agent); the wrapper must be on PATH — the pi install does not put package `bin` entries there (see README Installation section); if not found, report NEEDS_INPUT saying so |
| address map (agent name → mailbox identity + pane address) | `hc ls --json` → the terminal whose name is `<pane-name>`; that name is the mailbox identity, its id (e.g. `t12`) is the pane address | `herdr agent get <name>` → its `pane_id` is both the mailbox identity and the pane address |
| deliver message | `hc send <pane-name> "<text>"` (non-blocking paste + enter; accepts a terminal address or a name) | `herdr agent prompt <name> -- "<text>"` (delivery only — never pass `--wait`, never use it as a wait) |
| read pane tail | `hc read <pane-name>` | `herdr agent read <name> --source recent --lines N` |

`<mailbox-store>` is the store the mailbox CLI itself resolves: `$MAILBOX_DIR`
when it is set, otherwise the CLI default (`~/.local/share/mailbox`). Pass the
same store the invoking session uses so the worker binds where requests are
dispatched.

Wait is not a manager operation: the only wait anywhere in this prompt is
`agent_wait` on a concrete `requestId`.

## Steps

1. **Start (or reuse) the worker** — spawn it idle via the start/reuse op;
   do NOT submit the kickoff prompt through the start operation. The op's
   manager-specific form and preconditions live in the resolution table
   above. No prompt argument: the worker runs in this session's cwd = the
   project root.

   Build the kickoff message inline: it must quote the operator's task
   directive verbatim as the agent's work order (if the directive names an
   issue, the agent loads that issue; otherwise the directive itself is the
   work input), run the `plan-work` skill, and follow its sizing: small →
   propose the change and stop for the operator's go (reply `NEEDS_INPUT`
   with the `## Small change` block), unless the directive already says
   "just do it" (then the go is given — solve directly and report). Larger →
   produce the review-gated plan written to disk under `.todo/` in the
   agent's cwd (`.todo` is gitignored — NEVER `git add`/`git commit` it).
   The plan header MUST carry the issue reference when the directive names
   one, and the directive text otherwise. On completion the agent reports,
   for the larger path, the plan file path, the issue number or directive,
   and the number of units in the plan (for the small path: the proposed
   `## Small change` block instead), and stops.

2. **Resolve the worker identity and pane address, then dispatch the kickoff
   as a correlated request and block on its outcome:**

   - Use the address-map op for agent `$1`. The mailbox identity — the value
     the extension bound the agent's session under — is the pane name for
     `hc` and the pane id for `herdr`; the pane address is the terminal
     address used by deliver/read. If the agent has no entry (not started),
     report the failure and stop.
   - `agent_request` with worker set to the resolved **mailbox identity** and
     the kickoff message → returns a `requestId`. If the request fails
     (worker unreachable), report the failure and stop.

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

   - `DONE` → report back to the operator: agent name, task (issue reference
     or directive), plan path, number of units (parse them from the report).
     A small task the directive already authorized is reported the same way,
     as `solved directly`.
   - `NEEDS_INPUT` → surface the agent's report verbatim and stop. This is
     the normal small-path outcome: the proposal is the deliverable, and the
     go to execute it must come from the operator. Do not attempt to answer
     on the operator's behalf, and do not start execution.
   - `BLOCKED` → surface the agent's questions verbatim and stop. Do not
     attempt to answer on the operator's behalf, and do not start execution.
   - `FAILED` or a stopped-without-result outcome → treat as blocked: report
     the failure and stop.

This prompt ends at plan construction for the larger path, and at the small
change proposal for the small path — both wait for the operator; only a
small task the directive already authorized is solved directly. Execution of
a produced plan is driven by /plan-drive —
pass it the resolved mailbox identity (not the agent name alone) as its
argument.
