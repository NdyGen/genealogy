# lineage

Genealogy research tools for GEDCOM trees: validation, reports, archive lookups, a research queue, correspondence drafts and a Gramps Web sync. Run with `uv run lineage <command>`; `--file` (before the command) selects another GEDCOM file than the project's.

## Project settings

`lineage.toml` in the project root holds what differs per family tree. lineage finds it in the working directory or one of its parents (or in `LINEAGE_CONFIG`); every path in it is relative to its folder. Commit it: research rounds run in git worktrees and read their own copy.

```toml
name = "Smith family research"      # title on generated pages
language = "en"                     # output language: en, nl, de, fr
gedcom = "data/tree.ged"
targets = [{ label = "Me", id = "I1" }, { label = "Partner", id = "I2" }]
line_root = "I5"                    # whose ancestors form the direct line; default the first target
stems = [{ name = "Smith", id = "I1" }, { name = "Jones", id = "I2", men_first = true }]
runner = "auto"                     # auto, herdr, headless, inline

[paths]                             # any file or folder by name; see `lineage config show`
research = "research"

[paternal_line]                     # watched by `lineage paternal --notify`
start = "I1"
notify = "me@example.org"

[mail]
enabled = true                      # this project sends requests and reads replies; off by default
own_address = "me@example.org"      # mail to this address needs no approval
sender_name = "Ann Smith"

[gramps]
url = "https://gramps.example.org"

[accounts.personal]                 # Claude accounts for parallel rounds
config_dir = "~/.claude-personal"
```

Without the file the default paths apply relative to the working directory, and commands that need a project value (target persons, line root) say which key is missing.

Credentials never go in this file. `lineage auth <service>` (mail, gramps, transkribus, geneanet) asks for them in the terminal and writes `~/.config/lineage/<service>.env` with mode 600; `LINEAGE_<SERVICE>_CONFIG` points elsewhere.

## Commands

- `init`: write `lineage.toml` and the empty research files; `--update` changes an existing setup.
- `config show|check|path <key>`: the settings, a check against the tree, the path of a file or folder.
- `doctor`: required and optional software, and which services are set up.
- `auth <service>|check`: enter credentials for a service; `check` shows the state of each.

- `summary`: counts, source coverage and surnames.
- `validate`: check the tree for errors and implausibilities.
- `search <words>`: find persons by name.
- `person <id>`: everything about one person.
- `ancestors <id>`, `descendants <id>`: numbered ancestor table, descendant table.
- `tree <id>`: family tree diagram as Graphviz DOT/SVG.
- `kinship <id>`: kinship with the target persons.
- `paternal`: the paternal line; `--notify` drafts a mail when it grows.
- `book <id>`: book of life stories along the paternal lines.
- `stale`: life stories that lag behind the tree.
- `question-map`: heatmap page of open questions.
- `queue show|add|next|start|done|skip|normalize`: deep-research queue.
- `review <id>`: mechanical review of a finished research branch.
- `guard`: keeps research rounds running across usage limits.
- `archive search|show`: search and view records on Open Archives.
- `rat search|item|download|throttle|crop`: Regionaal Archief Tilburg inventory, scans and crops.
- `scan <refs>`: fetch an archive scan at full resolution, with provenance.
- `htr <images>`: Transkribus text recognition (costs credits); `--count` shows usage.
- `requests`: list and mark mail drafts to archives.
- `mail test|send|inbox`: send an approved draft, fetch replies.
- `forum post|read`: post a forum draft, read replies.
- `gramps status|sync`: compare and sync with Gramps Web.
- `coordinates index|search|fill`: offline coordinates for places and addresses.

Run `uv run lineage <command> --help` for the options.
