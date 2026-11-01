#!/usr/bin/env bash
# Starts the guard (`lineage guard`) in its own terminal (herdr: a tab; hc: a terminal), independent of any
# Claude session: it resumes running rounds after a usage limit on an account with room, or waits until there
# is room again.
# Does nothing when it already runs (heartbeat in <git-common-dir>/dr-guard.alive younger than ten minutes),
# unless the runner can tell its terminal is gone (runner_guard_alive).
#
# --cron: instead of a looping terminal, a crontab line runs one pass (`lineage guard --once`) every two
# minutes, so nothing has to stay open; a running guard terminal is closed. --no-cron removes the line.
# Needs a runner that defines runner_cron_env (hc). While the line exists, a plain start-guard does nothing.
# Log: <git-common-dir>/dr-guard.log.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

mode=terminal
case "${1:-}" in
  --cron) mode=cron;;
  --no-cron) mode=no-cron;;
  "") ;;
  *) die "usage: lineage round start-guard [--cron | --no-cron]";;
esac

project_init
MAIN=$(dirname "$COMMON")
load_runner
TAG="# lineage-guard $COMMON"

crontab_without_guard() { crontab -l 2>/dev/null | grep -vF "$TAG" || true; }

if [ "$mode" = no-cron ]; then
  crontab_without_guard | crontab -
  echo "guard removed from crontab; start it in a terminal with: lineage round start-guard"
  exit 0
fi

if [ "$mode" = cron ]; then
  declare -F runner_cron_env >/dev/null || die "the $RUNNER runner cannot run the guard from cron (hc can)"
  command -v crontab >/dev/null || die "crontab is not installed"
  command -v flock >/dev/null || die "flock is not installed"
  # cron starts with a bare PATH; the guard needs hc, uv, claude and git, and passes PATH on to the rounds.
  path_dirs=$(for c in hc uv claude git python3; do d=$(command -v "$c") && dirname "$d"; done | awk '!seen[$0]++' | paste -sd:)
  envs="PATH=$path_dirs:/usr/bin:/bin"
  while IFS= read -r l; do envs+=" $l"; done < <(runner_cron_env)
  # flock: a pass that resumes a round can outlast two minutes.
  line="*/2 * * * * cd '$MAIN' && $envs flock -n '$COMMON/dr-guard.lock' '$PLUGIN_ROOT/bin/lineage' guard --once --coordinator >/dev/null 2>>'$COMMON/dr-guard.log' $TAG"
  { crontab_without_guard; echo "$line"; } | crontab -
  if declare -F runner_guard_alive >/dev/null && runner_guard_alive; then
    runner_stop_guard
    echo "guard terminal closed"
  fi
  echo "guard runs from cron every two minutes (log: $COMMON/dr-guard.log; stop: lineage round start-guard --no-cron)"
  exit 0
fi

if crontab -l 2>/dev/null | grep -qF "$TAG"; then
  echo "guard runs from cron (log: $COMMON/dr-guard.log)"
  exit 0
fi
ALIVE=$(state_read_path dr-guard.alive dr-bewaker.alive)
if [ $(( $(date +%s) - $(grep -Eo "^[0-9]+" "$ALIVE" 2>/dev/null || echo 0) )) -lt 600 ]; then
  if declare -F runner_guard_alive >/dev/null && ! runner_guard_alive; then
    echo "the guard's heartbeat is recent but its terminal is gone; starting a new one"
  else
    echo "guard is already running (log: $COMMON/dr-guard.log)"
    exit 0
  fi
fi
RUNNER_WHERE=
# A fresh terminal has only the login PATH, where the plugin's bin/ is not.
runner_start_guard "$MAIN" "$PLUGIN_ROOT/bin/lineage" guard --coordinator --runner "$RUNNER"
echo "guard started ($RUNNER runner${RUNNER_WHERE:+, $RUNNER_WHERE}; log: $COMMON/dr-guard.log)"
