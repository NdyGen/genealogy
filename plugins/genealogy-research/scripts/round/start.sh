#!/usr/bin/env bash
# Starts deep research on one person from the queue: status in_progress with its own ID block, its own
# worktree and branch, and a leader started by the runner (docs/rounds.md): a herdr tab labelled with the
# person's name (leader pane dr-<id>; helpers from `lineage round helper` come as panes next to it), a
# background process (headless) or instructions for the user (inline).
#
# --resume: an interrupted round gets a new leader in the existing worktree.
# The account is explicit, independent of the caller's environment (lineage config accounts). A new start
# defaults to the first allowed account (dr-accounts in the git common dir, else all); --resume defaults to
# auto: the account of the round before (<output>/account), or the next one that is not at its usage limit
# (the watcher records limits in <git-common-dir>/dr-limit-<account> as the epoch of the reset).
# --follow-up: a person who is done gets a follow-up round with a new ID block. --brief <path>: a targeted
# brief (path in the repository, committed in main) that the leader reads first.
# --update-story: only update the life story with facts recorded after it was written (`lineage stale`): no
# queue, no ID block, sonnet by default; the worktree gets the marker <output>/update.
# --force: also start when a running round touches the same family (only if the brief keeps that family out
# of the round).
# Usage: lineage round start <ID> [--model opus|sonnet] [--resume] [--follow-up|--update-story]
#        [--brief <path>] [--account <name>|auto] [--force]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

USAGE="usage: lineage round start <ID> [--model opus|sonnet] [--resume] [--follow-up|--update-story] [--brief <path>] [--account <name>|auto] [--force]"
ID=${1:?$USAGE}
ID=$(upper "${ID#@}")
shift
MODEL=
RESUME=0
ACCOUNT=
FOLLOW_UP=
FORCE=
UPDATE=0
BRIEF=
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL=${2:?model missing}; shift 2;;
    --resume|--hervat) RESUME=1; shift;;
    --account) ACCOUNT=${2:?account missing}; shift 2;;
    --follow-up|--vervolg) FOLLOW_UP=--follow-up; shift;;
    --force|--forceer) FORCE=--force; shift;;
    --update-story|--bijwerk) UPDATE=1; shift;;
    --brief|--opdracht) BRIEF=${2:?path missing}; shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
[ -n "$MODEL" ] || MODEL=$([ "$UPDATE" = 1 ] && echo sonnet || echo opus)
[ "$UPDATE" = 1 ] && [ -n "$FOLLOW_UP" ] && { echo "--update-story and --follow-up exclude each other" >&2; exit 2; }
case "$MODEL" in opus|sonnet) ;; *) echo "unknown model: $MODEL (opus or sonnet)" >&2; exit 2;; esac

project_init
cd "$ROOT"
if ! check=$(lineage config check 2>&1); then
  echo "warning: lineage config check reports problems (continuing):" >&2
  echo "$check" >&2
fi
BRANCH="dr/$ID"
WT="$ROOT/.worktrees/dr-$ID"
IDL=$(lower "$ID")
NAME="dr-$IDL"

# Worktrees and their output stay out of the project's history without touching its .gitignore.
mkdir -p "$COMMON/info"
for p in .worktrees "$OUT"; do
  git check-ignore -q "$p/x" 2>/dev/null || echo "/$p/" >> "$COMMON/info/exclude"
done

ALLOWED=$(allowed_accounts)
FIRST_ALLOWED=${ALLOWED%% *}
[ -n "$ACCOUNT" ] || ACCOUNT=$([ "$RESUME" = 1 ] && echo auto || echo "$FIRST_ALLOWED")
if [ "$ACCOUNT" = auto ]; then
  previous=$(cat "$(out_dir "$WT")/account" 2>/dev/null || echo "$FIRST_ALLOWED")
  ACCOUNT=
  for acc in "$previous" $ALLOWED; do
    case " $ALLOWED " in *" $acc "*) ;; *) continue;; esac
    if ! account_on_limit "$acc"; then ACCOUNT=$acc; break; fi
  done
  if [ -z "$ACCOUNT" ]; then
    echo "all allowed accounts ($ALLOWED) are at their usage limit; first reset $(limit_reset_time)" >&2
    exit 3
  fi
fi
case " $ALLOWED " in *" $ACCOUNT "*) ;; *) echo "account $ACCOUNT is not allowed (allowed: $ALLOWED)" >&2; exit 2;; esac

load_runner

if [ "$RESUME" = 1 ]; then
  [ -d "$WT" ] || { echo "worktree $WT does not exist" >&2; exit 1; }
  runner_stop "$WT" "$NAME"
  sleep 2
else
  # Only the queue is committed here, so unstaged work of another session in main may stay.
  git diff --cached --quiet || { echo "main has staged changes" >&2; exit 1; }
  git diff --quiet -- "$QUEUE" || { echo "$QUEUE has uncommitted changes" >&2; exit 1; }
  [ -z "$BRIEF" ] || git cat-file -e "HEAD:$BRIEF" 2>/dev/null || { echo "brief $BRIEF is not committed in $MAIN_BRANCH" >&2; exit 1; }
  if [ "$UPDATE" = 1 ]; then
    git cat-file -e "HEAD:$LIFE_STORIES/$ID.md" 2>/dev/null || { echo "$ID has no life story yet; start a normal round" >&2; exit 1; }
  else
    lineage queue start "$ID" $FOLLOW_UP $FORCE
    git add "$QUEUE"
    git commit -qm "Queue: deep research $ID started${FOLLOW_UP:+ (follow-up round)}"
  fi
  git worktree add -q -b "$BRANCH" "$WT" "$MAIN_BRANCH"
fi

PERSON=$(cd "$WT" && lineage person "$ID" | sed -n 1p | sed -E 's/ \[[A-Za-z0-9]+\]$//')
[ "$UPDATE" = 1 ] && PERSON="${PERSON:-$ID} (update)"
OUTDIR="$WT/$OUT"
mkdir -p "$OUTDIR"
echo "$ACCOUNT" > "$OUTDIR/account"
echo "$MODEL" > "$OUTDIR/model"
[ -z "$BRIEF" ] || echo "$BRIEF" > "$OUTDIR/brief"
[ "$UPDATE" = 1 ] && date -Iseconds > "$OUTDIR/update"

CONTEXT="You work in this git worktree on branch $BRANCH. Read the project's $RESEARCH/project.md first (and CLAUDE.md if the project has one). Run 'lineage config value language' and write everything you produce (reports, life story, log, questions) in that language."
if [ "$UPDATE" = 1 ] || [ -f "$OUTDIR/update" ]; then
  PROMPT="Update the life story $LIFE_STORIES/$ID.md: since it was written, the tree has new data about $ID, his or her marriages or children. $CONTEXT This is not research: do not change $GEDCOM, $RESEARCH/ or the queue, do not search archives and do not start helpers. Steps: (1) 'lineage stale $ID' names the changed records and the commits; look at the changes yourself with 'git log -p --follow -- $GEDCOM' from the date of the story (shown in the output), and 'lineage person $ID'. (2) Read the report $PERSON_REPORTS/$ID.md, especially the sections of later rounds, and the life stories of the family members involved in $LIFE_STORIES/. (3) Work the new or corrected facts into the life story following the notes at the end of the deep-research skill's references/report.md: only facts with a source, no inventions, living persons not by name. A fact that is in the tree but not in the report also goes into the report, under a new heading 'Updated $(date +%Y-%m-%d)' with its source from the tree. If no change touches the story, leave the text as it is and write why in $OUT/update-result.md. (4) Commit, run 'lineage round finish' and end with DONE $ID."
elif [ "$RESUME" = 1 ]; then
  PROMPT="Use the deep-research skill for person $ID. This round was interrupted; carry on where it stopped. $CONTEXT Your ID block is listed under $ID in 'lineage queue show'. First look at 'git log --oneline $MAIN_BRANCH..HEAD', 'git status' and what is already in $PERSON_REPORTS/$ID.md and $OUT/, and do not redo finished steps. Commit per step, finish $PERSON_REPORTS/$ID.md and the life story, finish as step 7 of the skill says ('lineage round finish') and end with DONE $ID."
else
  PROMPT="Use the deep-research skill for person $ID. $CONTEXT Your ID block is listed under $ID in 'lineage queue show'. Commit per step, have search and reading work done by helper agents ('lineage round helper <role> <brief>', see 'Division of labour' in the skill), write $PERSON_REPORTS/$ID.md, finish with 'lineage round finish' and end with DONE $ID."
fi
if [ -n "$FOLLOW_UP" ]; then
  PROMPT="$PROMPT This is a follow-up round: $ID has been researched before. First read the existing report $PERSON_REPORTS/$ID.md and build on it; add your findings as a new section in that report instead of rewriting it, and update the life story only where there is something new."
fi
if [ -n "$BRIEF" ]; then
  PROMPT="$PROMPT Your main assignment is in $BRIEF; read it first and give it priority over the usual order of the skill."
fi

runner_start_leader "$WT" "$NAME" "${PERSON:-$ID}" "$MODEL" "$ACCOUNT" "$PROMPT"
STATE=started
[ "$RESUME" = 1 ] && STATE=resumed
[ "$UPDATE" = 1 ] && [ "$RESUME" = 0 ] && STATE="update round started"
echo "$ID $STATE on account $ACCOUNT ($RUNNER runner${RUNNER_TAB:+, tab $RUNNER_TAB}, agent $NAME, worktree $WT)"
