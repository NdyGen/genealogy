#!/usr/bin/env bash
# Tells a round's leader something: a correction from the review, an answer to a question in the report.
# The leader has the round's context, so it repairs cheaper and more precisely than the coordinator can.
#
# A live leader gets the text typed in. After `round finish` its terminal is gone: then its own Claude session
# (the last leader session in the worktree) is resumed with the text as its next prompt, on the round's
# account. Either way the round's DONE marker goes, so the coordinator waits for the leader's new finish.
# Usage: lineage round tell <ID> <text> | lineage round tell <ID> --file <path> [--account <name>]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"
USAGE="usage: lineage round tell <ID> <text> | --file <path> [--account <name>]"
ID=${1:?$USAGE}
ID=$(upper "${ID#@}")
shift
TEXT=
ACCOUNT=
while [ $# -gt 0 ]; do
  case "$1" in
    --file) TEXT=$(cat "${2:?path missing}"); shift 2;;
    --account) ACCOUNT=${2:?account missing}; shift 2;;
    *) TEXT="${TEXT:+$TEXT }$1"; shift;;
  esac
done
[ -n "$TEXT" ] || { echo "$USAGE" >&2; exit 2; }
project_init
cd "$ROOT"
WT="$ROOT/.worktrees/dr-$ID"
NAME="dr-$(lower "$ID")"
[ -d "$WT" ] || { echo "round $ID has no worktree ($WT); after a merge, start a follow-up round instead" >&2; exit 1; }
OUTDIR=$(out_dir "$WT")
load_runner

PROMPT="Message from the coordinator about round $ID: $TEXT
Do this in this worktree, commit, run 'lineage round finish' again and end with DONE $ID."

rm -f "$OUTDIR/DONE"
if runner_prompt "$NAME" "$PROMPT" 2>/dev/null; then
  echo "$ID: told the running leader ($NAME)"
  exit 0
fi

found=$(lineage leader-session "$ID") || exit 1
SESSION=${found%%$'\t'*}
SESSION_ACCOUNT=${found##*$'\t'}
ACCOUNT=${ACCOUNT:-$SESSION_ACCOUNT}
[ "$ACCOUNT" = "$SESSION_ACCOUNT" ] || {
  echo "the leader's session is on account $SESSION_ACCOUNT; a session cannot be resumed on $ACCOUNT" >&2; exit 2; }
ALLOWED=$(allowed_accounts)
case " $ALLOWED " in *" $ACCOUNT "*) ;; *)
  echo "account $ACCOUNT is not allowed (allowed: $ALLOWED); allow it in $COMMON/dr-accounts for this message" >&2
  exit 2;;
esac
if account_on_limit "$ACCOUNT"; then
  echo "account $ACCOUNT is at its usage limit until $(clock_time "$(cat "$(limit_file "$ACCOUNT")")")" >&2
  exit 3
fi
MODEL=$(cat "$OUTDIR/model" 2>/dev/null || echo opus)
PERSON=$(cd "$WT" && lineage person "$ID" | sed -n 1p | sed -E 's/ \[[A-Za-z0-9]+\]$//')
RESUME_SESSION=$SESSION runner_start_leader "$WT" "$NAME" "${PERSON:-$ID}" "$MODEL" "$ACCOUNT" "$PROMPT"
echo "$ID: resumed the leader's session $SESSION on account $ACCOUNT ($RUNNER runner${RUNNER_WHERE:+, $RUNNER_WHERE})"
