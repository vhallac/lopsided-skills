#!/usr/bin/env bash
# Release guard for worktree-management streams.
#
# Only `release` needs guarding (plan-open and PR-open refusals); create,
# attach, and list are plain git commands documented in the skill prose.
#
#   worktree.sh release <repo> <stream> [<branch>]   # guarded removal
#
# <repo> is the main checkout (path or URL resolvable by git -C). Guards run
# in fail-closed order: an open plan dies first, then an open PR, then the
# removal proceeds without --force (git's own unclean-refusal is the second
# layer).
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

cmd=${1:-}; shift || true
case "$cmd" in
release)
	[ $# -ge 2 ] && [ $# -le 3 ] || die "usage: release <repo> <stream> [<branch>]"
	repo=$1 stream=$2 branch=${3:-}
	wt=$(cd "$repo" && pwd -P)/../$(basename "$(cd "$repo" && pwd -P)")-wt/$stream
	[ -d "$wt" ] || die "no such worktree: $wt"
	if [ -f "$wt/.todo/task_plan.md" ]; then
		die "PLAN OPEN - archive first"
	fi
	gh_repo=$(git -C "$wt" remote get-url origin | sed -E -e 's#.*github.com[:/]##' -e 's/\.git$//')
	if [ -n "$branch" ] && gh pr list --repo "$gh_repo" --head "$branch" --state open | grep -q .; then
		die "PR STILL OPEN - merge first"
	fi
	git -C "$repo" worktree remove "$wt"
	git -C "$repo" worktree prune
	echo "released $stream"
	;;
*)
	sed -n '2,9p' "$0"
	exit 2
	;;
esac
