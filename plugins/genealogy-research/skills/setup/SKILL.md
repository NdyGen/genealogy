---
name: setup
description: Set up genealogy research in the current folder, or change an existing setup. Starts from a GEDCOM file, an export from another genealogy program, or nothing at all (then it interviews the user generation by generation and builds the first tree), chooses target persons, output language, runner and optional services, writes lineage.toml and the research folders, and queues the first persons to research.
disable-model-invocation: true
---

# Set up genealogy research

You set up a folder for genealogy research with the lineage CLI (`lineage`, on your PATH while this plugin is enabled). The user may be an experienced genealogist with a tree of thousands of people, or someone who knows the names of their grandparents and nothing more. Find out which early and adapt: short and efficient for the first, patient and explanatory for the second.

How to ask:
- Choices (yes/no, one of a few options): AskUserQuestion, one question at a time, with a sensible default first.
- Facts (names, dates, places, stories): plain questions in the conversation, about one person or one couple at a time. Never ask for everything at once.
- "I don't know" is a good answer. Write down what is known, note what is not, and move on.
- Speak the user's language. After every few answers, say back briefly what you recorded, so mistakes surface early.

If `lineage.toml` already exists, read it first (`lineage config show`) and use its values as the defaults: the user is changing a setup, not starting over. Never overwrite research files that already exist.

## 1. Requirements

Run `lineage doctor`. It reports uv, git, Python, Chromium (only needed for `lineage scan`), hc, Herdr and a few optional tools. If something required is missing, give the install instruction it prints and stop. Offer to install Chromium (`lineage doctor --install-browser`) only when the user wants to fetch scans.

## 2. Output language

Default: `${user_config.language}`, otherwise the language of this conversation. It decides the language of reports, life stories, the research log and CLI messages. File names and data formats are always English. Ask now, so everything that follows (including CLI messages) is in that language.

## 3. Where the tree comes from

Look for GEDCOM files (`find . -maxdepth 3 -iname '*.ged'`). Then ask which situation fits:

**A. A GEDCOM file in this folder (or elsewhere on disk).** Ask which one is the research tree. If it is not already at `data/tree.ged`, copy it there; the copy becomes the source of truth and is edited by the research rounds, the original is no longer used (say so, and offer to leave it out of git). Run `lineage --file <path> validate` and summarize the result in plain words. Report problems; fix nothing without being asked. Continue with step 4.

**B. A tree in a genealogy program or website** (MyHeritage, Ancestry, Geni, Gramps, Family Tree Maker, a family website). Explain that research works on a GEDCOM export, and help the user find it: it is usually under the tree's settings or the file menu, called "Export" or "GEDCOM". Do not invent menu paths you are not sure of; ask the user what they see. FamilySearch's shared tree has no full export: then take path C and copy the relevant people by hand. When the file is there, continue as in A.

**C. Nothing yet: start a new tree.** Continue with "Starting a new tree" below, then step 4.

## Starting a new tree

Explain in two or three sentences what happens: together you write down what the user knows, each fact with where it comes from ("my own memory", "told by aunt Els", "family booklet"). That is the starting point; the research rounds then look for the records in the archives. Archives keep recent records closed for privacy (in the Netherlands roughly: births for 100 years, marriages for 75, deaths for 50), so the research really starts with grandparents and great-grandparents. The more the user knows about them, the better.

Create the empty tree and the project with the language already chosen:

```
lineage init --new-tree --language <code>
```

### The interview, generation by generation

Work from the user backwards. Per person ask, in this order and only what is known:
1. Full name; for women the birth name (maiden name), not the married name.
2. Born: date (a year or "around 1890" is fine) and place.
3. For deceased persons: died, date and place; where buried, if known.
4. Occupation, religion, places where they lived.
5. Per couple: married when and where; their children (names and rough birth years are enough for siblings).

Order: the user (or the person the research is about), then parents, then the four grandparents, then the eight great-grandparents as far as anyone knows. After each couple, ask whether to go one generation further back on that side or switch to the other side. Stop where knowledge ends; never press.

Record each person right after the answer, with the source the user gave:

```
lineage add person --given "Johanna Maria" --surname "de Boer" --sex F \
  --born "12-3-1921" --born-place "Zwolle, Overijssel, Nederland" \
  --died "1998" --died-place "Kampen, Overijssel, Nederland" \
  --occupation "seamstress" --source "Told by Anna Visser (daughter), 2026"
lineage add family --partner I3 --partner I4 --married "1946" --married-place "Zwolle" --child I2
lineage add child F2 I5
```

`lineage add person` prints the new ID; use it in the family commands. Dates may be written the way people say them (12-3-1950, 12 maart 1950, 1950, omstreeks 1890, between 1880 and 1885); places as "town, province or county, country". `--deceased` records that someone died without a known date. Every few persons, show the result with `lineage ancestors <ID of the user> --generations 4`.

Living persons (the user, siblings, parents who are alive, children): record only what is needed to link the generations: name, birth year and place, the family links. No addresses, phone numbers or other details. They are never searched in archives.

### Papers at home and relatives to ask

Ask which documents the family has. Name examples that fit the country; for the Netherlands and Flanders: the family booklet (trouwboekje, gezinsboekje), memorial cards (bidprentjes) and mourning cards, death announcements, baptism and membership certificates, a family bible, old letters, military papers, emigration papers, photos with writing on the back, and for persons who died after 1938 the person card or person list (persoonskaart, persoonslijst) from the CBG. Facts from a document get the document as source (`--source "Bidprentje Jan Visser"`). Suggest photographing the papers into the sources folder (`lineage config path sources`); they become the first sources of the research.

If an older relative knows more, offer to write a short interview list (names to ask about, the questions per person, the papers to look for) to `<research>/interview-<name>.md`. The user can come back later and add the answers with `lineage add`.

### A first look in the archives

When at least one ancestor who died long ago is known with a name, a rough year and a place, show the user that it works: search one record together, preferably the marriage of a grandparent or great-grandparent couple (`lineage archive search "<name> & <name>" --type Huwelijk` for Dutch records, or the person with a year range). Show the result in plain words. If it clearly fits, ask whether to record it (as a source on the event, with `lineage archive show <ref> --gedcom` for the source text); if it is doubtful, say so and leave it for the research rounds. Do this only for persons who died long ago, never for living persons.

### Enough to start?

Research can start when at least one deceased ancestor is known with name, approximate year (within about ten years) and place, ideally born before about 1925 or married before about 1950. A couple with marriage year and place is better still. If the tree is not there yet, say plainly what is missing and what would help most (which relative to ask, which paper to look for), write these as open questions in the questions file (`lineage config path questions`, chapter for the user's choices), and finish the setup anyway: the user can continue the interview any time by asking Claude to "add to the tree".

## 4. Target persons

The research is oriented towards one or more target persons, usually the user (and partner, children). In a new tree that is the user. In an existing tree, ask for a name, run `lineage search <words>`, and let the user pick from the candidates (show ID, name, birth and death). Then offer partner and children of that person as additional targets. The youngest target whose ancestors cover the others becomes `line_root` (the direct line). Stems default to the paternal lines of the targets; mention that they can be changed later.

## 5. Runner

Default: `${user_config.runner}`. With `auto`, lineage uses `hc` in a Herdr app terminal, `herdr` inside the Herdr CLI and `inline` otherwise. Explain briefly:
- `inline`: one research round per Claude session; helper agents run as subagents. Simplest, no extra software. The right choice for most people.
- `hc`: rounds and helpers as terminals in the Herdr app (herdr-core), several rounds in parallel, a coordinator can merge them.
- `herdr`: the same with the older Herdr CLI, in its own tabs and panes.
- `headless`: parallel rounds as background `claude -p` processes, without Herdr. Permission prompts cannot be answered there.

Ask about Claude accounts only for `hc`, `herdr` or `headless`: a list of names, each with an optional `CLAUDE_CONFIG_DIR`.

## 6. Optional services

Offer each one briefly, skipping is fine (and the usual choice at the start):
- Transkribus (handwriting recognition, costs the user's own credits).
- A mailbox for request letters to archives (drafts are always shown to the user before anything is sent). Mail is per project: pass `--mail` to `lineage init`, otherwise the project neither sends nor reads mail, even when the credentials exist.
- Gramps Web (publish the tree to the user's own Gramps Web server).

Passwords never go through this conversation. Ask the user to type `! lineage auth <service>` themselves; that command prompts without echo and writes `~/.config/lineage/<service>.env` with mode 600. Afterwards run `lineage auth check` and report the result.

## 7. Privacy

A family tree almost always contains living persons. Write the project rules into the project agreements file (`lineage config path project`): publish nothing, send no data about living persons to external services, and any exceptions the user chooses (for example: searching archives about persons who died before 1900).

## 8. Repository

Research rounds need git. If the folder is not a repository, explain in one sentence why (every round works on its own branch, so nothing reaches the tree before it is checked) and propose `git init`. Propose a `.gitignore` for fetched scans, media, the output folder and `.worktrees/`. Make the first commit only after the user agrees.

## 9. Finish

Run `lineage init` with the chosen values (`--update` when the project already exists, as after a new tree): it writes `lineage.toml`, the research folder with `project.md`, `queue.tsv`, `log.md` and `questions.md`, and the reports folder. An existing `project.md` is kept, so after a new tree fill in its section on target persons yourself (names and IDs). Run `lineage config check` and fix what it reports.

Queue the starting points: in an existing tree the first target person; in a new tree the oldest deceased ancestors on each side whose records are likely public (both partners of each couple) (`lineage queue add <IDs> --reason "starting point"`). Queue both partners of a couple. `lineage queue add` itself reports anyone it skips as possibly living; report that as it says, do not guess reasons.

Then summarize in a few lines, in the user's language: what is set up, what was skipped, who is in the queue, how to start the first round (ask Claude for "deep research on <ID>"), and for a new tree the two or three things that would help most next (a relative to ask, papers to look for).
