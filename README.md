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

How rounds run is set by `runner` in `lineage.toml`:

- **`inline` (the default without Herdr):** one round at a time, in the session where you ask for it; helper agents run as subagents. When the round is finished Claude shows the review and, with your approval, merges it (`lineage round merge <ID>`). Ask for the next person when you are ready. Nothing runs in the background.
- **`herdr`:** rounds run in parallel, each in its own Herdr tab with its helpers in panes next to it. This needs two more things running, both started from the main checkout of the project inside Herdr:
  - **The coordinator**, a Claude session that starts rounds, watches them, reviews and merges finished ones, and fills free places from the queue. Start a Claude session in the project and run `/genealogy-research:coordinate`. It starts its own watcher (`lineage round watch` in the background) and restarts it after every notice.
  - **The guard** (`lineage round start-guard`), a plain loop without Claude in its own tab. It resumes rounds that stopped at a usage limit, on another account when one has room (accounts are listed under `[accounts]` in `lineage.toml`), or waits until a limit resets. It also keeps a coordinator alive: when no coordinator session has been active for half an hour, it starts one itself (`lineage round start-coordinator <account>`). It merges nothing and starts no new research. Log: `.git/dr-guard.log`; `lineage guard --once --dry-run` shows what it would do now.

  How many rounds run at once and on which accounts is in two files in the git directory: `.git/dr-max-rounds` (a number) and `.git/dr-accounts` (account names). Empty or absent means no limit and all accounts.
- **`headless`:** parallel rounds as background `claude -p` processes, without Herdr. The coordinator works the same way; permission prompts cannot be answered in the background, so rounds run in auto mode.

Every round works in its own git worktree and branch (`.worktrees/dr-<ID>`, `dr/<ID>`), so nothing reaches your tree before it has been reviewed and merged. `lineage round undo <ID>` withdraws a round that has not done anything yet.

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

The CLI lives in `plugins/genealogy-research/cli` (Python 3.12, uv): `uv run pytest`, `uv run ruff check`. Messages are English in the code with translations in `src/lineage/locales/<language>/`. Design notes are in `docs/`.

## License

MIT, see [LICENSE](LICENSE).
