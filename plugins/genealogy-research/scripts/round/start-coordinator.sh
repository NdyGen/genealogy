#!/usr/bin/env bash
# Starts (or restarts) a coordinator: a Claude session in the folder of main, in its own Herdr tab
# "coordinator", agent "coordinator". The guard (`lineage guard --coordinator`) calls this when no session
# coordinates (the watcher's heartbeat has been silent for half an hour) or when the coordinator is at a
# usage limit. Starting unattended in auto mode is a decision of the project owner.
# Usage: lineage round start-coordinator <account>
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

ACCOUNT=${1:?usage: lineage round start-coordinator <account>}
project_init
MAIN=$(dirname "$COMMON")
cd "$MAIN"
account_table | awk -F'\t' '{print $1}' | grep -qx "$ACCOUNT" || { echo "unknown account: $ACCOUNT" >&2; exit 2; }
NAME=coordinator
[ "${HERDR_ENV:-}" = 1 ] || { echo "not in Herdr" >&2; exit 2; }

if [ -s "$COMMON/dr-coordinator.tab" ]; then
  herdr agent send-keys "$NAME" ctrl+c ctrl+c >/dev/null 2>&1 || true
  herdr tab close "$(cat "$COMMON/dr-coordinator.tab")" >/dev/null 2>&1 || true
  sleep 2
fi
tab_json=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$MAIN" --label "coordinator" --no-focus)
echo "$tab_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["tab"]["tab_id"])' > "$COMMON/dr-coordinator.tab"
PANE=$(echo "$tab_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])')
herdr pane rename "$PANE" "$NAME" >/dev/null
sleep 2
herdr pane run "$PANE" "$(account_env_snippet "$ACCOUNT")" >/dev/null
sleep 1
herdr agent start "$NAME" --kind claude --pane "$PANE" --timeout 60000 -- --model opus --permission-mode auto >/dev/null 2>&1 || true
if herdr agent read "$NAME" --source visible 2>/dev/null | grep -q "trust this folder"; then
  herdr agent send-keys "$NAME" down enter >/dev/null
fi
herdr agent wait "$NAME" --until idle --timeout 60000 >/dev/null 2>&1 || true
# The coordinate skill is user-invoked only, so it is loaded as a slash command with this text as its arguments.
PROMPT="/genealogy-research:coordinate You are the coordinator of the deep-research rounds in this repository (the folder of main), started by the guard because no other session was coordinating. Follow the rules of this skill; read the project's $RESEARCH/project.md and CLAUDE.md if it exists. First see what is open: git log --oneline -15, lineage queue show, the worktrees in .worktrees/ (<output>/DONE = ready for review), tail -30 on the guard log in the git common dir (dr-guard.log) and lineage requests. Then start 'lineage round watch' in the background and restart it after every notice. Review every finished round as the skill says under 'Reviewing and merging' (have a subagent with model sonnet do the review) and merge with 'lineage round merge'; keep as many rounds running as the skill allows (the maximum is in <git-common-dir>/dr-max-rounds, the allowed accounts in dr-accounts) with 'lineage round start', direct line first, and start a new one only when a place is free. The guard handles usage limits: do not switch accounts yourself. Never send a mail: drafts wait for the user's explicit approval. Decisions that belong to the user go in $RESEARCH/questions.md and are reported at the end of your turn."
herdr agent prompt "$NAME" "$PROMPT" --wait --timeout 30000 >/dev/null 2>&1 || true
echo "coordinator started on $ACCOUNT in tab $(cat "$COMMON/dr-coordinator.tab")"
