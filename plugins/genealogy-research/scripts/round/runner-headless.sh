# Headless runner (source, do not run): leaders are background `claude -p` processes, helpers run in the
# foreground of the leader's Bash call. Pid and log of a leader: <worktree>/<output>/leader.{pid,log}.

_wt_of_name() { echo "$ROOT/.worktrees/dr-$(upper "${1#dr-}")"; }

_leader_alive() {
  local pidfile=$1
  [ -s "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

runner_start_leader() {
  local wt=$1 name=$2 label=$3 model=$4 account=$5 prompt=$6 out
  out=$(out_dir "$wt")
  mkdir -p "$out"
  (
    cd "$wt"
    eval "$(account_env_snippet "$account")"
    # Its own process group, so runner_stop can end it with its children.
    detach nohup claude -p "$prompt" --model "$model" --permission-mode auto \
      --output-format stream-json --verbose > "$out/leader.log" 2>&1 < /dev/null &
    echo $! > "$out/leader.pid"
  )
  sleep 2
  _leader_alive "$out/leader.pid" || { echo "WARNING: $name exited right away; see $out/leader.log" >&2; return 0; }
  RUNNER_WHERE=
  return 0
}

runner_start_helper() {
  local wt=$1 name=$2 agent=$3 prompt=$4 result=$5 max_min=${DR_HELPER_MAX_MIN:-${DR_HULP_MAX_MIN:-120}} log rc
  log=$(mktemp)
  # shellcheck disable=SC2064
  trap "rm -f '$log'" EXIT
  (cd "$wt" && with_timeout "$((max_min * 60))" claude -p --agent "$agent" --permission-mode auto "$prompt") > "$log" 2>&1 && rc=0 || rc=$?
  if [ "$rc" = 124 ]; then helper_fail "$result" "$name" "not done after $max_min minutes" "$(tail -n 60 "$log")"; return 1; fi
  if [ "$rc" != 0 ]; then helper_fail "$result" "$name" "exited with status $rc" "$(tail -n 60 "$log")"; return 1; fi
  [ -s "$result" ] || { helper_fail "$result" "$name" "stopped without a result" "$(tail -n 60 "$log")"; return 1; }
  return 0
}

runner_list() {
  local wt idl out
  for wt in "$ROOT"/.worktrees/dr-*; do
    [ -d "$wt" ] || continue
    idl=$(lower "${wt##*/dr-}")
    out=$(out_dir "$wt")
    [ -f "$out/leader.pid" ] || continue
    if _leader_alive "$out/leader.pid"; then
      printf 'dr-%s\tworking\n' "$idl"
    elif marker_file "$wt" DONE KLAAR >/dev/null; then
      printf 'dr-%s\tdone\n' "$idl"
    else
      printf 'dr-%s\tgone\n' "$idl"
    fi
  done
}

runner_screen() { tail -n 60 "$(out_dir "$(_wt_of_name "$1")")/leader.log" 2>/dev/null; }

runner_prompt() { echo "the headless runner cannot prompt a running leader" >&2; return 2; }

runner_stop() {
  local wt=$1 out pid
  out=$(out_dir "$wt")
  [ -s "$out/leader.pid" ] || return 0
  pid=$(cat "$out/leader.pid")
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  rm -f "$out/leader.pid"
}

runner_after_finish() { return 0; }

runner_start_coordinator() { echo "the headless runner cannot host a coordinator; use hc or herdr" >&2; return 2; }
runner_start_guard() { echo "the headless runner cannot host the guard; use hc or herdr" >&2; return 2; }
