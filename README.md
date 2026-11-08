# lopsided-skills

A set of agent skills that are highly opinionated, with a dash of NIH thrown in
for fun and profit. They are written in the open
[Agent Skills](https://skills.sh) format (`SKILL.md` with frontmatter), so any
coding agent that reads that format — pi, OpenCode, Claude Code, Codex, Cursor
and friends — can consume them as-is.

All skills here are **GPL-3.0**. See [LICENSE](LICENSE).

## The skills

| Skill | What it does |
|---|---|
| [`plan-work`](skills/plan-work/) | Prepares a controlled code change with strict scope before any implementation — a feature from a groomed story and spec, a bug fix from a bug report, or remediation of review findings. Estimates size first: small changes are solved directly, everything else becomes a right-sized, review-gated plan committed to `.todo`. |
| [`large-task-slicing`](skills/large-task-slicing/) | Breaks large or long-horizon tasks into externally tracked, bite-sized work units with verification gates. One unit at a time, state kept outside the agent's context, so work survives round boundaries and context loss. Includes a `plan.py` state helper. |
| [`commit-gate-wiring`](skills/commit-gate-wiring/) | Installs declared verification gates into a project that has automated tests — a unit gate, a pre-commit "no new red vs base" gate, promoted invariant/golden-diff/canary checks, and an optional diff-coverage floor. Writes a gates manifest consumed by `plan-work`, `large-task-slicing`, and `review-change`. Refuses when the project has no automated tests yet. |
| [`zettelkasten-notetaking`](skills/zettelkasten-notetaking/) | Maintains a zettelkasten-style running-notes store for a project: two files, small greppable cards, append-and-place only, with typed link discovery, structural validation, and a `store.py` helper for validation and tooling. Activated by a `.notes/zettel-index.md` signature file. |
| [`review-change`](skills/review-change/) | Read-only review of a merge/pull request, a work item, or both, against code, evidence, contracts and design decisions. Tries to falsify the work's claims and grades findings by a fixed severity and verdict scheme; writes a report file. In the first review, every new claim must map to a test or scenario — an unmapped claim blocks the verdict until a test is added or the operator grants a one-time waiver (later reviews flag changes under `coverage: review-only` claims). |
| [`use-case-writing`](skills/use-case-writing/) | Alistair Cockburn use-case format — structure, tree model, extension numbering, result binding, and natural language patterns. |
| [`story-writing`](skills/story-writing/) | Project-specific enrichment of use-case-writing for implementation stories and design documents. Covers delegation syntax, variable styling, and JIRA/Confluence formatting. |
| [`story-grooming`](skills/story-grooming/) | Grooms issues (epics/stories/tasks) into Cockburn use cases with a fixed architect/product-owner/reviewer split, using the issues themselves as the only communication medium. Supports a continuing groom → review loop across sessions. |
| [`behavioral-test-writing`](skills/behavioral-test-writing/) | Derives behavioral test specifications from groomed use cases — extracts requirement-level claims, grades them, rewrites as falsifiable scenarios, and emits Gherkin feature files with a claim→scenario traceability report and clarification pushback. Ungroomed inputs route back to story-grooming. |
| [`instruction-reliability`](skills/instruction-reliability/) | Techniques for writing effective AI instructions — from scratch or improving existing ones: de-escalating emphasis, fixing skipped or over-applied rules, and making instruction sets consistent. |
| [`worktree-management`](skills/worktree-management/) | Git worktree veneer for parallel development streams — create, attach, list, release. Enforces one plan per root and one root per stream. |
| [`publish-review`](skills/publish-review/) | Publishes a review produced by `review-change` to its channel — PR/MR comment, forge issue comment, or work-item notes — with the operator's decision (fix / accept / defer, file / decline) on every finding. Never reviews code itself. |

`plan-work` and `large-task-slicing` are designed to be used together: the
former decides *what* the controlled change is, the latter drives its execution
unit by unit. `review-change` and `publish-review` are likewise a pair: the
first writes the report, the second posts it. `worktree-management` gives each
parallel stream an isolated root, one plan per root.

## The mailbox CLI

`mailbox` (issue [#41](https://github.com/vhallac/lopsided-skills/issues/41))
is a CLI in this repo that persists and correlates request-reply pairs between
agents on the **same host, same OS user** — e.g. an orchestrator and its worker
sessions. Store location: `$MAILBOX_DIR` or `~/.local/share/mailbox` (one JSON
file per request, atomic writes).

Identity model: a request binds a **requester** identity (who gets the reply)
and a **worker** identity (who may answer it). Identities are opaque strings
chosen by the clients.

```sh
mailbox register --id r1 --requester q1 --worker w1 --instruction "research X"
                 # creates the reply expectation BEFORE exposure;
                 # re-registering a live expectation is rejected;
                 # re-registering a CANCELLED id supersedes it — the old
                 # record is archived as <id>.cancelled.<ts>.json (its
                 # rejection history stays inspectable) and a fresh
                 # expectation is created
mailbox dispatch --id r1              # mark it dispatched to the worker
mailbox reply --id r1 --worker w1 --status DONE --report "..."
mailbox consume --id r1 --requester q1  # exactly-once delivery of the reply
mailbox list [--pending]              # discover requests (pending = no outcome)
mailbox show --id r1                  # full record, JSON
mailbox pause --id r1                 # hold delivery (settable by any client)
mailbox resume --id r1
mailbox rebind --id r1 --requester q2 # explicit requester rebind
mailbox cancel --id r1                # stop the expectation; no delivery
```

Status vocabulary for replies: `DONE`, `NEEDS_INPUT`, `BLOCKED`, `FAILED`.

Delivery semantics:

- **Exactly-once** — the first successful `consume` marks the reply delivered;
  later consume attempts and duplicate replies are no-ops.
- **Acknowledge before mark** — `consume` writes the reply to the requester
  before the record is marked delivered. A crash between the two means the
  next `consume` re-delivers: the reply can repeat after a crash, but it is
  never lost (at-least-once on the crash window, exactly-once otherwise).
- **Pull-only** — there is no push notification. An undelivered reply is
  re-attempted by the client's next `consume`; the service persists it until
  then and nothing is lost, but re-attempt scheduling is the client's (#42's
  extension's) responsibility.
- **Unreachable requester** — if the requester has not consumed yet, the reply
  stays persisted and is delivered on a later `consume`; nothing is lost.
- **Paused** — while paused, delivery is held as inspectable state, not lost.
- **Identity change** — a `consume` from an identity other than the registered
  requester is refused until an explicit `rebind`.
- **Worker guard** — replies from an identity other than the dispatched worker
  are rejected and kept inspectable on the record.

Exit codes: `0` success, `2` usage error, `3` rejected (semantic refusal),
`4` not found.

pi extension integration (the mailbox as a pi extension tool) is issue #42 and
intentionally out of scope here.

## The agent-mailbox pi extension

The [agent-mailbox](pi-ext/agent-mailbox/) extension (issue
[#42](https://github.com/vhallac/lopsided-skills/issues/42)) exposes the
mailbox service as pi tools so an agent can delegate work to another pane and
get the reply back as a follow-up round — no polling of the CLI by hand, no
LLM rounds burned on waiting.

Installation is covered by the `pi` manifest in `package.json` (`extensions`:
`./pi-ext/agent-mailbox`); `pi install git:github.com/vhallac/lopsided-skills`
installs it like the skills. The mailbox CLI (same repo, `bin: mailbox`) is
its backing store — the extension shells out to it; see the section above for
store location and semantics.

Pane identity: the extension binds the pane name — read from the
`AGENT_PANE` environment variable, falling back to `HERDR_PANE_ID` (as set
by pane managers such as herdr, which does not set `AGENT_PANE`) — to a
stable session identity at session start. A pane that restarts gets a new session
identity and never receives its predecessor's replies until an explicit
`agent_rebind` binds the pending requests to the replacement session.

Tools:

| Tool | What it does |
|---|---|
| `agent_request` | Register + dispatch a request to a worker pane; returns a `requestId` immediately with a reply obligation. Unknown or unbound worker panes are rejected before any store mutation. |
| `agent_wait` | Block until the reply for a `requestId` is available (bounded poll loop in the extension — no LLM rounds consumed), or return "no outcome yet" on timeout without consuming the reply. |
| `agent_reply` | Worker side: submit a `status` (`DONE`, `NEEDS_INPUT`, `BLOCKED`, `FAILED`) and `report` for a dispatched `requestId`. Replies from an identity other than the dispatched worker are rejected. |
| `agent_rebind` | After a pane restart, bind the pane's pending requests from the old session identity to the replacement session. |

Delivery: when a reply settles while the requester is idle or between tool
rounds, the extension starts exactly one follow-up round attributed to the
worker as a custom (agent-attributed) message — never mid-run steering.
Delivery is exactly-once, backed by the mailbox `consume` semantics. If a
worker session ends without replying, the extension settles its dispatched
requests explicitly as FAILED ("stopped without a result") — never DONE —
leaving the request inspectable.

Recovery controls (operator- and agent-facing):

| Tool | What it does |
|---|---|
| `agent_list` | Inspect pending requests and undelivered replies. |
| `agent_pause` | Hold automatic delivery for a request; replies become inspectable state, not lost. |
| `agent_resume` | Release held delivery; the reply goes out on the next wait or probe. |
| `agent_cancel` | Cancel a blocked `agent_wait` — the wait returns without a result, the request stays pending and can be waited on later. |

## Installation

### Any Agent-Skills-compatible agent (skills.sh)

```sh
npx skills add vhallac/lopsided-skills
npx skills update        # re-sync installed skills later
```

This detects the agents on your machine and installs the skills into the right
locations.

### pi

```sh
pi install git:github.com/vhallac/lopsided-skills
pi update --extensions   # update installed packages later
```

pi installs the package `bin` entries on PATH: `mailbox` (the mailbox CLI)
plus `herdr-plan-agent` and `herdr-drive` — the herdr driver wrappers used
by the `plan-kick`/`plan-drive` prompts.

The repo carries a `package.json` with the `pi-package` keyword and a `pi`
manifest pointing at `./skills` and the `agent-mailbox` extension, so the pi
gallery can also index it.

### Claude Code + OpenCode (local symlink)

Both agents scan `~/.claude/skills/*/SKILL.md`:

```sh
git clone https://github.com/vhallac/lopsided-skills
ln -s "$PWD/lopsided-skills/skills" ~/.claude/skills
```

One symlink feeds both agents; the repo stays the single source of truth.

## Status

Early days: these skills are working drafts in daily use. More will follow in
a proper project structure. Expect churn.

## License

GPL-3.0 — see [LICENSE](LICENSE).
