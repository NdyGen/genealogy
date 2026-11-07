#!/usr/bin/env bash
# Cost and yield of one round: tokens, EUR, active time, archive requests, scans, credits and what it added
# to the tree. Before the merge from the branch, after it from the stats file.
# Usage: lineage round stats <ID> [--live]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runner.sh"
project_init
lineage stats show "$@"
