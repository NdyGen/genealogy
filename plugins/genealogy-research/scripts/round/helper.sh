#!/usr/bin/env bash
# Has a helper agent (cheaper model) carry out one brief, in a pane next to the round's leader (herdr) or in
# the foreground (headless). Waits until it is done, closes the pane and prints the result path.
# Usage: lineage round helper <role> <path/NN-name.brief.md>
#   role: archive-searcher | scan-reader | background | life-story  (agent dr-<role>, from the plugin or from
#         the project's own .claude/agents/dr-<role>.md, which wins)
#   result: the same path without ".brief" (NN-name.md); on failure NN-name.error.txt with the last screen.
# Exit 0 = result is ready, 1 = failed (see .error.txt), 2 = wrong use, 4 = this runner has no helper panes:
# use the Agent tool with subagent_type genealogy-research:dr-<role> and the contents of the brief.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

USAGE="usage: lineage round helper <role> <brief-file>"
ROLE=${1:?$USAGE}
BRIEF=$(abs_path "${2:?$USAGE}")
case "$BRIEF" in
  *.brief.md) RESULT="${BRIEF%.brief.md}.md";;
  *.opdracht.md) RESULT="${BRIEF%.opdracht.md}.md";;
  *) echo "the brief file must end in .brief.md" >&2; exit 2;;
esac
[ -s "$BRIEF" ] || { echo "brief $BRIEF is empty or missing" >&2; exit 2; }
case "$ROLE" in
  archive-searcher) SHORT=search;;
  scan-reader) SHORT=scan;;
  background) SHORT=back;;
  life-story) SHORT=story;;
  # Dutch role names of worktrees started before the switch
  archiefzoeker) ROLE=archive-searcher; SHORT=search;;
  scanlezer) ROLE=scan-reader; SHORT=scan;;
  achtergrond) ROLE=background; SHORT=back;;
  levensverhaal) ROLE=life-story; SHORT=story;;
  *) echo "unknown role $ROLE (archive-searcher, scan-reader, background, life-story)" >&2; exit 2;;
esac
WT=$(git -C "$(dirname "$BRIEF")" rev-parse --show-toplevel)
cd "$WT"
project_init
ERROR="${RESULT%.md}.error.txt"
rm -f "$RESULT" "$ERROR" "${RESULT%.md}.fout.txt"

AGENT="genealogy-research:dr-$ROLE"
[ ! -f "$WT/.claude/agents/dr-$ROLE.md" ] || AGENT="dr-$ROLE"

load_runner
BRANCH=$(git -C "$WT" rev-parse --abbrev-ref HEAD)
ID=${BRANCH#dr/}
NR=$(basename "$BRIEF" | grep -oE '^[0-9]+' || echo $$)
NAME="$(lower "$ID")-$SHORT-$NR"
PROMPT="Read the brief in $BRIEF and carry it out according to your role. Write your result to $RESULT. Commit nothing. End with HELPER DONE."

if [ "$RUNNER" = inline ]; then
  echo "no helper panes in this runner: use the Agent tool with subagent_type $AGENT and the contents of $BRIEF" >&2
  exit 4
fi
# In a subshell with errexit, so a failing herdr call stops the helper as it did before; `fn || exit` would
# switch errexit off inside the function.
set +e
(set -e; runner_start_helper "$WT" "$NAME" "$AGENT" "$PROMPT" "$RESULT")
rc=$?
set -e
[ "$rc" = 0 ] || exit "$rc"
echo "$RESULT"
