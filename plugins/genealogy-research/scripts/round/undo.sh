#!/usr/bin/env bash
# Undoes the start of a research round that has done nothing yet, so its place can go to another round:
# stops the leader and closes its tab, removes the worktree and branch, and reverts the queue commit of
# `lineage round start`. Refuses when the branch has commits, the worktree has changes or <output>/DONE exists.
# Usage: lineage round undo <ID>
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

ID=${1:?usage: lineage round undo <ID>}
ID=$(upper "${ID//@/}")
IDL=$(lower "$ID")
project_init
cd "$ROOT"
load_runner
WT="$ROOT/.worktrees/dr-$ID"
BRANCH="dr/$ID"

[ -d "$WT" ] || { echo "no worktree $WT" >&2; exit 1; }
marker_file "$WT" DONE KLAAR >/dev/null && { echo "$ID is already finished; merge it instead of undoing" >&2; exit 1; }
[ -z "$(git rev-list "$MAIN_BRANCH..$BRANCH")" ] || { echo "$BRANCH already has commits; not undoing" >&2; exit 1; }
[ -z "$(git -C "$WT" status --porcelain)" ] || { echo "$WT has uncommitted changes; not undoing" >&2; exit 1; }
start=$(git log --format=%H -1 --extended-regexp --grep="^(Queue: deep research $ID started|Wachtrij: deep research $ID gestart)" -- "$QUEUE")
[ -n "$start" ] || { echo "no start commit found for $ID" >&2; exit 1; }

runner_stop "$WT" "dr-$IDL"
git worktree remove --force "$WT"
git branch -D "$BRANCH" >/dev/null
# A revert restores exactly the state before the start: open for a first round, done with the old ID block for a follow-up.
git revert --no-edit "$start" >/dev/null || { git revert --abort; echo "reverting $start conflicts; restore the queue by hand" >&2; exit 1; }
echo "$ID undone: $(grep -P "^$ID\t" "$QUEUE" | cut -f2)"
