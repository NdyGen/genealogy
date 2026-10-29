# genealogy: deep research in your own family tree

A Claude Code plugin marketplace with one plugin, `genealogy-research`. Point it at a GEDCOM file and Claude researches your ancestors one person at a time: it checks every fact against archive sources, looks beyond baptism, marriage and burial (population registers, notarial and court records, militia, newspapers), places each life in its local history, completes parents, partners and children, and writes a report and a readable life story. A research queue keeps track of who is next.

It works best for the Netherlands and Flanders, where the source guide and the archive tools are most complete (Open Archieven, Regionaal Archief Tilburg, Memorix viewers), but the method and the CLI work for any GEDCOM tree.

## Install

```
/plugin marketplace add NdyGen/genealogy
/plugin install genealogy-research@genealogy
```

Requirements: [uv](https://docs.astral.sh/uv/getting-started/installation/) and git. Optional: Chromium for fetching scans (`lineage doctor --install-browser`), Herdr for parallel rounds in panes, Graphviz for tree diagrams, `python3-gi` for Gramps Web sync.

## First steps

1. Open Claude Code in a folder with your GEDCOM file (or an empty folder) and run `/genealogy-research:setup`. It checks your machine, picks the tree and your target persons, sets the output language and writes `lineage.toml` plus the research files.
2. Ask Claude for "deep research on I12" (any person ID), or "work through the research queue".
3. Read the report and the life story it wrote, and answer the open questions it leaves for you.

## What is in the plugin

- **Skills:** `deep-research` (one person, start to finish), `life-book` (a book of life stories along the paternal lines of father and mother), `setup`, and `coordinate` (user-invoked, for running several rounds in parallel and merging them).
- **Helper agents:** archive searcher, scan reader, background researcher, life-story writer.
- **The `lineage` CLI**, on Claude's PATH while the plugin is enabled: validation, person cards, ancestor and descendant tables, the research queue, kinship, archive search and scan download, handwriting recognition through Transkribus, request letters to archives, a Gramps Web sync, a question heat map. `lineage --help` lists everything; `lineage round ...` runs the research-round scripts.

Each research round works in its own git worktree and branch, so nothing reaches your tree before it has been reviewed and merged. Rounds run inline (one per session, helpers as subagents), in Herdr panes, or headless in the background (`runner` in `lineage.toml`).

## Privacy

Family trees contain living people. The skills never send data about living persons to external services, never open the GEDCOM for an outside model, and search archives only for people who died long ago, unless your project file (`research/project.md`) allows more. Credentials for optional services (mailbox, Gramps Web, Transkribus, Geneanet) stay in `~/.config/lineage/` with mode 600 and are entered with `lineage auth <service>`, never through the conversation. Mail is off unless a project enables it, and no mail is sent without your explicit approval of that draft.

## External services

- **Open Archieven** (openarchieven.nl): no account needed.
- **Regionaal Archief Tilburg / Memorix viewers:** public; the CLI throttles itself, because parallel downloads get an IP address blocked for hours.
- **Transkribus:** your own account and credits; the CLI refuses large batches by default.
- **Gramps Web, a mailbox, the Geneanet forum:** optional, per project.

## Development

The CLI lives in `plugins/genealogy-research/cli` (Python 3.12, uv): `uv run pytest`, `uv run ruff check`. Messages are English in the code with translations in `src/lineage/locales/<language>/`. Design notes are in `docs/`.

## License

See [LICENSE](LICENSE).
