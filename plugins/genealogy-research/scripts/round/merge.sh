#!/usr/bin/env bash
# Merges a finished deep-research round into main and cleans up.
# An update round (<output>/update, life story only) touches neither the queue nor the tree; when the story
# stayed unchanged, the check is recorded so `lineage stale` stops reporting it.
# Usage (from main): lineage round merge <ID> [--keep]   (--keep: keep worktree, branch and tab)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

ID=${1:?usage: lineage round merge <ID> [--keep]}
ID=$(upper "${ID#@}")
KEEP=0
case "${2:-}" in --keep|--laat-staan) KEEP=1;; "") ;; *) echo "unknown option: $2" >&2; exit 2;; esac
project_init
cd "$ROOT"
load_runner
BRANCH="dr/$ID"
WT="$ROOT/.worktrees/dr-$ID"
REPORT="$PERSON_REPORTS/$ID.md"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# uv rewrites uv.lock now and then; that is never a change to keep.
restore_lock() {
  [ -f "$1/uv.lock" ] || return 0
  git -C "$1" diff --quiet -- uv.lock || { git -C "$1" checkout -- uv.lock; echo "uv.lock in $1 restored"; }
}
restore_lock "$ROOT"
restore_lock "$WT"

git diff --quiet && git diff --cached --quiet || { echo "main has uncommitted changes" >&2; exit 1; }
[ -n "$(git -C "$WT" status --porcelain 2>/dev/null)" ] && { echo "worktree $WT has uncommitted changes" >&2; exit 1; }
git -C "$WT" show "HEAD:$REPORT" >/dev/null 2>&1 || { echo "report $REPORT is missing in $BRANCH" >&2; exit 1; }
UPDATE_ROUND=0
if marker_file "$WT" update bijwerk >/dev/null; then
  UPDATE_ROUND=1
  for f in "$GEDCOM" "$QUEUE"; do
    git diff --quiet "$MAIN_BRANCH...$BRANCH" -- "$f" || { echo "update round $ID changed $f; that is not allowed, look at the branch" >&2; exit 1; }
  done
fi
BEFORE=$(git rev-parse HEAD)
[ "$UPDATE_ROUND" = 1 ] || { echo "review $ID:"; lineage review "$ID" || true; }

git merge --no-edit -q "$BRANCH" || true
# The output folder is gitignored, but leaders sometimes force-add it; identical file names across rounds then
# conflict. Main keeps its own working copies; the branch versions stay in history.
for f in $(git diff --name-only --diff-filter=U -- "$OUT"); do git checkout --ours -- "$f" 2>/dev/null || rm -f -- "$f"; done
git rm -r -q --cached --ignore-unmatch "$OUT"
# Logs, questions, queue and reports get lines appended at the end by several branches: keep both sides.
for f in $(git diff --name-only --diff-filter=U); do
  case "$f" in
    "$RESEARCH"/*|"$REPORTS"/*)
      git show ":1:$f" > "$TMP/b" 2>/dev/null || : > "$TMP/b"
      git show ":2:$f" > "$TMP/o"; git show ":3:$f" > "$TMP/t"
      git merge-file --union -p "$TMP/o" "$TMP/b" "$TMP/t" > "$f"
      git add "$f";;
    "$DATA"/coordinates.tsv|"$DATA"/coordinaten.tsv)
      # One row per place or address, sorted: keep the rows of both sides.
      git show ":1:$f" > "$TMP/b" 2>/dev/null || : > "$TMP/b"
      git show ":2:$f" > "$TMP/o"; git show ":3:$f" > "$TMP/t"
      git merge-file --union -p "$TMP/o" "$TMP/b" "$TMP/t" > "$TMP/u"
      { head -1 "$TMP/o"; tail -n +2 "$TMP/u" | grep -vP '^(place|plaats)\t' | LC_ALL=C sort -u; } > "$f"
      git add "$f";;
    "$GEDCOM")
      # Both branches appending different new records at the same spot is not a real conflict.
      lineage_py -c "import sys; from pathlib import Path; from lineage.merge import resolve_appended_file; resolve_appended_file(Path(sys.argv[1]))" "$f" || { echo "CONFLICT in $f: resolve it by hand" >&2; exit 1; }
      git add "$f";;
    *) echo "CONFLICT in $f: resolve it by hand" >&2; exit 1;;
  esac
done
git diff --cached --quiet || git commit -q --no-edit

# Two branches changing the same request leave doubled keys in its header after the union merge.
for f in $(git diff --name-only "$BEFORE" HEAD -- "$REQUESTS/*.md"); do
  case "$f" in */replies/*|*/antwoorden/*) continue;; esac
  [ -f "$f" ] || continue
  DIFF=$(lineage_py -c "import sys; from pathlib import Path; from lineage.merge import merge_request_header_file; r = merge_request_header_file(Path(sys.argv[1])); print('-' if r is None else ' '.join(r) or '+')" "$f")
  [ "$DIFF" = "-" ] && continue
  git add "$f"
  git commit -qm "Request $(basename "$f" .md): header merged after merging $ID" -- "$f"
  echo "request $(basename "$f" .md): header merged, read it again"
done

if [ "$UPDATE_ROUND" = 1 ]; then
  if git diff --quiet "$BEFORE" HEAD -- "$LIFE_STORIES/$ID.md"; then
    lineage stale --checked "$ID"
    git add "$STORIES_CHECKED"
    git commit -qm "Life story $ID reviewed: no change needed"
    echo "life story $ID unchanged; check recorded"
  else
    echo "life story $ID updated"
  fi
else
  lineage queue normalize
  lineage_py -c "from pathlib import Path; import sys; from lineage.merge import dedupe_file; r = dedupe_file(Path(sys.argv[1])); print('deduplicated:', r)" "$GEDCOM"
  lineage queue done "$ID" --report "$REPORT"
  git add -A "$QUEUE" "$GEDCOM"
  git diff --cached --quiet || git commit -qm "Deep research $ID merged: queue updated, duplicate source records removed"
  # Only projects that ask for it (a file <research>/paternal-notify) get a notice about a longer paternal line.
  if [ -f "$RESEARCH/paternal-notify" ] || [ -f "$RESEARCH/vaderlijn-melden" ]; then
    PATERNAL=$(lineage paternal --notify)
    echo "$PATERNAL"
    NOTICE=$(sed -n -e 's/^paternal line extended: draft //p' -e 's/^vaderlijn verlengd: concept //p' <<< "$PATERNAL")
    if [ -n "$NOTICE" ]; then
      git add "$NOTICE"
      git commit -qm "Notice: paternal line extended (deep research $ID)"
    fi
  fi
fi

echo "validate: $(lineage validate --level info | tail -1)"
if [ -d "$ROOT/tests" ] && [ -f "$ROOT/pyproject.toml" ]; then uv run pytest -q | tail -1; fi

# Corrections made in one record often leave the same old fact in the stories of relatives.
STALE=$(lineage stale --short | xargs)
[ -z "$STALE" ] || echo "life stories that lag behind: $STALE"
# Every so many merged rounds the coordinator turns the logged lessons into skill rules.
COUNTER=$(state_read_path dr-rounds-since-improvement dr-rondes-sinds-verbeterronde)
N=$(( $(cat "$COUNTER" 2>/dev/null || echo 0) + 1 ))
echo "$N" > "$COMMON/dr-rounds-since-improvement"
[ "$N" -lt "${DR_IMPROVE_AFTER:-${DR_VERBETER_NA:-10}}" ] || echo "time for an improvement round: $N rounds since the last one (see 'Improvement round' in the coordinate skill)"

UNTRACKED=$(git status --porcelain --untracked-files=normal | grep '^??' || true)
[ -z "$UNTRACKED" ] || { echo "warning: untracked files in main (not removed):" >&2; echo "$UNTRACKED" >&2; }

[ "$KEEP" = 1 ] && exit 0

WT_OUT=$(out_dir "$WT")
if [ "$UPDATE_ROUND" = 0 ] && [ -d "$WT_OUT" ]; then
  mkdir -p "$SOURCES/scans/dr-$ID"
  # Keep the folder layout: scans of different inventories often share a file name like 098.jpg.
  (cd "$WT_OUT" && find . -type f -print0 | while IFS= read -r -d '' f; do
    case "$(file --mime-type -b "$f")" in
      image/*|application/pdf) cp --parents --update=none "$f" "$ROOT/$SOURCES/scans/dr-$ID/" || exit 1;;
    esac
  done) || {
    # A failed copy (full disk) leaves a truncated file that --update=none would keep; the worktree has the original.
    echo "scans not fully copied to $SOURCES/scans/dr-$ID; worktree stays. Make room, remove the half-copied folder and run again." >&2
    exit 1
  }
fi
runner_stop "$WT" "dr-$(lower "$ID")"
git worktree remove --force "$WT"
git branch -d "$BRANCH" >/dev/null
# Claude Code keeps a temp dir per working directory (path with / and . as -) that outlives the worktree;
# on a per-user /tmp quota these add up to gigabytes, so drop those of every worktree that is gone.
TMPBASE=${CLAUDE_CODE_TMPDIR:-/tmp/claude-$(id -u)}
PREFIX=$(echo "$ROOT/.worktrees/dr-" | tr '/.' '--')
for d in "$TMPBASE/$PREFIX"*; do
  [ -d "$d" ] || continue
  [ -d "$ROOT/.worktrees/dr-${d##*/"$PREFIX"}" ] || rm -rf -- "$d"
done
echo "$ID $([ "$UPDATE_ROUND" = 1 ] && echo "update round ")merged and cleaned up"
