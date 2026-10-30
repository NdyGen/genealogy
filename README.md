# genealogy: deep research in your own family tree

A Claude Code plugin marketplace with one plugin, `genealogy-research`. Give it a GEDCOM file, or start from what you know, and Claude researches your ancestors one person at a time: it checks every fact against archive sources, looks beyond baptism, marriage and burial (population registers, notarial and court records, militia, newspapers), places each life in its local history, completes parents, partners and children, and writes a report and a readable life story. A research queue keeps track of who is next.

It works best for the Netherlands and Flanders, where the source guide and the archive tools are most complete (Open Archieven, Regionaal Archief Tilburg, Memorix viewers), but the method and the CLI work for any GEDCOM tree.

## Install

In Claude Code:

```
/plugin marketplace add NdyGen/genealogy
/plugin install genealogy-research@genealogy
```

Or from a shell: `claude plugin marketplace add NdyGen/genealogy` and `claude plugin install genealogy-research@genealogy`. Add `--scope project` to enable it for one project only (it is then recorded in that project's `.claude/settings.json`, for every Claude account that opens the project).

Requirements: [uv](https://docs.astral.sh/uv/getting-started/installation/) and git, on Linux or macOS. Optional: Chromium for fetching scans (`lineage doctor --install-browser`), Herdr for running several rounds in parallel, Graphviz for tree diagrams, `python3-gi` for Gramps Web sync.

The plugin brings the `lineage` CLI. Inside Claude it is on the PATH automatically. To use it in your own terminal (or from other tools), link it once: `ln -s ~/.claude/plugins/marketplaces/genealogy/plugins/genealogy-research/bin/lineage ~/.local/bin/lineage`.

## Getting started

1. **Make a folder** for the research and open Claude Code in it. Put your GEDCOM file there if you have one (an export from MyHeritage, Ancestry, Geni, Gramps or another program). No file? Start in an empty folder.
2. **Run `/genealogy-research:setup`.** It checks your machine, asks for the output language, and then:
   - with a GEDCOM: validates it and asks who the research is about (usually you);
   - without one: interviews you generation by generation (you, your parents, grandparents, great-grandparents), records every fact with where it comes from, asks which papers you have at home (family booklet, memorial cards, letters) and which relatives could tell more, and if possible looks up a first record in the archives together with you.

   It writes `lineage.toml` (the project settings), the research folder with the queue, log, questions and the project agreements, makes the first commit, and queues the first persons to research.
3. **Start the first round:** ask Claude for "deep research on I4" (any person ID from the queue), or "work through the research queue".
4. **Read the result:** a report and a life story per person in the reports folder, new open questions for you in the questions file. Answer those, and let Claude merge the round.

To add more of what you know later, just tell Claude ("add my great-grandmother: ..."); it uses `lineage add person|family|child`.

## Keep the research running

### Choosing the runner

The runner decides where research rounds run. It is `runner` in `lineage.toml`, chosen during setup:

| runner | rounds | what you start |
|---|---|---|
| `inline` | one at a time, in your own Claude session | nothing extra |
| `herdr` | several in parallel, each in its own Herdr tab | Herdr, a coordinator session and the guard |
| `headless` | several in parallel, as background `claude -p` processes | a coordinator session |
| `auto` (default) | `herdr` when Claude runs inside Herdr, otherwise `inline` | |

Change it with `lineage init --update --runner herdr` (or edit `lineage.toml`). `lineage config runner` shows which runner is used right now; `DR_RUNNER=inline lineage round start <ID>` overrides it for one command.

### inline

1. Open Claude Code in the project folder (`claude`).
2. Ask for "deep research on I4". Claude starts the round (`lineage round start I4`), moves into its worktree and does the research in the same session, with helper agents as subagents.
3. At the end Claude shows the review; after your approval it merges the round (`lineage round merge I4`). Ask for the next person when you are ready.

Nothing runs in the background, so nothing needs to be stopped.

### herdr

1. **Start Herdr** in a terminal: `herdr` (it starts or reattaches the persistent session).
2. **Open the project in a Herdr pane** and start Claude there: `cd <project> && claude`. Inside Herdr the `auto` runner becomes `herdr`.
3. **Start the coordinator** in that session: `/genealogy-research:coordinate`. The coordinator starts rounds from the queue, watches them (it runs `lineage round watch` in the background and restarts it after every notice), reviews finished rounds, merges them and fills the free places.
4. **Start the guard:** `lineage round start-guard` (from any pane in the project, or ask the coordinator). It opens its own tab "guard": a plain loop without Claude that resumes rounds stopped at a usage limit, on another account when one has room (accounts under `[accounts]` in `lineage.toml`), or after the limit resets. When no coordinator has been active for half an hour it starts one itself (`lineage round start-coordinator <account>`). It merges nothing and starts no new research. Log: `.git/dr-guard.log`; `lineage guard --once --dry-run` shows what it would do now. Starting it twice is harmless.
5. **Set the limits** if you want them, in the git directory of the project: `echo 2 > .git/dr-max-rounds` (rounds at the same time) and `echo "personal" > .git/dr-accounts` (accounts that may be used). Empty or absent means no limit and all accounts.

Each round gets a tab named after the person, with its helpers in panes next to it. To stop: end the coordinator session, and stop the guard with ctrl+c in its tab. Running rounds keep going until they finish; `lineage round undo <ID>` withdraws a round that has not done anything yet.

### headless

1. Set `runner = "headless"` in `lineage.toml`.
2. Start rounds with `lineage round start <ID>`, or ask Claude for "deep research on I4". Each round runs as a background `claude -p` process in its worktree; its process ID and log are in `.worktrees/dr-<ID>/output/leader.pid` and `leader.log` (`tail -f` to follow it).
3. For several rounds, open a Claude session in the project and run `/genealogy-research:coordinate`: it watches, reviews, merges and starts the next ones. The guard is not available without Herdr, so a round that hits a usage limit is resumed by the coordinator or by hand (`lineage round start <ID> --resume`).

Background rounds cannot answer permission prompts, so they run in auto mode. `lineage round undo <ID>` stops a round that has not done anything yet.

### Disk space

Rounds download whole registers, and a merged round keeps its scans in the sources folder, so the disk fills up over time. `lineage disk` shows free space and what can be removed. The guard checks every loop: below 20 GB free it removes the scan cache and then whole Regionaal Archief Tilburg register pages (`<fonds>-<inventory>/NNNN.jpg`) that a round merged more than 30 days ago and that no tracked file names by path, oldest first, until 40 GB is free; `lineage rat download` fetches such a page again. Crops, scans from other archives, manual scans, HTR text and provenance files are never removed. Below 5 GB no round is started or resumed, no register is downloaded, and with mail enabled the guard mails your own address once. Without the guard, run `lineage disk prune` yourself. The limits are `[disk]` in `lineage.toml`: `low_gb`, `target_gb`, `critical_gb`, `keep_days`.

Every round, with any runner, works in its own git worktree and branch (`.worktrees/dr-<ID>`, `dr/<ID>`), so nothing reaches your tree before it has been reviewed and merged.

## What is in the plugin

- **Skills:** `deep-research` (one person, start to finish), `life-book` (a book of life stories along the paternal lines of father and mother), `setup`, and `coordinate` (you start it yourself, for running several rounds in parallel).
- **Helper agents:** archive searcher, scan reader, background researcher, life-story writer.
- **The `lineage` CLI:** validation, person cards, ancestor and descendant tables, building a tree by hand, the research queue, kinship, archive search and scan download, handwriting recognition through Transkribus, request letters to archives, a Gramps Web sync, a question heat map. `lineage --help` lists everything; `lineage round ...` runs the research-round scripts.

## Privacy

Family trees contain living people. The skills never send data about living persons to external services, never open the GEDCOM for an outside model, and search archives only for people who died long ago, unless your project agreements (`research/project.md`) allow more. Credentials for optional services (mailbox, Gramps Web, Transkribus, Geneanet) stay in `~/.config/lineage/` with mode 600 and are entered with `lineage auth <service>` in your own terminal, never through the conversation. Mail is off unless a project enables it, and no mail is sent without your explicit approval of that draft.

## External services

- **Open Archieven** (openarchieven.nl): no account needed.
- **Regionaal Archief Tilburg / Memorix viewers:** public; the CLI throttles itself, because parallel downloads get an IP address blocked for hours.
- **Transkribus:** your own account and credits; the CLI refuses large batches by default.
- **Gramps Web, a mailbox, the Geneanet forum:** optional, per project.

## Development

The CLI lives in `plugins/genealogy-research/cli` (Python 3.12, uv): `uv run pytest`, `uv run ruff check`. Messages are English in the code with translations in `src/lineage/locales/<language>/`. Design notes are in `docs/`. Installed copies are cached per version: raise `version` in `plugins/genealogy-research/.claude-plugin/plugin.json` with every release, or `claude plugin update` keeps the old code.

## License

MIT, see [LICENSE](LICENSE).
