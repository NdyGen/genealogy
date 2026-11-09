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
    runner-hc.sh  runner-herdr.sh  runner-headless.sh  runner-inline.sh
    start.sh  helper.sh  finish.sh  tell.sh  merge.sh  stats.sh  undo.sh  watch.sh  start-guard.sh  start-coordinator.sh
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
| `herdr-tab` | `runner-tab` (herdr), `leader.pid` + `leader.log` (headless); hc keeps no marker, it finds a round by its labels |

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
  resolved to `hc` when `HC_TERMINAL_ID` is set (a herdr-core terminal, as in the Herdr app) and `hc` is on
  PATH, else `herdr` when `HERDR_ENV=1` and `herdr` is on PATH, else `inline`.
- `lineage config accounts`: one line per account, `name<TAB>config_dir` (config_dir empty for the
  default). Without `[accounts]` a single line `default<TAB>`.

## Telling the starting session (`<output>/caller`)

`round start` run from an hc terminal writes that terminal's address (`HC_TERMINAL_ID`) to `<output>/caller`.
When the round has DONE and nobody coordinates (no `coordinator` terminal, no live session with a fresh
heartbeat), the guard types one notice into that terminal: the round waits for review and merge. It only
does so while the terminal still runs Claude in the project's main folder (a shell would run the text) and
waits for input; a busy session is tried again on the next check. `<output>/caller-told` records that it was
told, or that the terminal is gone; `round start` (a resume) and `round tell` remove it, so the next DONE is
announced again. herdr has no such notice.

## Talking to a lead (`lineage round tell`)

Agents work through files: a brief and a result file between lead and helper, `<output>/DONE` and the branch
between lead and coordinator. The one way back is `lineage round tell <ID> <text>` (or `--file <path>`), for
what the coordinator's review finds. A running lead (`runner_prompt`: `hc send`, `herdr agent prompt`) gets
the text typed in. After `round finish` the lead's terminal is gone: `lineage leader-session <ID>` finds the
last leader session in the worktree (not a helper's, which work in the same folder) and `tell` resumes it
(`claude --resume <id>`) with the message as its next prompt, on that session's account, so the lead keeps the
round's context. The account must be in `dr-accounts` and not at its limit. `tell` removes DONE, so the
coordinator waits for the new finish. The hc and headless runners resume; herdr cannot, inline prints the
command.

## Cost per round (`lineage stats`)

`round merge` writes one row per round to the stats file (`lineage config path stats`, default
`research/stats.tsv`) with `lineage stats record`. `lineage round stats <ID>` (or `lineage stats show <ID>`)
shows one round, before the merge computed from its branch; `lineage stats` summarises all rows (median and
mean cost per ancestor, cost per fact, by kind, century and region, and the share of leader, helpers and
review). `lineage stats backfill` adds every merged round from git and the transcripts that still exist.

Where the numbers come from:

- **Rounds**: a merge commit `Merge branch 'dr/<ID>'`, or after a fast-forward the commit
  `Deep research <ID> merged` that follows the branch's commits. The round runs from its fork point (the
  start commit) to the merge. Kind: `follow-up` from the start commit, `update` when the branch touched
  neither tree nor queue, else `normal`.
- **Tokens**: the Claude Code transcripts of the worktree (`<config_dir>/projects/<path with every
  non-alphanumeric as ->`) on every account, between fork and merge. A session that starts with "Read the
  brief" or is an Agent-tool sub-agent counts as a helper, the rest as the leader. Usage is counted once
  per message id (Claude Code writes a line per content block). The coordinator's review is its turns
  (and its sub-agents') in the main checkout from the first command that names the round after the
  round's own sessions stopped (not its last commit: corrections after the review land on the branch) up to `round merge <ID>` (without a merge call in the transcripts, as from a
  background task, up to the last command naming the round before the merge); overlapping review windows
  split the cost evenly. A round counts as measured only when its own worktree sessions were found.
- **Active time**: the union over all sessions of the stretches between lines at most ten minutes apart;
  waiting on a limit does not count.
- **Review time**: `review_min` is the active time of the coordinator's sessions (with sub-agents) inside
  the review windows above; `review_wait_min` the wall-clock time from the round's last own turn to the
  merge, waiting included. Issue #2 asks for a routine round reviewed in under 15 minutes.
- **Cost**: API list prices in EUR (`[prices]` in `lineage.toml` overrides a model or `usd_eur`), and the
  subscription share `api_eur / monthly_budget_eur x subscription_eur` per account. `lineage stats
  calibrate [--write]` sets `monthly_budget_eur`: the API-equivalent use of the account (all projects) in
  the week before a weekly-limit hit, scaled to a month (median over such weeks). `subscription_eur`, the
  monthly price, is set by hand.
- **Yield**: the GEDCOM diff between fork and tip (events added, changed, removed; persons, families,
  citations) and the IDs added to the queue.
- **Archives**: `<output>/metrics.jsonl` in the worktree, appended by `lineage` itself for every Open
  Archieven, RAT, web and browser request made inside a round's worktree; scans counted in the output
  folder (after the merge in the sources folder); Transkribus credits from the HTR log by the `dr-<ID>/`
  in the image path. Only rounds since the counters exist have archive numbers.
- Opencode rounds get a row with yield and empty token columns.
- **Verification**: the `verify_*` columns count the outcomes of `lineage verify` per citation at the
  merge (see below). A backfill keeps the counts the merge recorded and leaves them empty for older rounds.

## Verification (`lineage verify`)

`lineage verify <ID>` takes the facts (events, NAME, FAMC) that `dr/<ID>` added or changed against its
merge base, resolves each citation's `PAGE` and compares the record with the fact. `round finish` and
`round merge` run it; `--all` checks every cited fact in the tree, `--tsv` writes one line per citation.

- **References**: an Open Archieven record URL (fetched with `archive.show`, cached in
  `~/.cache/lineage/openarch`), a Delpher article URN (its OCR text, cached in `~/.cache/lineage/delpher`),
  a scan (`RAT <fonds> ... inv. <n> ... scan <n>`, `scan: <file>`, `transkribus: <file>`, or `inv. <n> ... scan(s) <n>` with the fonds in the source record), any other URL,
  else unresolvable.
- **Open Archieven**: the person is found among the record's persons by name (given names folded to their
  Latin form, surname prefixes ignored, or as the partner of a named spouse). Same event (birth record for
  BIRT): the date must match, a mismatch over ten days is a contradiction, under ten days (burial registers
  index the day of notice) partly; the place differing is partly. Neighbouring event (baptism for BIRT,
  burial for DEAT): the date must fall in a window. Otherwise birth date or age, occupation and residence
  of the record person. FAMC: the child and each parent in a parent role.
- **Delpher**: surname, given name and year in the OCR text; never a contradiction.
- **Scans**: no comparison, but the citation or the fact's NOTE needs the marker `reread by lead`
  (`nagelezen door leider`; the older wording `zelf gelezen` and `eigen lezing` counts too).
- **Parent links**: for every new FAMC, cited or not (not when a citation has QUAY 1), the Open Archieven records cited
  anywhere at the child are sorted into records naming the child and a parent (one per event and date, so
  two indexes of one baptism count once) and other records naming the child. Independent: two such
  records, or one and another record whose age, birth date or birthplace fits the child's birth (from the
  tree, else from that baptism). Single: one record and nothing else about the child. Weak (ERROR): one
  record while other records of the child confirm nothing. Name, patronymic and place are not a feature.
- **Years in words**: `"<words>" = <year>` in the helpers' result files (`<output>/helpers/`) and the
  report is recomputed (`yearwords.py`: early modern Dutch and Latin); another year is a WARNING.
- **Severity**: a fact is proven when a citation has QUAY 3. ERROR: a QUAY 3 citation contradicted, or no
  QUAY 3 citation that resolves. WARNING: partly supported, a contradiction on a lower QUAY, a scan
  without the marker. Exit status 1 on an ERROR only with `--strict` or `[verify] strict = true`; then
  `round finish` refuses. Measured before turning it on (#2): of 26 contradictions in a whole-tree sweep 24
  were false alarms and of a sample of weak links 13 of 15, all since fixed; the last 30 merged rounds of
  that tree give 0 ERRORs. A lead who finds an index wrong lowers that citation to QUAY 2 with a NOTE.
- **Sample** (`lineage review <ID> --sample N`, `sample.py`): N of the round's cited records (Open
  Archieven, Delpher, scans), one per record, printed next to the facts that cite them: tree on the left,
  record on the right, the verify outcome below. Weighted: a new parent link (the child's baptism or birth
  record for an uncited FAMC) or a correction (a fact that stood with another date, place or value) +3, a
  contradicted or partly supported citation +2, on a base of 1. The seed is the ID and the merge base, so
  the coordinator and the review agent see the same records. A scan shows the lead's reading from the
  citation and fact NOTEs; the scan itself still has to be opened.

## Gold-standard evaluation (`lineage gold`)

A project keeps a gold set: 10 to 20 persons whose facts and parents were checked against scans, in TOML
(format and a fictional example in `skills/deep-research/evals/fixture/gold.toml`). Per person: `tags`
(the gold is complete for those event tags), `facts` (tag, date, place, source) and `parents` (role, name,
birth year).

- `lineage gold exam <gold> --out exam.ged`: the tree without the gold persons' facts of those tags and,
  where the gold names parents, without the parent link (FAMC and the family's CHIL). Encoding and line
  endings stay. A round on a copy of the project with this tree has to find them again.
- `lineage gold score <gold> [--tree round.ged] [--transcripts <logs>]`: per gold fact right (same date
  to the gold's precision, place not different), vague (consistent but less precise, or a range), wrong,
  or missing; a fact of a gold tag that the gold does not have is wrong. Precision is right / (right +
  wrong), recall right / gold. Parent links: the tree's parent must match the gold name (given name and
  surname) and birth year within two years. Calibration: per QUAY, how many scored facts and links held.
  Living persons: tool calls in the round's session logs that send the name of a possibly living person
  to an outside service (WebSearch, WebFetch, MCP tools, `lineage archive|rat|scan|htr|forum|mail`,
  `curl`, `wget`); a name a deceased person also bears is skipped, local commands are not counted.
  Exit 1 on any such lookup, or with `--minimum` when a precision or recall is below it. `--json` for
  the numbers.

## Runner interface (scripts/round/runner.sh)

`runner.sh` sets `RUNNER=$(lineage config runner)` and sources `runner-$RUNNER.sh`. Each implements:

| function | hc | herdr | headless | inline |
|---|---|---|---|---|
| `runner_start_leader <wt> <name> <label> <model> <account> <prompt>` | terminal `<name>` in `<wt>`: `claude --model --permission-mode auto <prompt>` (the brief is claude's first prompt), trust dialog answered once | own tab labelled `<label>`, pane `<name>`, `herdr agent start ... --model --permission-mode auto`, prompt resent up to 3x | `setsid claude -p <prompt> --model <model> --permission-mode auto --output-format stream-json --verbose` in `<wt>`, pid and log in `<wt>/<OUT>/leader.{pid,log}` | prints "open Claude in <wt> and say: <prompt>"; returns 0 |
| `runner_start_helper <wt> <name> <agent> <prompt> <result>` (blocks until done) | child terminal of the leader (`--parent $HC_TERMINAL_ID --no-notify`), same limits, refusal and timeout as herdr; `hc wait` instead of polling | pane next to the leader, limits `DR_MAX_AGENTS`/`DR_MAX_HELPERS`, refuse a permission prompt once, timeout `DR_HELPER_MAX_MIN` | `claude -p --agent <agent> --permission-mode auto <prompt>` in the foreground with timeout | `return 4` |
| `runner_list` | `name<TAB>status` for the project's live terminals | `name<TAB>status` for every agent | the leaders of `.worktrees/dr-*` from their pid files | nothing |
| `runner_screen <name>` | `hc read` (the visible screen) | `herdr agent read --source visible` | tail of the leader log | nothing |
| `runner_stop <wt> <name>` | `hc kill` + `hc rm` of every terminal of the round, finished ones included | ctrl+c, close the tab (and the old shared-tab panes) | kill the process group | nothing |
| `runner_prompt <name> <text>` | `hc send` | `herdr agent prompt` | not supported (return 2) | not supported |
| `runner_after_finish <wt> <name>` | helpers closed now, the leader 30 s later | helpers closed now, the tab 30 s later | nothing | nothing |
| `runner_start_coordinator <main> <account> <prompt>` | terminal `coordinator` | tab `coordinator`, its id in `<git-common-dir>/dr-coordinator.tab` | return 2 | return 2 |
| `runner_start_guard <main> <command...>` | terminal `guard` (`DR_RUNNER=hc`) | tab `guard` | return 2 | return 2 |
| `runner_guard_alive` (optional) | the terminal `guard` lives | not defined | not defined | not defined |
| `runner_stop_guard` (optional) | closes the terminal `guard` | not defined | not defined | not defined |
| `runner_cron_env` (optional, enables `start-guard --cron`) | `DR_RUNNER=hc` and `DR_HC_SPACE=<space of the caller>` | not defined | not defined | not defined |

Status values: `working idle blocked done gone`. hc reports `idle working done blocked error` itself (OSC 7501);
no status yet counts as `working` (booting), `error` as `idle` (the turn ended; the guard reads the screen
for a usage limit), a finished terminal as `gone`.

### hc (herdr-core, the Herdr app)

hc starts programs in the core's environment, not the caller's: the runner passes `PATH` and the account
(`CLAUDE_CONFIG_DIR`, or `-u CLAUDE_CONFIG_DIR`; always `-u ANTHROPIC_MODEL`) through `env(1)`.

hc names are unique among all live terminals of the user, across projects. Every terminal the runner starts
carries `lineage.project=<git common dir>` and `lineage.role=leader|helper|coordinator|guard`, rounds also
`lineage.round=<ID>`; every lookup filters on the project first. Two projects that run rounds at the same
time still cannot both have a terminal `coordinator` or `guard`.

Placement in the app, chosen over making the round a sub-agent of the coordinator:
- Leaders, the coordinator and the guard have no hc parent (`--no-parent`). A child ends with its parent,
  and the guard restarts coordinators (usage limit, another session took over), which would end every round
  with it; `--outlive-parent` would leave a dangling parent and hc would type notes about every round into
  the coordinator's prompt. Instead they copy only the `herdr.space` label of the terminal that starts
  them: without `herdr.tab` the app opens a new tab, so each round, the coordinator and the guard get their
  own tab in the coordinator's space, as under herdr. The guard copies the space from the coordinator when
  it is started and passes it on to rounds it resumes. Run from cron (`start-guard --cron`) there is no starting terminal: the crontab line carries
  `DR_HC_SPACE`, the space `start-guard --cron` was run from, and `DR_RUNNER=hc`, since `auto` would fall back to
  `inline` outside a terminal. A space that is no longer in the app's layout (removed or reorganised since)
  would hide the new tab, so then the runner takes the space where the app shows a live terminal of the
  project, or leaves the choice to the app. The app keeps its layout in the hc document
  `herdr-app` (spaces, their tabs and the terminals in them) and numbers a tab without a name, so the runner
  names the new tab there (`doc.set`, retried on a version conflict): `<ID> <person>` for a round,
  `coordinator` and `guard`. A tab someone already named keeps its name.
- A helper is a child of its leader (`--parent $HC_TERMINAL_ID --no-notify`): it shows as the leader's
  sub-agent, ends when the leader is stopped, and hc types no notes into the leader while `helper.sh` already
  waits for it. The app lays out only terminals without a parent, so the runner adds the helper as a pane to
  its leader's tab in `herdr-app` and takes it out again when it closes the helper (never emptying a tab).

The guard (`lineage guard --runner hc`, default from `lineage config runner`) uses the same labels. A
`lineage round watch` heartbeat is keyed by `HC_TERMINAL_ID` (falling back to `HERDR_PANE_ID`), with `:` and
`/` written as `_`. The account's `config_dir` is exported as
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
