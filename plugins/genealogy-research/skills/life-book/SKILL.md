---
name: life-book
description: Makes a book of life stories of the ancestors of one person in the project's family tree (project specifics in `research/project.md`), in two parts. Part I follows the paternal line on the father's side (father, his father, and so on); part II starts with the mother and follows her paternal line. Under each life story it shows how the line runs to the chosen person and which facts in the tree support the story, each with its source. Use this skill when someone asks for a book, collection, family history or bundle of life stories of someone's ancestors, for "the paternal line" or "the mother's line" as a story, or for an overview of what has been written per ancestor and what is missing.
---

# Life book

You make a book of life stories along two lines of one person. You do not write the stories yourself: they come from the life stories folder (`lineage config path life_stories`, files `<ID>.md`), written in the deep-research rounds. The command `lineage book` puts them in order and adds the line and the supporting facts under each story.

Language: the book is written in the project language (`lineage config value language`) and the PDF follows it.

## Procedure

1. **Determine the person.** If the user gives a name, find the ID with `lineage search <name>`. With several candidates, choose on birth year or parents, and ask only if it really cannot be decided.
2. **Make the book** from the folder of `main`, so the newest merged stories are in it:
   ```bash
   lineage book <ID>                    # writes <books folder>/<ID>.md (lineage config path books)
   lineage book <ID> --youngest-first
   ```
   By default each part starts with the oldest ancestor, so the book reads as a family history from the progenitor downward.
3. **Make a PDF** if the user wants one (the script is in this skill's `scripts/` folder; `uv` fetches the two dependencies):
   ```bash
   uv run --with markdown-it-py --with typst python ${CLAUDE_SKILL_DIR}/scripts/pdf.py <books folder>/<ID>.md
   ```
   This writes `<books folder>/<ID>.pdf`: title page, contents with page numbers, each part and chapter on a new page, images with captions, and the line and supporting facts in smaller type under each story. It reads the book in either supported language (English or Dutch headings) and sets the PDF language to match. Typst needs no system libraries (Chromium and WeasyPrint do). After building, look at a few pages (`typst.compile(..., format="png")` on the source kept with `--typ`) before you report the result.
4. **Check.** Read the contents and the closing "Still to write" list. Also see whether stories lag behind the tree: `lineage stale <ID>...` (with the IDs from the book) names the stories whose record, a marriage or a child changed after writing. Tell the user:
   - how many stories each part holds and which ancestors have no story yet;
   - which stories can be updated (and offer to have that done in an update round, see the coordinate skill, "Updating life stories");
   - which of those ancestors are already in the research queue (`lineage queue show --all | grep <ID>`), and whether it makes sense to move them forward;
   - where a line stops, and why (unknown father, or the father is not yet researched).
5. **Do not fill in yourself.** If a story is missing, do not write it into the book. A story belongs to a finished research round with a report; put the person in the queue or start a round following the `deep-research` skill.

## What each chapter holds

- **The life story**, without the kinship line at the top and without the sources line at the bottom (the book replaces that with its own supporting facts). Headings go down one level; image paths and references to other stories are adjusted to the book.
- **Line to <person>:** every generation from the ancestor to the chosen person, with years, ID and the kinship to the chosen person.
- **Supporting facts:** all facts in the GEDCOM for that ancestor and his marriages, by date, each with the source as recorded in the tree. Facts without a source are reported as such. Below that the path to the full report and the background sources from the story.

## Living persons

- Possibly living persons (born after 1925 without known death) get no story, no dates and no facts in the book, only their name in the line.
- The book stays local. The data contains living persons: publish nothing and send nothing to external services.
- If the user asks for a web page or artifact of the book or a part of it, make a version without names of living persons (say "the current generations") and without the chosen person if he or she lives, and publish only after that check.

## Finishing

The book is derived from the tree and the stories; rebuild it after new research instead of editing it by hand. Commit it only if the user wants to keep it.
