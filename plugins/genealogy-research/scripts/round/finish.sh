#!/usr/bin/env bash
# Last step of the round leader: checks that everything is committed, marks the round as finished
# (<output>/DONE, which the coordinator watches for) and shortly after closes the round's tab.
# Usage (from the worktree): lineage round finish
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

project_init
WT=$ROOT
BRANCH=$(git -C "$WT" rev-parse --abbrev-ref HEAD)
case "$BRANCH" in dr/*) ;; *) echo "not in a deep-research worktree (branch $BRANCH)" >&2; exit 1;; esac
ID=${BRANCH#dr/}
IDL=$(lower "$ID")
load_runner
UPDATE_ROUND=0
marker_file "$WT" update bijwerk >/dev/null && UPDATE_ROUND=1

[ -z "$(git -C "$WT" status --porcelain)" ] || { echo "uncommitted changes; commit first" >&2; git -C "$WT" status --short >&2; exit 1; }
for f in "$PERSON_REPORTS/$ID.md" "$LIFE_STORIES/$ID.md"; do
  git -C "$WT" cat-file -e "HEAD:$f" 2>/dev/null || { echo "$f is missing in the last commit" >&2; exit 1; }
done
# Seven rounds in a row once finished without a log entry; the coordinator had to write them.
if [ "$UPDATE_ROUND" = 0 ]; then
  git -C "$WT" diff "$MAIN_BRANCH...HEAD" -- "$LOG" | grep -Eq "^\+## .*(^|[^0-9A-Za-z])$ID([^0-9]|$)" || {
    echo "no new heading with $ID in $LOG; write and commit your log entry first (deep-research skill, step 7)" >&2; exit 1; }
fi

if [ "$UPDATE_ROUND" = 0 ]; then
  # What needs no judgement (scope, vanished values, coordinates, Transkribus count, account, queue) is checked
  # here, so the coordinator's review can spend its time on readings and certainty.
  REVIEW=$(cd "$WT" && lineage review "$ID") || {
    echo "$REVIEW" >&2; echo "fix the ERROR lines, commit, and run 'lineage round finish' again" >&2; exit 1; }
  echo "$REVIEW"
fi

mkdir -p "$(out_dir "$WT")"
date -Iseconds > "$(out_dir "$WT")/DONE"

runner_after_finish "$WT" "dr-$IDL"
echo "$ID finished"
