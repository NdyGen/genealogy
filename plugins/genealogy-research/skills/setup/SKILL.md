---
name: setup
description: Set up genealogy research in the current folder, or change an existing setup. Chooses the GEDCOM tree, the target persons, the output language, the runner and optional services, writes lineage.toml and the research folders, and puts the first person in the research queue.
disable-model-invocation: true
---

# Set up genealogy research

You set up a folder for genealogy research with the lineage CLI (`lineage`, on your PATH while this plugin is enabled). Ask one thing at a time with AskUserQuestion, propose a sensible default for each step, and let the user skip anything optional. Speak the user's language.

If `lineage.toml` already exists, read it first (`lineage config show`) and use its values as the defaults: the user is changing a setup, not starting over. Never overwrite research files that already exist.

## 1. Requirements

Run `lineage doctor`. It reports uv, git, Python, Playwright Chromium (only needed for `lineage scan`) and Herdr (optional). If something required is missing, give the install instruction it prints and stop. Offer to install Chromium (`lineage doctor --install-browser`) only when the user wants to fetch scans.

## 2. The tree

Find GEDCOM files in the folder (`find . -maxdepth 3 -iname '*.ged'`). Ask which one is the research tree, or for a path. If it lives elsewhere (outside the folder, or as an export next to other files), copy it to `data/tree.ged`; the copy becomes the source of truth and is edited by the research rounds, and the original is no longer used (say so, and offer to leave it out of git). Run `lineage --file <path> validate` and summarize the result. Report problems; do not fix anything without being asked.

## 3. Target persons

The research is oriented towards one or more target persons, usually the user (and partner, children). Ask for a name, run `lineage search <words>`, and let the user pick from the candidates (show ID, name, birth and death). Then offer partner and children of that person as additional targets. The youngest target whose ancestors cover the others becomes `line_root` (the direct line). Stems default to the paternal lines of the targets; mention that they can be changed later.

## 4. Output language

Default: `${user_config.language}`, otherwise the language of this conversation. This decides the language of reports, life stories, the research log and CLI messages. File names and data formats are always English.

## 5. Runner

Default: `${user_config.runner}`. With `auto`, lineage uses Herdr when it runs inside Herdr and `inline` otherwise. Explain briefly:
- `inline`: one research round per Claude session; helper agents run as subagents. Simplest, no extra software.
- `herdr`: rounds and helpers in their own Herdr tabs and panes, several rounds in parallel, a coordinator can merge them.
- `headless`: parallel rounds as background `claude -p` processes, without Herdr. Permission prompts cannot be answered there.

Ask about Claude accounts only for `herdr` or `headless`: a list of names, each with an optional `CLAUDE_CONFIG_DIR`.

## 6. Optional services

Offer each one, skipping is fine:
- Transkribus (handwriting recognition, costs the user's own credits).
- A mailbox for request letters to archives (drafts are always shown to the user before anything is sent). Mail is per project: pass `--mail` to `lineage init`, otherwise the project neither sends nor reads mail, even when the credentials exist.
- Gramps Web (publish the tree to the user's own Gramps Web server).

Passwords never go through this conversation. Ask the user to type `! lineage auth <service>` themselves; that command prompts without echo and writes `~/.config/lineage/<service>.env` with mode 600. Afterwards run `lineage auth check` and report the result.

## 7. Privacy

Ask whether the tree contains living persons (almost always yes). Write the project rules into the project agreements file (`research/project.md`): publish nothing, send no data about living persons to external services, and any exceptions the user chooses (for example: searching archives about persons who died before 1900).

## 8. Repository

Research rounds need git. If the folder is not a repository, propose `git init`. Propose a `.gitignore` for fetched scans, media and `.worktrees/`. Make the first commit only after the user agrees.

## 9. Finish

Run `lineage init` with the chosen values (it writes `lineage.toml`, `research/` with `project.md`, `queue.tsv`, `log.md`, `questions.md`, and `reports/`). Add the first target person to the queue (`lineage queue add <ID> --reason "target person"`). Then summarize in a few lines: what is set up, what was skipped, and how to start the first round (ask Claude for "deep research on <ID>").
