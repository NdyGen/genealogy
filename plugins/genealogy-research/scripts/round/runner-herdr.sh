# Herdr runner (source, do not run). A round has its own tab labelled with the person's name; the leader is
# the pane/agent dr-<id>, helpers are panes <id>-<role>-<nr> next to it. The tab id is kept in
# <worktree>/<output>/runner-tab (old name: herdr-tab).

_tab_of() {
  local wt=$1 f tab
  f=$(marker_file "$wt" runner-tab herdr-tab) || return 0
  [ -s "$f" ] || return 0
  tab=$(cat "$f")
  herdr tab get "$tab" >/dev/null 2>&1 && echo "$tab"
  return 0
}

_helper_panes_of() {
  local idl=$1
  herdr pane list --workspace "$HERDR_WORKSPACE_ID" | python3 -c "
import json, sys
for p in json.load(sys.stdin)['result']['panes']:
    if (p.get('label') or '').startswith('$idl-'):
        print(p['pane_id'])"
}

_agent_status() {
  herdr agent list | python3 -c "
import json, sys
print(next((a['agent_status'] for a in json.load(sys.stdin)['result']['agents'] if a.get('name') == '$1'), 'gone'))"
}

# Trust prompt on the first start in a new folder.
_accept_trust() {
  if herdr agent read "$1" --source visible 2>/dev/null | grep -q "trust this folder"; then
    herdr agent send-keys "$1" down enter >/dev/null
  fi
}

runner_start_leader() {
  local wt=$1 name=$2 label=$3 model=$4 account=$5 prompt=$6 tab_json pane attempt started out
  out=$(out_dir "$wt")
  tab_json=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$wt" --label "$label" --no-focus)
  mkdir -p "$out"
  echo "$tab_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["tab"]["tab_id"])' > "$out/runner-tab"
  pane=$(echo "$tab_json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])')
  herdr pane rename "$pane" "$name" >/dev/null
  sleep 2
  herdr pane run "$pane" "$(account_env_snippet "$account")" >/dev/null
  sleep 1
  herdr agent start "$name" --kind claude --pane "$pane" --timeout 60000 -- --model "$model" --permission-mode auto >/dev/null 2>&1 || true
  _accept_trust "$name"
  herdr agent wait "$name" --until idle --timeout 60000 >/dev/null 2>&1 || true
  # Under heavy load the first prompt is sometimes lost; resend until the agent has picked it up.
  for attempt in 1 2 3; do
    herdr agent prompt "$name" "$prompt" --wait --timeout 30000 >/dev/null 2>&1 || true
    sleep 10
    started=$(herdr agent list | python3 -c "
import json, sys
a = next((a for a in json.load(sys.stdin)['result']['agents'] if a.get('name') == '$name'), {})
print('yes' if a.get('agent_status') == 'working' or (a.get('tokens') or {}).get('ctx', '0%') != '0%' else 'no')")
    [ "$started" = yes ] && break
  done
  [ "$started" = yes ] || echo "WARNING: $name did not pick up the brief after three attempts" >&2
  RUNNER_TAB=$(cat "$out/runner-tab")
  return 0
}

# Blocks until the helper is done. Memory caps both the total number of agents and the helpers per round.
runner_start_helper() {
  local wt=$1 name=$2 agent=$3 prompt=$4 result=$5
  local idl max_total max_per max_min lock total own last attempt started deadline refused st screen
  idl=${name%%-*}
  max_total=${DR_MAX_AGENTS:-24}
  max_per=${DR_MAX_HELPERS:-${DR_MAX_HULP:-3}}
  max_min=${DR_HELPER_MAX_MIN:-${DR_HULP_MAX_MIN:-120}}
  HELPER_PANE=

  _helper_panes_here() {
    herdr pane list --workspace "$HERDR_WORKSPACE_ID" | python3 -c "
import json, sys
for p in json.load(sys.stdin)['result']['panes']:
    if p['tab_id'] == '$HERDR_TAB_ID' and (p.get('label') or '').startswith('$idl-'):
        print(p['pane_id'])"
  }
  _fail() {
    screen=
    [ -z "$HELPER_PANE" ] || screen=$(herdr pane read "$HELPER_PANE" --source recent-unwrapped --lines 60 2>/dev/null || true)
    helper_fail "$result" "$name" "$1" "$screen"
    [ -z "$HELPER_PANE" ] || herdr pane close "$HELPER_PANE" >/dev/null 2>&1 || true
    return 1
  }

  # The lock keeps parallel starts honest.
  lock="$COMMON/dr-helper.lock"
  while :; do
    lock_take "$lock"
    total=$(herdr agent list | python3 -c "import json,sys;print(len(json.load(sys.stdin)['result']['agents']))")
    own=$(_helper_panes_here | wc -l)
    [ "$total" -lt "$max_total" ] && [ "$own" -lt "$max_per" ] && break
    lock_release "$lock"
    sleep 30
  done

  last=$(_helper_panes_here | tail -1)
  if [ -z "$last" ]; then
    HELPER_PANE=$(herdr pane split "$HERDR_PANE_ID" --direction right --cwd "$wt" --no-focus \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
  else
    HELPER_PANE=$(herdr pane split "$last" --direction down --cwd "$wt" --no-focus \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
  fi
  herdr pane rename "$HELPER_PANE" "$name" >/dev/null
  # An interrupted script (the leader stopping its background task) must not leave an idle pane behind.
  trap '[ -n "$HELPER_PANE" ] && herdr pane close "$HELPER_PANE" >/dev/null 2>&1' EXIT
  trap 'exit 143' TERM INT HUP
  sleep 2
  # Same account as the leader; the model comes from the agent definition, so ANTHROPIC_MODEL must not override it.
  if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
    herdr pane run "$HELPER_PANE" "export CLAUDE_CONFIG_DIR='$CLAUDE_CONFIG_DIR'; unset ANTHROPIC_MODEL" >/dev/null
  else
    herdr pane run "$HELPER_PANE" "unset CLAUDE_CONFIG_DIR ANTHROPIC_MODEL" >/dev/null
  fi
  sleep 1
  herdr agent start "$name" --kind claude --pane "$HELPER_PANE" --timeout 60000 -- --agent "$agent" --permission-mode auto >/dev/null 2>&1 || true
  _accept_trust "$name"
  herdr agent wait "$name" --until idle --timeout 60000 >/dev/null 2>&1 || true
  lock_release "$lock"

  started=no
  for attempt in 1 2 3; do
    herdr agent prompt "$name" "$prompt" --wait --timeout 30000 >/dev/null 2>&1 || true
    sleep 5
    case "$(_agent_status "$name")" in working|blocked) started=yes; break;; esac
    [ -s "$result" ] && { started=yes; break; }
  done
  [ "$started" = yes ] || { _fail "brief not picked up after three attempts"; return 1; }

  deadline=$(( $(date +%s) + max_min * 60 ))
  refused=0
  while :; do
    herdr agent wait "$name" --timeout 600000 >/dev/null 2>&1 || true
    st=$(_agent_status "$name")
    case "$st" in
      idle|done)
        [ -s "$result" ] || { _fail "stopped without a result (usage limit or error?)"; return 1; }
        break;;
      blocked)
        # Usually a permission request outside the worktree: refuse once and let it carry on, never grant.
        [ "$refused" = 0 ] || { _fail "blocked again on a permission prompt"; return 1; }
        refused=1
        herdr agent send-keys "$name" esc >/dev/null
        sleep 2
        herdr agent prompt "$name" "That action was refused. Work only inside this worktree and its output folder, and state in your result what you could not do because of that. Carry on." --wait --timeout 30000 >/dev/null 2>&1 || true;;
      gone) _fail "agent disappeared"; return 1;;
      working) ;;
      *) sleep 15;;
    esac
    [ "$(date +%s)" -lt "$deadline" ] || { _fail "not done after $max_min minutes"; return 1; }
  done

  herdr pane close "$HELPER_PANE" >/dev/null 2>&1 || true
  HELPER_PANE=
  return 0
}

runner_list() {
  herdr agent list | python3 -c "
import json, sys
for a in json.load(sys.stdin)['result']['agents']:
    if a.get('name'):
        print(a['name'] + '\t' + a['agent_status'])"
}

runner_screen() { herdr agent read "$1" --source visible 2>/dev/null; }

runner_prompt() { herdr agent prompt "$1" "$2" --wait --timeout 30000 >/dev/null 2>&1; }

# Stops the leader and helpers of one round and closes their tab; panes from the old shared tab are closed one by one.
runner_stop() {
  local wt=$1 name=$2 idl tab pane f
  [ "${HERDR_ENV:-}" = 1 ] || return 0
  idl=${name#dr-}
  herdr agent send-keys "$name" ctrl+c ctrl+c >/dev/null 2>&1 || true
  tab=$(_tab_of "$wt")
  if [ -n "$tab" ]; then
    herdr tab close "$tab" >/dev/null 2>&1 || true
  else
    for pane in $(herdr pane list --workspace "$HERDR_WORKSPACE_ID" | python3 -c "
import json, sys
for p in json.load(sys.stdin)['result']['panes']:
    l = p.get('label') or ''
    if l == '$name' or l.startswith('$idl-'):
        print(p['pane_id'])"); do
      herdr pane close "$pane" >/dev/null 2>&1 || true
    done
  fi
  for f in runner-tab herdr-tab; do rm -f "$(out_dir "$wt")/$f"; done
}

# After `finish`: closes the helpers and, shortly after, the tab of the round.
runner_after_finish() {
  local wt=$1 name=$2 pane tab
  [ "${HERDR_ENV:-}" = 1 ] || return 0
  for pane in $(_helper_panes_of "${name#dr-}"); do herdr pane close "$pane" >/dev/null 2>&1 || true; done
  tab=$(_tab_of "$wt")
  if [ -n "$tab" ]; then
    # Detached and delayed, so the leader can still print its closing line before its own pane goes.
    detach nohup sh -c "sleep 30; herdr tab close '$tab'" >/dev/null 2>&1 < /dev/null &
    echo "tab $tab closes in 30 seconds"
  fi
  return 0
}
