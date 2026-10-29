# Research rounds: scripts, runners and names

Binding design for Fase 4 and 5. The scripts, the skills and the agents follow this; deviations go here first.

## Layout in the plugin

```
plugins/genealogy-research/
  .claude-plugin/plugin.json
  bin/lineage                      # wrapper: `lineage round ...` runs scripts/round/, everything else the CLI
  hooks/hooks.json, hooks/session-start.sh
  cli/                             # the Python CLI
  scripts/round/
    runner.sh                      # sourced: picks the runner, loads runner-<name>.sh, common helpers
    runner-herdr.sh  runner-headless.sh  runner-inline.sh
    start.sh  helper.sh  finish.sh  merge.sh  undo.sh  watch.sh  start-guard.sh  start-coordinator.sh
  skills/deep-research/            # SKILL.md, references/{report.md, sources-nl.md, lessons.md}, evals/
  skills/coordinate/               # SKILL.md (was references/coordinatie.md); user-invoked only
  skills/life-book/                # was levensboek; scripts/pdf.py
  skills/setup/
  agents/dr-archive-searcher.md  dr-scan-reader.md  dr-background.md  dr-life-story.md
```

One plugin. The planned separate `genealogy-coordination` plugin is dropped: coordination is a skill with
`disable-model-invocation: true`, and its scripts need the same runner library.

Scripts are reached through the wrapper, never by path: `lineage round <command> [args]` execs
`scripts/round/<command>.sh`. That works from skills, agents, the guard and the user's shell alike, because
the plugin's `bin/` is on the Bash tool's PATH. In a development checkout `plugins/genealogy-research/bin`
can be put on PATH by hand.

## Commands (old -> new)

| old (ndygen) | new |
|---|---|
| `.claude/skills/deep-research/scripts/start-onderzoek.sh <ID> [--model] [--hervat] [--vervolg] [--bijwerk] [--opdracht <pad>] [--account] [--forceer]` | `lineage round start <ID> [--model opus\|sonnet] [--resume] [--follow-up] [--update-story] [--brief <path>] [--account <name>\|auto] [--force]` |
| `hulp.sh <rol> <pad/NN-iets.opdracht.md>` | `lineage round helper <role> <path/NN-name.brief.md>`; result `NN-name.md`, failure `NN-name.error.txt` |
| roles `archiefzoeker scanlezer achtergrond levensverhaal` | `archive-searcher scan-reader background life-story` (agents `dr-<role>`) |
| `afronden.sh` | `lineage round finish` |
| `samenvoegen.sh <ID> [--laat-staan]` | `lineage round merge <ID> [--keep]` |
| `terugzetten.sh <ID>` | `lineage round undo <ID>` |
| `wacht.sh [interval]` | `lineage round watch [interval]` |
| `start-bewaker.sh` | `lineage round start-guard` |
| `start-coordinator.sh <account>` | `lineage round start-coordinator <account>` |
| `uv run ndygen <cmd>` | `lineage <cmd>` (see docs/renames.md for every subcommand and option) |
| final words `KLAAR <ID>` / `HULP KLAAR` | `DONE <ID>` / `HELPER DONE` |

Exit codes stay: 0 ok, 1 failed, 2 wrong use, 3 all accounts at their limit, 4 (helper) runner has no
helper panes: use the Agent tool.

## Files in a worktree's output folder

The output folder is `lineage config path output --relative` (default `output`, ndygen `uitvoer`).

| old | new |
|---|---|
| `KLAAR` | `DONE` |
| `bijwerk` | `update` |
| `bijwerk-resultaat.md` | `update-result.md` |
| `account`, `model` | same |
| `opdracht` | `brief` |
| `herdr-tab` | `runner-tab` (herdr), `leader.pid` + `leader.log` (headless) |

Readers (guard.py, review.py, watch.sh) accept the old names too, for worktrees started before the switch.
State in the git common dir keeps its names (`dr-accounts`, `dr-max-rondes` -> read both `dr-max-rounds`
and `dr-max-rondes`, `dr-limiet-<acc>` -> `dr-limit-<acc>` with fallback, `dr-wacht.*` -> `dr-watch.*`).

## Project paths in scripts

Scripts never hard-code project paths. At the top:

```bash
ROOT=$(git rev-parse --show-toplevel)          # from the working directory, not the script dir
GEDCOM=$(lineage config path gedcom --relative)
QUEUE=$(lineage config path queue --relative)
OUT=$(lineage config path output --relative)
```

`start` refuses with a clear message when `lineage.toml` is missing (`lineage config check` fails) or the
directory is not a git repository.

New CLI commands for the scripts:
- `lineage config path <key> --relative`: path below the project root.
- `lineage config value <key>`: one scalar setting (`language`, `runner`, `name`, `line_root`).
- `lineage config runner`: the runner to use: `DR_RUNNER`, else `runner` in lineage.toml, else `auto`
  resolved to `herdr` when `HERDR_ENV=1` and `herdr` is on PATH, else `inline`.
- `lineage config accounts`: one line per account, `name<TAB>config_dir` (config_dir empty for the
  default). Without `[accounts]` a single line `default<TAB>`.

## Runner interface (scripts/round/runner.sh)

`runner.sh` sets `RUNNER=$(lineage config runner)` and sources `runner-$RUNNER.sh`. Each implements:

| function | herdr | headless | inline |
|---|---|---|---|
| `runner_start_leader <wt> <name> <label> <model> <account> <prompt>` | own tab labelled `<label>`, pane `<name>`, `herdr agent start ... --model --permission-mode auto`, prompt resent up to 3x | `setsid claude -p <prompt> --model <model> --permission-mode auto --output-format stream-json --verbose` in `<wt>`, pid and log in `<wt>/<OUT>/leader.{pid,log}` | prints "open Claude in <wt> and say: <prompt>"; returns 0 |
| `runner_start_helper <wt> <name> <agent> <prompt> <result>` (blocks until done) | pane next to the leader, limits `DR_MAX_AGENTS`/`DR_MAX_HULP`, refuse a permission prompt once, timeout `DR_HULP_MAX_MIN` | `claude -p --agent <agent> --permission-mode auto <prompt>` in the foreground with timeout | `return 4` |
| `runner_list` | `name<TAB>status` for every agent | the leaders of `.worktrees/dr-*` from their pid files | nothing |
| `runner_screen <name>` | `herdr agent read --source visible` | tail of the leader log | nothing |
| `runner_stop <wt> <name>` | ctrl+c, close the tab (and the old shared-tab panes) | kill the process group | nothing |
| `runner_prompt <name> <text>` | `herdr agent prompt` | not supported (return 2) | not supported |

Status values: `working idle blocked done gone`. The account's `config_dir` is exported as
`CLAUDE_CONFIG_DIR` for the leader (unset for the default account) and inherited by helpers.

Agent names: the plugin namespaces agents, so `helper.sh` passes `--agent genealogy-research:dr-<role>`
when the agent file is not in the project's own `.claude/agents/` (a project may override a role there).
The inline fallback message names the same `subagent_type`.

## What stays out of the plugin skills

Project facts (target persons, Gramps Web, Geneanet, mailbox, accounts, the user's decisions, lessons tied to
person IDs) go to the project: `<research>/project.md` and `<research>/lessons.md`. The skill reads both
when they exist.

## Language

Skills and agents are written in English. They tell the agent to read `lineage config value language` and
to write reports, life stories, the log, questions and request letters in that language. Dutch archive terms
(ondertrouw, schepenprotocol, kohier, DTB, ...) stay with a short English explanation.
