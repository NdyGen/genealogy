# Inline runner (source, do not run): the user opens Claude in the worktree. No leader process, no helper
# panes; helpers are spawned by the leader with the Agent tool.

runner_start_leader() {
  local wt=$1 name=$2 label=$3 model=$4 account=$5 prompt=$6 dir
  dir=$(account_dir "$account")
  dir=${dir/#\~/$HOME}
  echo
  echo "Open Claude in $wt${dir:+ (CLAUDE_CONFIG_DIR=$dir)}, model $model, and say:"
  echo
  echo "$prompt"
  echo
  RUNNER_TAB=
  return 0
}

runner_start_helper() { return 4; }
runner_list() { return 0; }
runner_screen() { return 0; }
runner_prompt() { return 2; }
runner_stop() { return 0; }
runner_after_finish() { return 0; }
