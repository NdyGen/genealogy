#!/usr/bin/env bash
# Prepares the CLI in the background and tells Claude when this folder looks like a family tree
# without a lineage setup, once per folder.
set -uo pipefail
ROOT=${CLAUDE_PLUGIN_ROOT:?}
DATA=${CLAUDE_PLUGIN_DATA:?}
PROJECT=${CLAUDE_PROJECT_DIR:-$PWD}
mkdir -p "$DATA/seen"

notes=()
command -v uv >/dev/null || notes+=("uv is not installed; the lineage CLI cannot run until it is (https://docs.astral.sh/uv/getting-started/installation/).")
command -v git >/dev/null || notes+=("git is not installed; research rounds need it.")

if command -v uv >/dev/null && ! cmp -s "$ROOT/cli/uv.lock" "$DATA/uv.lock"; then
  ( LINEAGE_VENV="$DATA/venv" "$ROOT/bin/lineage" --help >/dev/null 2>&1 && cp "$ROOT/cli/uv.lock" "$DATA/uv.lock" ) </dev/null >/dev/null 2>&1 &
  disown
fi

seen="$DATA/seen/$(printf '%s' "$PROJECT" | { sha1sum 2>/dev/null || shasum; } | cut -c1-16)"
if [ ! -e "$PROJECT/lineage.toml" ] && [ ! -e "$seen" ] \
  && find "$PROJECT" -maxdepth 2 -iname '*.ged' -print -quit 2>/dev/null | grep -q .; then
  notes+=("This folder contains a GEDCOM file but no lineage.toml. Offer the user /genealogy-research:setup to set up genealogy research here.")
  : > "$seen"
fi

[ ${#notes[@]} -eq 0 ] && exit 0
python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(sys.argv[1:])}}))' "${notes[@]}"
