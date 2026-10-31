#!/usr/bin/env bash
# Starts the guard (`lineage guard`) in its own terminal (herdr: a tab; hc: a terminal), independent of any
# Claude session: it resumes running rounds after a usage limit on an account with room, or waits until there
# is room again.
# Does nothing when it already runs (heartbeat in <git-common-dir>/dr-guard.alive younger than ten minutes).
# Log: <git-common-dir>/dr-guard.log.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

project_init
MAIN=$(dirname "$COMMON")
load_runner
ALIVE=$(state_read_path dr-guard.alive dr-bewaker.alive)
if [ $(( $(date +%s) - $(grep -Eo "^[0-9]+" "$ALIVE" 2>/dev/null || echo 0) )) -lt 600 ]; then
  echo "guard is already running (log: $COMMON/dr-guard.log)"
  exit 0
fi
RUNNER_WHERE=
# A fresh terminal has only the login PATH, where the plugin's bin/ is not.
runner_start_guard "$MAIN" "$PLUGIN_ROOT/bin/lineage" guard --coordinator --runner "$RUNNER"
echo "guard started ($RUNNER runner${RUNNER_WHERE:+, $RUNNER_WHERE}; log: $COMMON/dr-guard.log)"
