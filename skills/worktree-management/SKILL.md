---
name: worktree-management
description: Git worktree veneer for parallel development streams — create, attach, list, release. Use when starting work that needs an isolated root (parallel agents/streams, "do this in a worktree"), when checking which streams exist, or when releasing a finished stream. Enforces one plan per root and one root per stream.
---

# Worktree Management

Thin veneer over `git worktree` for running N parallel development streams in
one repository. Each stream gets its own root directory, index, and branch,
sharing the object store. Git itself is the registry and the enforcer: it
refuses duplicate branch checkouts, and `git worktree list` is the source of
truth — no separate state file.

## Rules this skill enforces

1. **No changes on the default branch, ever.** Worktrees are created with a
   new branch (`-b`), never on the default branch, never detached.
2. **One root per stream.** Never two streams in one root — shared roots
   clobber each other's files, index, and commits.
3. **One plan per root.** A root with an open plan (`.todo/task_plan.md`
   present) is occupied; `release` refuses it.

## Commands

### create <stream>

Isolated root for new work. Run from inside the repository, from the default
branch:

```bash
git worktree add ../<repo>-wt/<stream> -b <type>/<stream-slug>
```

- Always from the default branch, always a new branch, never detached.
- Branch type prefix per repo convention (`feat/`, `fix/`, ...).

### attach <branch>

Worktree on an existing branch (e.g. a PR branch for a review-remediation
plan). Same shape, no `-b`:

```bash
git worktree add ../<repo>-wt/<stream> <branch>
```

- Git refuses if the branch is already checked out elsewhere — that is the
  one-root-per-stream rule being enforced for you.
- If `<stream>` should equal the branch slug, keep them identical.

### list

```bash
git worktree list
```

Plus, per worktree, the occupancy check:

```bash
test -f <worktree>/.todo/task_plan.md && echo "PLAN OPEN" || echo "free"
```

### release <stream>

Refuses if a plan is open (mirror of `plan.py archive`'s refusal semantics —
archive the plan first), and refuses while a PR is still open on the stream's
branch (post-merge cleanup only). The guarded `release` subcommand lives in
the tested helper script (same precedence as `review-change`'s
`scripts/worktree.sh`):

```bash
skills/worktree-management/scripts/worktree.sh release <repo-root> <stream> [<branch>]
```

- `<repo-root>` is the main checkout path; `<branch>` (optional) is the
  stream's branch to check for open PRs via `gh` — when omitted it is derived
  from the worktree's HEAD, so the PR guard always runs. A `gh` failure is
  treated as unknown PR state and refuses the release (fail closed).

## Coordination contract

Plan → workspace created (create/attach) → plan lives in the worktree
(`plan.py init <worktree-root>`) → units execute in the worktree → tail unit
pushes + PRs → user merges → `plan.py archive` (removes `.todo/`; the tarball
lands in the shared git dir, safe from worktree removal) → `release` the
worktree. The main checkout hosts no plans; it is the
review/merge surface.

Parallel streams are just: one worktree per stream, each with at most one
plan. Planner and executor per stream are isolated by root.
