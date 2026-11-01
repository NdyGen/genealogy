# hc runner (source, do not run): rounds run as herdr-core terminals, shown in the Herdr app.
#
# Every terminal of the project carries lineage.project=<git common dir> (hc names are unique among all
# live terminals of the user, so lookups filter on the project first), lineage.role and, for rounds,
# lineage.round=<ID>. Names stay as under herdr: leader dr-<id>, helpers <id>-<role>-<nr>, coordinator,
# guard.
#
# Placement in the app: leaders, the coordinator and the guard get no hc parent (a parent's end would end
# them, and the guard restarts coordinators) but copy only the herdr.space label of the terminal that
# starts them: each gets its own tab in the coordinator's space, as under herdr. The app keeps its layout in
# the hc document herdr-app (spaces, their tabs and the terminals in them); _hc_name_tab names the new tab
# there, since the app numbers an unnamed one. A helper is a child of its leader: it
# ends with the leader, shows as its sub-agent, and --no-notify keeps hc from typing notes into the
# leader's prompt while helper.sh already waits for it.

# name<TAB>address<TAB>status of the project's live terminals carrying all given labels (--all first: the
# finished ones too).
_hc_terms() {
  local args=(ls --json --label "lineage.project=$COMMON") l
  [ "${1:-}" != --all ] || { args+=(--all); shift; }
  for l in "$@"; do args+=(--label "$l"); done
  hc "${args[@]}" | python3 -c '
import json, sys
# No status yet means booting; an error ends a turn like idle (see guard.hc_status).
mapped = {None: "working", "error": "idle"}
for t in json.load(sys.stdin)["terminals"]:
    s = t.get("status")
    if isinstance(s, dict):
        s = s.get("state")
    print("\t".join([t.get("name") or "", t["address"], mapped.get(s, s)]))'
}

_hc_addr() { _hc_terms | awk -F'\t' -v n="$1" '$1 == n {print $2; exit}'; }

# Status of one terminal by address; gone once it has finished.
_hc_get_status() {
  hc get "$1" --json 2>/dev/null | python3 -c '
import json, sys
t = json.load(sys.stdin)
s = t.get("status")
s = s.get("state") if isinstance(s, dict) else s
print("gone" if t.get("state") == "finished" else {None: "working", "error": "idle"}.get(s, s))' || echo gone
}

# The herdr.space label of the terminal this runs in; outside a terminal (the guard from cron) DR_HC_SPACE.
# Without herdr.tab the app opens a new tab.
_hc_placement() {
  if [ -z "${HC_TERMINAL_ID:-}" ]; then
    [ -z "${DR_HC_SPACE:-}" ] || echo "herdr.space=$DR_HC_SPACE"
    return 0
  fi
  hc get "$HC_TERMINAL_ID" --json 2>/dev/null | python3 -c '
import json, sys
space = json.load(sys.stdin).get("labels", {}).get("herdr.space")
if space:
    print("herdr.space=" + space)' || true
}

# _hc_name_tab <address> <title>: names the app's tab that holds only this terminal, once the app has made
# it (up to 30 seconds). A tab someone already named keeps its name. Without the app's document nothing happens.
_hc_name_tab() {
  python3 -c '
import json, subprocess, sys, time

addr, title = sys.argv[1:]

def call(method, params):
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    out = subprocess.run(["hc", "connect"], input=req + "\n", capture_output=True, text=True, timeout=15).stdout
    return json.loads(out.splitlines()[0])

def terminals(node):
    if (node.get("content") or {}).get("terminal"):
        yield node["content"]["terminal"]
    for child in node.get("children", []):
        yield from terminals(child)

deadline = time.time() + 30
while time.time() < deadline:
    doc = call("doc.get", {"name": "herdr-app"}).get("result") or {}
    if not doc.get("value"):
        break
    tab = next((t for sp in (doc.get("value") or {}).get("spaces", []) for t in sp.get("tabs", [])
                if list(terminals(t.get("root", {}))) == [addr]), None)
    if tab is not None:
        if tab.get("name"):
            break
        tab["name"] = title
        if "result" in call("doc.set", {"name": "herdr-app", "value": doc["value"], "version": doc["version"]}):
            break
        continue
    time.sleep(2)' "$1" "$2" >/dev/null 2>&1 || true
}

# The env(1) arguments for a Claude terminal: hc starts programs in the core's environment, not the
# caller's, so PATH (claude, lineage) and the account are passed explicitly.
_hc_env() {
  local dir=$1
  # env(1) takes its options before the assignments.
  printf '%s\n' -u ANTHROPIC_MODEL
  if [ -n "$dir" ]; then printf '%s\n' "CLAUDE_CONFIG_DIR=$dir"; else printf '%s\n' -u CLAUDE_CONFIG_DIR; fi
  printf '%s\n' "PATH=$PATH"
}

# hc_start <name> <cwd> <role> <round-or-empty> <parent-or-empty> <config-dir> <command...>
# Starts a terminal in the background and prints its address.
hc_start() {
  local name=$1 cwd=$2 role=$3 round=$4 parent=$5 dir=$6 l
  shift 6
  local args=(run --bg --json --name "$name" --cwd "$cwd" --label "lineage.project=$COMMON" --label "lineage.role=$role")
  [ -z "$round" ] || args+=(--label "lineage.round=$round")
  if [ -n "$parent" ]; then
    args+=(--parent "$parent" --no-notify)
  else
    args+=(--no-parent)
    while IFS= read -r l; do [ -z "$l" ] || args+=(--label "$l"); done < <(_hc_placement)
  fi
  local envs=()
  while IFS= read -r l; do envs+=("$l"); done < <(_hc_env "$dir")
  hc "${args[@]}" env "${envs[@]}" "$@" | python3 -c 'import json,sys;print(json.load(sys.stdin)["address"])'
}

# Waits up to <seconds> until a freshly started Claude has begun its first turn (or a helper already wrote
# <result>), answering the trust dialog of a new folder once. Returns 1 when it did not start or exited.
hc_await_start() {
  local addr=$1 secs=${2:-90} result=${3:-} deadline info answered=0
  deadline=$(( $(date +%s) + secs ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    # "<state> <status> <turn>"; turn goes up each time the status leaves working.
    info=$(hc get "$addr" --json 2>/dev/null | python3 -c '
import json, sys
t = json.load(sys.stdin)
s = t.get("status")
s = s.get("state") if isinstance(s, dict) else s
print(t.get("state"), s, t.get("turn") or 0)') || return 1
    case "$info" in
      finished*) return 1;;
      *" working "*) return 0;;
      *" 0") ;;
      *) return 0;;
    esac
    [ -n "$result" ] && [ -s "$result" ] && return 0
    if [ "$answered" = 0 ] && hc read "$addr" 2>/dev/null | grep -q "trust this folder"; then
      hc keys "$addr" down enter >/dev/null 2>&1 || true
      answered=1
    else
      case "$info" in *" blocked "*) return 0;; esac
    fi
    sleep 2
  done
  return 1
}

# Kills the terminals and removes them from the list, so their names are free again.
hc_close() {
  local addr
  for addr in "$@"; do
    hc kill "$addr" >/dev/null 2>&1 || true
    hc rm "$addr" >/dev/null 2>&1 || true
  done
}

runner_start_leader() {
  local wt=$1 name=$2 label=$3 model=$4 account=$5 prompt=$6 dir id addr old title
  id=$(upper "${name#dr-}")
  dir=$(account_dir "$account")
  dir=${dir/#\~/$HOME}
  title=$id
  [ "$label" = "$id" ] || title="$id $label"
  old=$(_hc_addr "$name")
  [ -z "$old" ] || hc_close "$old"
  # The brief goes in as claude's first prompt, so it cannot be lost while the agent boots.
  addr=$(hc_start "$name" "$wt" leader "$id" "" "$dir" claude --model "$model" --permission-mode auto "$prompt") \
    || { echo "hc could not start $name" >&2; return 1; }
  hc label "$addr" "lineage.person=$label" >/dev/null 2>&1 || true
  hc_await_start "$addr" 90 || echo "WARNING: $name did not pick up the brief within 90 seconds (hc read $addr)" >&2
  _hc_name_tab "$addr" "$title"
  RUNNER_WHERE="terminal $addr"
  return 0
}

# Blocks until the helper is done. Memory caps both the total number of agents and the helpers per round.
runner_start_helper() {
  local wt=$1 name=$2 agent=$3 prompt=$4 result=$5
  local id max_total max_per max_min lock total own deadline refused st screen
  id=$(upper "${name%%-*}")
  max_total=${DR_MAX_AGENTS:-24}
  max_per=${DR_MAX_HELPERS:-${DR_MAX_HULP:-3}}
  max_min=${DR_HELPER_MAX_MIN:-${DR_HULP_MAX_MIN:-120}}
  HELPER_ADDR=

  _fail() {
    screen=
    [ -z "$HELPER_ADDR" ] || screen=$(hc read "$HELPER_ADDR" --lines 60 2>/dev/null || true)
    helper_fail "$result" "$name" "$1" "$screen"
    [ -z "$HELPER_ADDR" ] || hc_close "$HELPER_ADDR"
    HELPER_ADDR=
    return 1
  }

  lock="$COMMON/dr-helper.lock"
  while :; do
    lock_take "$lock"
    # Memory is per machine: every live Claude terminal counts, of any project.
    total=$(hc ls --json | python3 -c '
import json, sys
print(sum(1 for t in json.load(sys.stdin)["terminals"] if t.get("agent") == "claude-code"))')
    own=$(_hc_terms "lineage.round=$id" "lineage.role=helper" | wc -l)
    [ "$total" -lt "$max_total" ] && [ "$own" -lt "$max_per" ] && break
    lock_release "$lock"
    sleep 30
  done

  # An interrupted script (the leader stopping its background task) must not leave an idle helper behind.
  trap '[ -n "$HELPER_ADDR" ] && hc_close "$HELPER_ADDR"' EXIT
  trap 'exit 143' TERM INT HUP
  # Same account as the leader; the model comes from the agent definition, so ANTHROPIC_MODEL must not override it.
  HELPER_ADDR=$(hc_start "$name" "$wt" helper "$id" "${HC_TERMINAL_ID:-}" "${CLAUDE_CONFIG_DIR:-}" \
    claude --agent "$agent" --permission-mode auto "$prompt") || { lock_release "$lock"; HELPER_ADDR=; _fail "hc could not start the helper"; return 1; }
  hc_await_start "$HELPER_ADDR" 90 "$result" || { lock_release "$lock"; _fail "brief not picked up within 90 seconds"; return 1; }
  lock_release "$lock"

  deadline=$(( $(date +%s) + max_min * 60 ))
  refused=0
  while :; do
    hc wait "$HELPER_ADDR" --timeout 600 >/dev/null 2>&1 || true
    st=$(_hc_get_status "$HELPER_ADDR")
    case "$st" in
      idle|done)
        [ -s "$result" ] || { _fail "stopped without a result (usage limit or error?)"; return 1; }
        break;;
      blocked)
        # Usually a permission request outside the worktree: refuse once and let it carry on, never grant.
        [ "$refused" = 0 ] || { _fail "blocked again on a permission prompt"; return 1; }
        refused=1
        hc keys "$HELPER_ADDR" esc >/dev/null 2>&1 || true
        # hc refuses to type into a blocked program; give the dialog time to close first.
        for _ in 1 2 3 4 5 6 7 8 9 10; do
          sleep 1
          [ "$(_hc_get_status "$HELPER_ADDR")" = blocked ] || break
        done
        hc send "$HELPER_ADDR" "That action was refused. Work only inside this worktree and its output folder, and state in your result what you could not do because of that. Carry on." >/dev/null 2>&1 || true;;
      gone) _fail "agent disappeared"; return 1;;
      working) ;;
      *) sleep 15;;
    esac
    [ "$(date +%s)" -lt "$deadline" ] || { _fail "not done after $max_min minutes"; return 1; }
  done

  hc_close "$HELPER_ADDR"
  HELPER_ADDR=
  return 0
}

runner_list() { _hc_terms | awk -F'\t' '$1 != "" {print $1 "\t" $3}'; }

runner_screen() {
  local addr
  addr=$(_hc_addr "$1")
  [ -z "$addr" ] || hc read "$addr" 2>/dev/null
}

runner_prompt() {
  local addr
  addr=$(_hc_addr "$1")
  [ -n "$addr" ] || return 1
  hc send "$addr" "$2" >/dev/null 2>&1
}

# Stops the leader and helpers of one round and removes their terminals, finished ones included.
runner_stop() {
  local wt=$1 name=$2 id addrs
  command -v hc >/dev/null || return 0
  id=$(upper "${name#dr-}")
  addrs=$(_hc_terms --all "lineage.round=$id" | awk -F'\t' '{print $2}') || addrs=
  # shellcheck disable=SC2086
  [ -z "$addrs" ] || hc_close $addrs
  for f in runner-tab herdr-tab; do rm -f "$(out_dir "$wt")/$f"; done
}

# After `finish`: closes the helpers now and the leader shortly after.
runner_after_finish() {
  local wt=$1 name=$2 id leader helpers
  command -v hc >/dev/null || return 0
  id=$(upper "${name#dr-}")
  helpers=$(_hc_terms --all "lineage.round=$id" "lineage.role=helper" | awk -F'\t' '{print $2}') || helpers=
  # shellcheck disable=SC2086
  [ -z "$helpers" ] || hc_close $helpers
  leader=$(_hc_addr "$name") || leader=
  if [ -n "$leader" ]; then
    # Detached and delayed, so the leader can still print its closing line before its terminal goes.
    detach nohup sh -c "sleep 30; hc kill '$leader'; hc rm '$leader'" >/dev/null 2>&1 < /dev/null &
    echo "terminal $leader closes in 30 seconds"
  fi
  return 0
}

runner_start_coordinator() {
  local main=$1 account=$2 prompt=$3 dir old addr
  dir=$(account_dir "$account")
  dir=${dir/#\~/$HOME}
  old=$(_hc_addr coordinator)
  [ -z "$old" ] || { hc_close "$old"; sleep 2; }
  addr=$(hc_start coordinator "$main" coordinator "" "" "$dir" claude --model opus --permission-mode auto "$prompt") || return 1
  hc_await_start "$addr" 90 || echo "WARNING: the coordinator did not start its first turn (hc read $addr)" >&2
  _hc_name_tab "$addr" coordinator
  RUNNER_WHERE="terminal $addr"
}

# Whether the project's guard terminal still lives; its heartbeat stays fresh for ten minutes after a kill.
runner_guard_alive() { [ -n "$(_hc_terms lineage.role=guard)" ]; }

runner_stop_guard() { _hc_terms lineage.role=guard | cut -f2 | while read -r a; do hc_close "$a"; done; }

# Environment for the guard run from cron, where no terminal tells the runner or the space.
runner_cron_env() {
  echo DR_RUNNER=hc
  local space
  space=$(_hc_placement | sed -n 's/^herdr\.space=//p')
  [ -z "$space" ] || echo "DR_HC_SPACE=$space"
}

runner_start_guard() {
  local main=$1 addr
  shift
  addr=$(hc_start guard "$main" guard "" "" "" env DR_RUNNER=hc "$@") || return 1
  _hc_name_tab "$addr" guard
  RUNNER_WHERE="terminal $addr"
}
