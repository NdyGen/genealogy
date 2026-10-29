#!/usr/bin/env bash
# Starts the guard (`lineage guard`) in its own Herdr tab, independent of any Claude session: it resumes
# running rounds after a usage limit on an account with room, or waits until there is room again.
# Does nothing when it already runs (heartbeat in <git-common-dir>/dr-guard.alive younger than ten minutes).
# Log: <git-common-dir>/dr-guard.log.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

project_init
MAIN=$(dirname "$COMMON")
[ "${HERDR_ENV:-}" = 1 ] || { echo "not in Herdr" >&2; exit 2; }
ALIVE=$(state_read_path dr-guard.alive dr-bewaker.alive)
if [ $(( $(date +%s) - $(grep -Eo "^[0-9]+" "$ALIVE" 2>/dev/null || echo 0) )) -lt 600 ]; then
  echo "guard is already running (log: $COMMON/dr-guard.log)"
  exit 0
fi
tab_json=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$MAIN" --label "guard" --no-focus)
PANE=$(echo "$tab_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])')
herdr pane rename "$PANE" guard >/dev/null
sleep 1
# A fresh pane has only the login PATH, where the plugin's bin/ is not.
herdr pane run "$PANE" "cd '$MAIN' && '$PLUGIN_ROOT/bin/lineage' guard --coordinator" >/dev/null
echo "guard started in tab $(echo "$tab_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["tab"]["tab_id"])') (log: $COMMON/dr-guard.log)"
