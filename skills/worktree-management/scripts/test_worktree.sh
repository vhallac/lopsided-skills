#!/usr/bin/env bash
# Regression tests for the worktree-management release guard (issue 53).
#
# Claim-mapped matrix (claim ids repo-scoped to feature file test_worktree):
#   test_worktree-SC-1  release with no open plan and no open PR removes the
#                       stream worktree (the bug case: failed before the fix)
#   test_worktree-EXT-1 an open .todo/task_plan.md refuses the release and
#                       keeps the worktree
#   test_worktree-EXT-2 an open PR on the release branch refuses the release
#                       and keeps the worktree
#   test_worktree-EXT-3 a gh failure while checking PR state refuses the
#                       release (fail closed) and keeps the worktree
#   test_worktree-EXT-4 omitting <branch> still runs the PR guard: the branch
#                       is derived from the worktree HEAD, so an open PR is
#                       refused
#   test_worktree-SC-2 a clean release leaves the path absent from
#                       `git worktree list`
#
# Scaffolds a throwaway git repo with a worktree under ../<repo>-wt/<stream>,
# mirroring the skill's layout. gh is stubbed via a fake bin dir.
set -uo pipefail
cd "$(dirname "$0")"
script=./worktree.sh
chmod +x "$script"

pass=0 fail=0
ok() { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $*" >&2; }

fake_gh_dir=$(mktemp -d)
cat >"$fake_gh_dir/gh" <<'EOF'
#!/usr/bin/env bash
# fake gh: echoes the stub file set by tests; exits 1 when GH_FAIL is set
[ "${GH_FAIL:-0}" = 1 ] && exit 1
cat "${GH_FAKE_OUT:-/dev/null}"
EOF
chmod +x "$fake_gh_dir/gh"
export PATH="$fake_gh_dir:$PATH"

scratch=$(mktemp -d /tmp/wt-test-XXXXXX)
trap 'rm -rf "$scratch"' EXIT
repo="$scratch/repo"
mkdir "$repo" && git -C "$repo" init -q && git -C "$repo" config user.email t@t && git -C "$repo" config user.name t
echo x >"$repo/f" && git -C "$repo" add f && git -C "$repo" commit -qm x
git -C "$repo" remote add origin "https://github.com/test-org/$$-repo.git"
stream=fix/foo
git -C "$repo" worktree add -q "$scratch/repo-wt/$stream" -b "$stream" 2>/dev/null
wt="$scratch/repo-wt/$stream"

pr_stub="$scratch/pr.txt"
: >"$pr_stub"
export GH_FAKE_OUT="$pr_stub"

# test_worktree-SC-1: no plan, no PR -> removed
out=$("$script" release "$repo" "$stream" 2>&1) && st=0 || st=$?
if [ $st -eq 0 ] && [ ! -d "$wt" ]; then ok; else bad "case1: expected success+removal, got st=$st out=$out"; fi

git -C "$repo" worktree add -q "$scratch/repo-wt/$stream" "$stream" 2>/dev/null || git -C "$repo" worktree add -q "$scratch/repo-wt/$stream" -b "$stream" 2>/dev/null

# test_worktree-EXT-1: plan present -> refused, worktree kept
mkdir -p "$wt/.todo" && touch "$wt/.todo/task_plan.md"
out=$("$script" release "$repo" "$stream" 2>&1) && st=0 || st=$?
if [ $st -ne 0 ] && [ -f "$wt/.todo/task_plan.md" ]; then ok; else bad "case2: expected refusal+keep, got st=$st out=$out"; fi
rm -rf "$wt/.todo"

# test_worktree-EXT-2: open PR (branch arg given) -> refused, worktree kept
echo "https://github.com/x/y/pull/1" >"$pr_stub"
out=$("$script" release "$repo" "$stream" fix/foo 2>&1) && st=0 || st=$?
if [ $st -ne 0 ] && [ -d "$wt" ]; then ok; else bad "case3: expected PR refusal, got st=$st out=$out"; fi

# test_worktree-EXT-3: gh failure -> fail closed, worktree kept
out=$(GH_FAIL=1 "$script" release "$repo" "$stream" fix/foo 2>&1) && st=0 || st=$?
if [ $st -ne 0 ] && [ -d "$wt" ]; then ok; else bad "case4: expected gh-failure refusal, got st=$st out=$out"; fi
unset GH_FAIL

# test_worktree-EXT-4: branch omitted, open PR on HEAD branch -> still refused
out=$("$script" release "$repo" "$stream" 2>&1) && st=0 || st=$?
if [ $st -ne 0 ] && [ -d "$wt" ]; then ok; else bad "case5: expected derived-branch PR refusal, got st=$st out=$out"; fi

# test_worktree-SC-2: clean release -> path gone from worktree list
: >"$pr_stub"
out=$("$script" release "$repo" "$stream" fix/foo 2>&1) && st=0 || st=$?
if [ $st -eq 0 ] && ! git -C "$repo" worktree list --porcelain | grep -qF "$scratch/repo-wt/$stream"; then ok; else bad "case6: expected list-clean release, got st=$st out=$out"; fi

echo "pass=$pass fail=$fail"
[ $fail -eq 0 ]
