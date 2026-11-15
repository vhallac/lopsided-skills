#!/usr/bin/env bash
# Regression tests for the worktree-management release guard (issue 53).
#
# Matrix:
#   1. no plan + no PR  -> removed      (the bug case: failed before the fix)
#   2. plan present     -> refused, worktree kept
#   3. open PR          -> refused, worktree kept
#   4. clean release    -> path gone from `worktree list`
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
# fake gh: reads the stub file set by tests, echoes open-PR listing
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

# Case 1: no plan, no PR -> removed
out=$("$script" release "$repo" "$stream" 2>&1) && st=0 || st=$?
if [ $st -eq 0 ] && [ ! -d "$wt" ]; then ok; else bad "case1: expected success+removal, got st=$st out=$out"; fi

# Case 2: plan present -> refused, worktree kept
git -C "$repo" worktree add -q "$scratch/repo-wt/$stream" "$stream" 2>/dev/null || git -C "$repo" worktree add -q "$scratch/repo-wt/$stream" -b "$stream" 2>/dev/null
mkdir -p "$wt/.todo" && touch "$wt/.todo/task_plan.md"
out=$("$script" release "$repo" "$stream" 2>&1) && st=0 || st=$?
if [ $st -ne 0 ] && [ -f "$wt/.todo/task_plan.md" ]; then ok; else bad "case2: expected refusal+keep, got st=$st out=$out"; fi
rm -rf "$wt/.todo"

# Case 3: open PR -> refused, worktree kept
echo "https://github.com/x/y/pull/1" >"$pr_stub"
out=$("$script" release "$repo" "$stream" fix/foo 2>&1) && st=0 || st=$?
if [ $st -ne 0 ] && [ -d "$wt" ]; then ok; else bad "case3: expected PR refusal, got st=$st out=$out"; fi

# Case 4: clean release -> path gone from worktree list
: >"$pr_stub"
out=$("$script" release "$repo" "$stream" fix/foo 2>&1) && st=0 || st=$?
if [ $st -eq 0 ] && ! git -C "$repo" worktree list --porcelain | grep -qF "$scratch/repo-wt/$stream"; then ok; else bad "case4: expected list-clean release, got st=$st out=$out"; fi

echo "pass=$pass fail=$fail"
[ $fail -eq 0 ]
