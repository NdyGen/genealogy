#!/usr/bin/env bash
# Starts (or restarts) a coordinator: a Claude session named "coordinator" in the folder of main, started by
# the runner (herdr: its own tab; hc: a terminal in the space of the session that starts it). The guard
# (`lineage guard --coordinator`) calls this when no session coordinates (the watcher's heartbeat has been
# silent for half an hour) or when the coordinator is at a usage limit. Starting unattended in auto mode is a decision of the project owner.
# Usage: lineage round start-coordinator <account>
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"

ACCOUNT=${1:?usage: lineage round start-coordinator <account>}
project_init
MAIN=$(dirname "$COMMON")
cd "$MAIN"
account_table | awk -F'\t' '{print $1}' | grep -qx "$ACCOUNT" || { echo "unknown account: $ACCOUNT" >&2; exit 2; }
load_runner

# The coordinate skill is user-invoked only, so it is loaded as a slash command with this text as its arguments.
PROMPT="/genealogy-research:coordinate You are the coordinator of the deep-research rounds in this repository (the folder of main), started by the guard because no other session was coordinating. Follow the rules of this skill; read the project's $RESEARCH/project.md and CLAUDE.md if it exists. First see what is open: git log --oneline -15, lineage queue show, the worktrees in .worktrees/ (<output>/DONE = ready for review), tail -30 on the guard log in the git common dir (dr-guard.log) and lineage requests. Then start 'lineage round watch' in the background and restart it after every notice. Review every finished round as the skill says under 'Reviewing and merging' (have a subagent with model sonnet do the review) and merge with 'lineage round merge'; keep as many rounds running as the skill allows (the maximum is in <git-common-dir>/dr-max-rounds, the allowed accounts in dr-accounts) with 'lineage round start', direct line first, and start a new one only when a place is free. The guard handles usage limits: do not switch accounts yourself. Never send a mail: drafts wait for the user's explicit approval. Decisions that belong to the user go in $RESEARCH/questions.md and are reported at the end of your turn."
RUNNER_WHERE=
runner_start_coordinator "$MAIN" "$ACCOUNT" "$PROMPT"
echo "coordinator started on $ACCOUNT ($RUNNER runner${RUNNER_WHERE:+, $RUNNER_WHERE})"
