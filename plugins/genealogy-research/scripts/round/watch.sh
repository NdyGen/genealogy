#!/usr/bin/env bash
# For the coordinator, in the background: waits until something needs doing in a running round and reports it.
#   done         <output>/DONE exists (`lineage round finish` ran): review and merge
#   blocked      the leader waits on a permission prompt
#   quiet        the leader is idle without running helpers, twice in a row (usage limit, stuck)
#   no-agent     no leader runs and the round is not done
#   limit        the screen of the leader or a helper shows the account's usage limit; the reset is recorded
#                (dr-limit-<account>) and the round is resumed on another account, unless that one is at its
#                limit too (DR_AUTO_SWITCH=0 turns resuming off)
#   mail         new mail in the assistant's mailbox (read every half hour, DR_MAIL_INTERVAL); the reply is
#                already committed in <replies> and must be processed
#   forum        new reply to a question on the Geneanet forum (read as soon as Geneanet mails a notification,
#                otherwise every twelve hours, DR_FORUM_INTERVAL); the reply is already committed in the draft
#                file in <forum> and must be processed
#   forum-notice Geneanet mailed a notification (committed in <forum_notifications>); without a 'forum' line
#                next to it reading the thread failed: read it yourself or via the user
# Reports only what changed since the previous notice; a situation already reported does not hold the watcher.
# Mail and forum are polled only when their credential file exists.
# Usage: lineage round watch [interval-seconds, default 120]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

INTERVAL=${1:-120}
project_init
load_runner
STATE="$COMMON/dr-watch.state"
[ -f "$STATE" ] || { [ -f "$COMMON/dr-wacht.state" ] && cp "$COMMON/dr-wacht.state" "$STATE" || : > "$STATE"; }
# One watcher at a time, or the mailbox is read twice. A pidfile instead of flock: a lock fd would stay open in
# long-running child processes (herdr, start.sh). A lock of a process that no longer exists (or is no longer a
# watcher) is taken over.
LOCK="$COMMON/dr-watch.lock"
for attempt in 1 2 3; do
  if (set -o noclobber; echo $$ > "$LOCK") 2>/dev/null; then break; fi
  old=$(cat "$LOCK" 2>/dev/null || true)
  if [ -n "$old" ] && process_command "$old" | grep -Eq 'watch\.sh|wacht\.sh'; then
    echo "watcher already running (pid $old)"
    exit 75
  fi
  rm -f "$LOCK"
  [ "$attempt" = 3 ] && { echo "cannot take the watch lock" >&2; exit 1; }
done
trap 'if [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ]; then rm -f "$LOCK"; fi' EXIT
# A restart must remember who was already quiet, or a leader waiting out a usage limit is reported again.
previous_quiet=$(awk '$2 == "quiet" {print $1}' "$STATE")
MAIL_STAMP="$COMMON/dr-mail.last"
FORUM_STAMP="$COMMON/dr-forum.last"

# Reads the assistant's mailbox at most every DR_MAIL_INTERVAL seconds; new replies are committed in main
# right away, so no uncommitted file blocks start.sh or merge.sh.
read_mailbox() {
  local now last out
  [ "$(cd "$ROOT" && lineage config value mail_enabled)" = true ] || return 0
  [ -n "$(credential_file mail)" ] || return 0
  now=$(date +%s); last=$(cat "$MAIL_STAMP" 2>/dev/null || echo 0)
  [ $((now - last)) -ge "${DR_MAIL_INTERVAL:-1800}" ] || return 0
  echo "$now" > "$MAIL_STAMP"
  out=$(cd "$ROOT" && lineage mail inbox 2>>"$COMMON/dr-mail.log") || return 0
  [ "$out" = "no new mail" ] || [ "$out" = "geen nieuwe mail" ] && return 0
  git -C "$ROOT" add "$REPLIES" "$FORUM_NOTIF" 2>/dev/null || true
  git -C "$ROOT" commit -q -m "Mailbox: new mail stored (to process)" -- "$REPLIES" "$FORUM_NOTIF" 2>/dev/null || true
  # A Geneanet notification means a reply on the forum: read the threads in this round instead of waiting.
  if echo "$out" | grep -q "^$FORUM_NOTIF/"; then rm -f "$FORUM_STAMP"; fi
  # The notification is reported itself too: reading the thread can fail (a Cloudflare check).
  echo "$out" | sed -e "s#^$REPLIES/#mail #" -e "s#^$FORUM_NOTIF/#forum-notice #"
}

# The forum threads: read right after a Geneanet notification mail, otherwise twice a day as a fallback.
read_forum() {
  local now last out
  [ -n "$(credential_file geneanet)" ] || return 0
  grep -Elq '^status: (posted|geplaatst)' "$ROOT/$FORUM"/*.md 2>/dev/null || return 0
  now=$(date +%s); last=$(cat "$FORUM_STAMP" 2>/dev/null || echo 0)
  [ $((now - last)) -ge "${DR_FORUM_INTERVAL:-43200}" ] || return 0
  echo "$now" > "$FORUM_STAMP"
  out=$(cd "$ROOT" && lineage forum read 2>>"$COMMON/dr-forum.log") || return 0
  [ "$out" = "no new replies" ] || [ "$out" = "geen nieuwe reacties" ] && return 0
  git -C "$ROOT" add "$FORUM"
  git -C "$ROOT" commit -q -m "Forum: new reply stored (to process)" -- "$FORUM" || true
  echo "$out" | grep -E '^[^ ].*(new repl|nieuwe reactie)' | sed 's#^#forum #'
}

# Prints "<account> <reset-epoch>" when the leader's or a helper's screen shows the usage-limit message.
limit_on_screen() {
  local wt=$1 idl=$2 name account_file account reset
  account_file=$(marker_file "$wt" account || true)
  account=$(cat "${account_file:-/dev/null}" 2>/dev/null || true)
  account=${account:-${ALLOWED%% *}}
  for name in "dr-$idl" $(runner_list | awk -F'\t' -v p="$idl-" 'index($1, p) == 1 {print $1}'); do
    reset=$(runner_screen "$name" | lineage limits parse) && { echo "$account $reset"; return 0; }
  done
  return 1
}

# Records the limit and, when another allowed account is free, resumes the round there.
switch_on_limit() {
  local id=$1 wt=$2 idl=$3 acc reset other candidate result found
  found=$(limit_on_screen "$wt" "$idl") || return 1
  read -r acc reset <<<"$found"
  [ -n "$acc" ] && [ -n "$reset" ] || return 1
  echo "$reset" > "$COMMON/dr-limit-$acc"
  other=
  for candidate in $ALLOWED; do
    [ "$candidate" != "$acc" ] && ! account_on_limit "$candidate" && { other=$candidate; break; }
  done
  if [ "${DR_AUTO_SWITCH:-${DR_AUTO_WISSEL:-1}}" = 1 ] && [ -n "$other" ]; then
    if result=$("$ROUND_DIR/start.sh" "$id" --resume --account "$other" 2>&1 | tail -1); then
      echo "$id limit $acc (reset $(clock_time "$reset")); resumed on $other"
    else
      echo "$id limit $acc; resuming on $other failed: $result"
    fi
  else
    echo "$id limit $acc (reset $(clock_time "$reset")); no other account free or switching off, waiting"
  fi
}

while :; do
  ALLOWED=$(allowed_accounts)
  # Heartbeat per pane: the guard starts its own coordinator when no watcher has beaten for half an hour,
  # and closes that auto-coordinator again while another session's watcher beats.
  mkdir -p "$COMMON/dr-coordinator.alive.d"
  date +%s > "$COMMON/dr-coordinator.alive.d/$(echo "${HERDR_PANE_ID:-no-pane}" | tr : _)"
  # Without an agent list (herdr not answering) every round would look agent-less: skip this check.
  agents=$(runner_list) || { sleep "$INTERVAL"; continue; }
  notices=$(ROOT="$ROOT" PREVIOUS_QUIET="$previous_quiet" OUT="$OUT" AGENTS="$agents" python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["ROOT"])
agents = {}
for line in os.environ["AGENTS"].splitlines():
    name, _, status = line.partition("\t")
    if name:
        agents[name] = status
previous_quiet = set(os.environ["PREVIOUS_QUIET"].split())
for wt in sorted((root / ".worktrees").glob("dr-*")):
    id_ = wt.name[3:]
    idl = id_.lower()
    leader = agents.get(f"dr-{idl}")
    helpers = [n for n in agents if n.startswith(f"{idl}-")]
    out = [wt / os.environ["OUT"], wt / "uitvoer"]
    if any((o / n).exists() for o in out for n in ("DONE", "KLAAR")):
        print(f"{id_} done")
    elif leader is None:
        print(f"{id_} no-agent")
    elif leader == "blocked":
        print(f"{id_} blocked")
    elif leader in ("idle", "done") and not helpers:
        print(f"{id_} quiet" if id_ in previous_quiet else f"{id_} quiet?")
PY
)
  # A quiet or finished leader may be at a usage limit: check the screens and switch account, unless the
  # guard runs (heartbeat younger than ten minutes); then it handles limits and two would race.
  limit_notices=""
  guard_running=0
  [ $(( $(date +%s) - $(grep -Eo "^[0-9]+" "$(state_read_path dr-guard.alive dr-bewaker.alive)" 2>/dev/null || echo 0) )) -lt 600 ] && guard_running=1
  while read -r id state; do
    [ "$guard_running" = 1 ] && break
    [ -n "$id" ] || continue
    case "$state" in quiet|quiet\?|no-agent) ;; *) continue;; esac
    wt="$ROOT/.worktrees/dr-$id"; idl=$(lower "$id")
    m=$(switch_on_limit "$id" "$wt" "$idl" || true)
    [ -n "$m" ] && limit_notices="$limit_notices$m"$'\n' && notices=$(echo "$notices" | grep -v "^$id " || true)
  done <<<"$notices"
  # A leader waiting on its own background shell (a download, a helper) is not quiet.
  busy=""
  while read -r id state; do
    case "$state" in quiet|quiet\?) ;; *) continue;; esac
    runner_screen "dr-$(lower "$id")" | grep -qE '[0-9]+ shells? still running|· [0-9]+ shells?' && busy="$busy $id"
  done <<<"$notices"
  for id in $busy; do notices=$(echo "$notices" | grep -v "^$id " || true); done
  previous_quiet=$(echo "$notices" | awk '$2 == "quiet?" || $2 == "quiet" {print $1}')
  current=$(echo "$notices" | grep -v ' quiet?$' | sed '/^$/d' | sort || true)
  new=$(comm -13 "$STATE" <(echo "$current") | sed '/^$/d')
  echo "$current" > "$STATE"
  mail_notices=$(read_mailbox || true)
  forum_notices=$(read_forum || true)
  new=$(printf '%s\n%s\n%s\n%s' "$limit_notices" "$mail_notices" "$forum_notices" "$new" | sed '/^$/d')
  if [ -n "$new" ]; then
    echo "$new"
    exit 0
  fi
  sleep "$INTERVAL"
done
