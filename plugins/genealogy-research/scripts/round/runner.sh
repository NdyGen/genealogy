# Shared library of the research-round scripts (source it, do not run it).
#
# Provides project paths from lineage.toml, account and usage-limit helpers, marker file names (with the old
# Dutch names still read), and picks the runner: it loads runner-<name>.sh, which implements
# runner_start_leader, runner_start_helper, runner_list, runner_screen, runner_stop, runner_prompt,
# runner_after_finish, runner_start_coordinator and runner_start_guard, and optionally runner_guard_alive
# (see docs/rounds.md).

ROUND_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# lineage itself runs frozen; this keeps any other uv call from rewriting the project's uv.lock in main.
export UV_FROZEN=1
PLUGIN_ROOT=$(cd "$ROUND_DIR/../.." && pwd)

# The scripts run through `lineage round`, which puts the plugin's bin/ on PATH; the guard starts them by path.
command -v lineage >/dev/null 2>&1 || lineage() { "$PLUGIN_ROOT/bin/lineage" "$@"; }

die() { echo "$*" >&2; exit "${DIE_CODE:-1}"; }

# --- portability: macOS has BSD tools and bash 3.2; these cover the GNU-only bits ------------------------

clock_time() { date -d "@$1" +%H:%M 2>/dev/null || date -r "$1" +%H:%M; }
now_iso() { date +%Y-%m-%dT%H:%M:%S%z; }
abs_path() { python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }

# Runs a command in its own session (process group), so it outlives the caller and can be stopped as a group.
detach() {
  if command -v setsid >/dev/null; then setsid "$@"; else
    python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@"
  fi
}

# with_timeout <seconds> <command...>: exit 124 when the time is up, like GNU timeout.
with_timeout() {
  local secs=$1; shift
  if command -v timeout >/dev/null; then timeout "$secs" "$@"; else
    python3 -c '
import subprocess, sys
try:
    sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1])).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)' "$secs" "$@"
  fi
}

# A lock directory instead of flock (not on macOS); a lock left by a process that is gone is taken over.
lock_take() {
  local dir="$1.d" holder
  until mkdir "$dir" 2>/dev/null; do
    holder=$(cat "$dir/pid" 2>/dev/null || true)
    if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then rm -rf "$dir"; continue; fi
    sleep 1
  done
  echo $$ > "$dir/pid"
}
lock_release() { rm -rf "$1.d"; }

# The name of the program running as pid, or nothing.
process_command() { ps -p "$1" -o command= 2>/dev/null || true; }

# Runs python with the lineage package (merge helpers), in the same venv as the lineage wrapper.
lineage_py() {
  command -v uv >/dev/null || die "lineage needs uv: https://docs.astral.sh/uv/getting-started/installation/"
  local venv=${LINEAGE_VENV:-} data d
  if [ -z "$venv" ]; then
    data="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/data"
    venv="$data/genealogy-research-genealogy/venv"
    for d in "$data"/genealogy-research-*/; do [ -d "$d/venv" ] && { venv="${d%/}/venv"; break; }; done
  fi
  UV_PROJECT_ENVIRONMENT="$venv" uv run --quiet --frozen --no-dev --project "$PLUGIN_ROOT/cli" python "$@"
}

# --- project ---------------------------------------------------------------------------------------------

# Sets ROOT (the project, from the working directory), COMMON (git common dir) and the config paths, all
# relative to ROOT (DR_PROJECT names the project folder when the caller runs elsewhere, like the guard). Stops with a clear message without a git repository or a usable lineage.toml.
project_init() {
  [ -z "${DR_PROJECT:-}" ] || cd "$DR_PROJECT"
  ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die "not a git repository: $PWD (research rounds run in the project's git repository)"
  COMMON=$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)
  if [ ! -f "$ROOT/lineage.toml" ]; then
    # A worktree branched before lineage.toml was committed reads the one of the main checkout.
    local main_toml
    main_toml="$(dirname "$COMMON")/lineage.toml"
    [ -f "$main_toml" ] || die "no lineage.toml in $ROOT; run /genealogy-research:setup or 'lineage init' first"
    export LINEAGE_CONFIG="$main_toml"
  fi
  local key paths line
  paths=$(cd "$ROOT" && lineage config paths 2>&1) || die "lineage.toml in $ROOT is invalid: $paths"
  while IFS='=' read -r key line; do
    case "$key" in
      gedcom) GEDCOM=$line;; queue) QUEUE=$line;; log) LOG=$line;; research) RESEARCH=$line;;
      reports) REPORTS=$line;; data) DATA=$line;; requests) REQUESTS=$line;; replies) REPLIES=$line;;
      forum) FORUM=$line;; forum_notifications) FORUM_NOTIF=$line;; person_reports) PERSON_REPORTS=$line;;
      life_stories) LIFE_STORIES=$line;; stories_checked) STORIES_CHECKED=$line;; output) OUT=$line;;
      sources) SOURCES=$line;;
    esac
  done <<<"$paths"
  for key in GEDCOM QUEUE LOG RESEARCH REPORTS DATA REQUESTS REPLIES FORUM FORUM_NOTIF PERSON_REPORTS LIFE_STORIES STORIES_CHECKED OUT SOURCES; do
    [ -n "${!key}" ] || die "lineage config gave no path for $key"
  done
  MAIN_BRANCH=$(main_branch)
}

main_branch() {
  local b
  [ -z "${DR_MAIN_BRANCH:-}" ] || { echo "$DR_MAIN_BRANCH"; return; }
  for b in main master; do
    git -C "$ROOT" show-ref --verify --quiet "refs/heads/$b" && { echo "$b"; return; }
  done
  git -C "$ROOT" rev-parse --abbrev-ref HEAD
}

lower() { echo "$1" | tr '[:upper:]' '[:lower:]'; }
upper() { echo "$1" | tr '[:lower:]' '[:upper:]'; }

# --- worktree markers ------------------------------------------------------------------------------------

# Output folder of a worktree; a worktree started before the rename may still use the Dutch folder.
out_dir() {
  local wt=$1
  if [ -d "$wt/$OUT" ] || [ ! -d "$wt/uitvoer" ]; then echo "$wt/$OUT"; else echo "$wt/uitvoer"; fi
}

# marker_file <wt> <name> [old-name...]: path of the first marker that exists.
marker_file() {
  local wt=$1 name f out
  shift
  out=$(out_dir "$wt")
  for name in "$@"; do
    f="$out/$name"
    [ -e "$f" ] && { echo "$f"; return 0; }
  done
  return 1
}

# --- accounts and usage limits ---------------------------------------------------------------------------

# One line per configured account: name<TAB>config_dir (empty for the default).
account_table() { (cd "${ROOT:-.}" && lineage config accounts); }

# State in the git common dir under its new name; the old name is read when only that one exists.
state_read_path() {
  local new=$1 old=${2:-}
  if [ ! -e "$COMMON/$new" ] && [ -n "$old" ] && [ -e "$COMMON/$old" ]; then echo "$COMMON/$old"; else echo "$COMMON/$new"; fi
}

limit_file() { state_read_path "dr-limit-$1" "dr-limiet-$1"; }

# Accounts that may run research: dr-accounts (one per line or space separated) limits the configured ones.
allowed_accounts() {
  local f configured acc out=""
  configured=$(account_table | awk -F'\t' '{print $1}')
  f="$COMMON/dr-accounts"
  if [ -s "$f" ]; then
    for acc in $(cat "$f"); do
      case " $(echo $configured) " in *" $acc "*) out="$out $acc";; esac
    done
  fi
  echo ${out:-$(echo $configured)}
}

# Config dir of an account (empty for the default one).
account_dir() { account_table | awk -F'\t' -v a="$1" '$1 == a {print $2; exit}'; }

account_on_limit() {
  local f reset
  f=$(limit_file "$1")
  [ -s "$f" ] || return 1
  reset=$(cat "$f")
  [ "$reset" -gt "$(date +%s)" ]
}

limit_reset_time() {
  local acc f
  for acc in $(account_table | awk -F'\t' '{print $1}'); do
    f=$(limit_file "$acc"); [ -s "$f" ] && clock_time "$(cat "$f")"
  done | sort | head -1
}

# Shell snippet that selects the account: for herdr panes (run as a command line) and for subshells.
# (The hc runner passes the account through env(1) instead.)
account_env_snippet() {
  local dir
  dir=$(account_dir "$1")
  dir=${dir/#\~/$HOME}
  if [ -n "$dir" ]; then echo "export CLAUDE_CONFIG_DIR='$dir'"; else echo "unset CLAUDE_CONFIG_DIR ANTHROPIC_MODEL"; fi
}

# --- credentials -----------------------------------------------------------------------------------------

# Prints the credential file of a service (mail, geneanet) when it exists. LINEAGE_<SVC>_CONFIG or the old
# NDYGEN_<SVC>_CONFIG name an explicit file (a non-existing one switches the service off).
credential_file() {
  local svc=$1 up var f
  up=$(upper "$svc")
  for var in "LINEAGE_${up}_CONFIG" "NDYGEN_${up}_CONFIG"; do
    if [ -n "${!var:-}" ]; then [ -f "${!var}" ] && echo "${!var}"; return 0; fi
  done
  for f in "$HOME/.config/lineage/$svc.env" "$HOME/.config/ndygen/$svc.env"; do
    [ -f "$f" ] && { echo "$f"; return 0; }
  done
  return 0
}

# --- runner ----------------------------------------------------------------------------------------------

# A leader needs a herdr session for the herdr runner and hc for the hc runner; without them, the round is
# prepared and left to the user.
load_runner() {
  RUNNER=$(cd "${ROOT:-.}" && lineage config runner)
  if [ "$RUNNER" = herdr ] && [ "${HERDR_ENV:-}" != 1 ]; then
    echo "not in Herdr; using the inline runner (start the agent yourself in the worktree)" >&2
    RUNNER=inline
  fi
  if [ "$RUNNER" = hc ] && ! command -v hc >/dev/null; then
    echo "hc (herdr-core) is not on PATH; using the inline runner (start the agent yourself in the worktree)" >&2
    RUNNER=inline
  fi
  [ -f "$ROUND_DIR/runner-$RUNNER.sh" ] || die "unknown runner '$RUNNER'"
  # shellcheck source=/dev/null
  source "$ROUND_DIR/runner-$RUNNER.sh"
}

# Writes <result>.error.txt for a helper that did not deliver, with the last screen when there is one.
helper_fail() {
  local result=$1 name=$2 reason=$3 screen=${4:-} errfile
  errfile="${result%.md}.error.txt"
  { echo "$reason"; echo; [ -z "$screen" ] || echo "$screen"; } > "$errfile"
  echo "FAILED $name: $reason (see $errfile)" >&2
}
