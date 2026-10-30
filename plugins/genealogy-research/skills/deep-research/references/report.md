# Report template: `<person_reports>/<ID>.md`

Find the folder with `lineage config path person_reports`. Write for the user: readable text in the project language (`lineage config value language`), no raw dumps, no em-dashes. Every fact has a reference to the record, in the form `archive:identifier` or archive, inventory and folio. Keep context (section "Time and place") strictly separate from facts.

## Headings and words that tools recognise

The report's section headings are free text for people; only the items below are read by tools. Keep them as given.

| Where | What | Notes |
|---|---|---|
| report heading | the account name from `<output>/account` | `lineage review` errors if it is missing from the new text |
| report | the number of Transkribus recognitions of the round, as "N Transkribus recognitions" (Dutch: "N Transkribus-herkenningen") | also when 0; checked against the HTR log |
| report | every ID added to the queue appears in the text | checked against the queue diff |
| report and life story | "helper agent" (Dutch "hulpagent") with "proven" (Dutch "bewezen") in the same paragraph, without "not" | warned: a helper's reading is never proven |
| report, NOTE, life story | words off the scale: "demonstrable", "almost certain", "nearly certain", "undoubtedly", "without doubt" (Dutch: aantoonbaar, vrijwel zeker, bijna zeker, ongetwijfeld, zonder twijfel) | warned |
| report, last line | `Blog-worthy: yes/no` (Dutch: `Blogwaardig: ja/nee`) | read by the coordinator |
| report | a section "For the coordinator" (Dutch: "Voor de coördinator") | read by the coordinator: corrections elsewhere, uncertain decisive readings |
| log | heading `## <date> · <ID> · <name> (deep research)` | `lineage round finish` looks for the ID in a new `## ` heading |
| tree NOTE | `Deep research <dd-mm-yyyy>: <report>` | added by `lineage round merge`; never by you. Your own findings notes begin `Deep research <ID> (...)` |
| life story | first line `# <title>`; an optional italic kinship line right after it; a `---` line before the sources tail; a tail line that starts with `**Background` (Dutch `**Achtergrond`) | read by the book builder and the Gramps Web sync |
| life story | images `![alt](path)` followed by an italic caption line | read by the Gramps Web sync |
| questions file | chapter headings (see below) | sort the questions by kind |

Chapter headings of the questions file, English and the Dutch ones used so far (a project uses one language, and the file already has its headings; keep them):

| English | Dutch |
|---|---|
| Choices for the user | Keuzes voor de gebruiker |
| To research with online sources | Uit te zoeken met online bronnen |
| On site only or with a full-resolution scan | Alleen ter plaatse of met scan op volle resolutie |
| Living persons or recent (do not look up) | Levende personen of recent (niet opzoeken) |
| Solved | Opgelost |

Dutch headings of the report used so far (English first): Summary (Samenvatting), Course of life (Levensloop), Stories (Verhalen), Fact check (Feitencheck), New facts from other registers (Nieuwe feiten uit andere registers), Time and place (Tijd en plaats), Parents, partners and children (Ouders, partners en kinderen), Removed (Verwijderd), Open questions (Open vragen), Added to the queue (Toegevoegd aan de wachtrij), Line of evidence (Bewijsvoering), For the coordinator (Voor de coördinator).

## Certainty scale

Every statement that is not established (an identification, a link, a connection, a reading) gets one word of this scale:

| Word (Dutch) | Means | In GEDCOM |
|---|---|---|
| **proven** (bewezen) | a record, plus a second independent feature that agrees | as a fact or link, with citation |
| **probable** (waarschijnlijk) | several independent indications, but no record that says it | as a NOTE ("not linked"), plus an open question; as a link only when marked and after a decision of the user (see "Linking without a direct record") |
| **presumed** (vermoedelijk) | one pattern or feature (naming after a relative, occupation, neighbourhood) | only as a NOTE, plus an open question |
| **possible** (mogelijk) | only the name (perhaps with place) | at most as a search lead in the open questions |

Summary, Stories, NOTE in the tree, the questions file, the log and the life story use **the same word** for the same statement. If a presumption becomes "probable" in the summary and "almost certain" in the life story, the family reads a stronger statement than the source carries. A reading by a helper or by Transkribus that the research lead did not reread on the scan is never proven.

Counting features honestly:
- **Name, patronymic and place are one feature.** A man with the right given name and the right patronymic in the right village is a presumption at most, however well it fits; it becomes probable only with an indication that does not come from the name (a spouse, a property, a godparent who recurs).
- **A new reading of an uncertain name is not an identification.** If a word stays uncertain on the scan, matching it against a list of officers, clerks or neighbours is name similarity only: possible, a search lead. Two uncertain steps do not add up to a presumption.
- **"Read myself" only for what is on the scan.** A date or a bound taken from the regest of a neighbouring record, or from an index, is cited as the regest's or the index's, also in the PAGE text. A step the record does not state (a stopover on a route, a sentence by a court when only a prison register was seen, the reason for a request) is written as a derivation.

`Blog-worthy: yes` only for a proven core finding, or a story that stands without an unproven step.

## Linking without a direct record

Linking a parent, child or partner (FAMC, CHIL, HUSB/WIFE) is normally done only when it is **proven**. For a **probable** link there are two cases. The difference is where the kinship is stated.

**A. The kinship is in a record, only the identity is derived.** Example: a baptism names the parents of a Joannes, and that this is our Joannes follows from a second indication (a godparent, a naming, the same place). This may be a **marked link**, but only after a decision of the user. The coordinator puts it to the user. The marking looks like this:
- under the link (at the child: `1 FAMC @F..@`) a `2 SOUR` to the record with the kinship, with `3 PAGE` and `3 QUAY 1`;
- under that a `2 NOTE`: "Link probable, not proven (<the record with the kinship; the indication for the identity>). Confirm with <what is missing>; decision <user> <date>.";
- in report, life story, questions and log the word "probable", never as established fact;
- the question "confirm" stays open in the questions file.

A chain counts as one indication: if the second indication itself rests on a derived identity (a brother who is the baptised child only on name and patronymic), it is case A and not proven.

**B. The kinship is in no record, everything is derived.** Example: a patronymic, a neighbour in a tax register, a guardianship habit. Then **no link**, not even a marked one, until all four conditions are met:
1. **A reasonably exhaustive search.** Every source that could decide it was consulted, or is explicitly listed as unreachable. That includes sources only available by mail or in a reading room.
2. **Counter-indications discussed.** Every indication against it (a naming that does not fit, an age, a namesake) is discussed and resolved, or honestly weighed.
3. **Line of evidence written out.** A section "Line of evidence" (Dutch "Bewijsvoering") in the report, and a short NOTE at the person that refers to it. It holds:
   - the question;
   - all candidates and why they dropped out;
   - every argument for, with source;
   - every argument against, with source;
   - what was not searched yet;
   - the conclusion in one word of the scale.
4. **A decision of the user.**

Until then the candidate stands only in the line of evidence and as a NOTE at the person ("probable father: <name> (<ID or description>), not linked; see the line of evidence in the report"), and the question stays open. If the four conditions are met and the user decides to link, use the same marking as in A: `QUAY 1`, with a NOTE that refers to the line of evidence.

A paternal-line notification (`lineage paternal --notify`) follows only on a link, never on a candidate in a NOTE.

## Report

```markdown
# <Name> (<ID>), <birth year>-<death year>

Deep research <date>, round <n>, branch `dr/<ID>`, account <account>.

## Summary
Three to six sentences: who was this person, what is new or corrected, what is removed, and how many family members were added. Name the most striking story too. For every statement that is not established use the word of the certainty scale, and give the number of Transkribus recognitions of this round (from the diff check in `SKILL.md`).

## Course of life
| Date | Event | Place | Source |
|---|---|---|---|
| 12-3-1801 | baptised (RC), godfather … | Sprang | DTB baptisms Sprang, `sha:…` |
| … | | | |

## Stories
The heart of the report. Work every notable fact out into a piece of its own of a few paragraphs, with a heading in plain language (for example "### 1802: 28 broken windows"). Per story:
- **What happened,** as concretely as the source allows: date, place (street, house), who was there and in what role.
- **The source itself:** quote the main sentences literally from the regest, record or newspaper, in old spelling, with a reference.
- **Explanation of terms** that a present-day reader does not know, such as "akte van indemniteit" (a declaration by which a municipality promises to bear the poor relief if someone moves elsewhere and becomes poor), schout en schepenen, ondertrouw (the registered marriage banns), gaarder, or legitimation.
- **What it says about the person's life:** position in the village, poverty or prosperity, conflicts, network. Keep what the source says and interpretation apart.
- **What is not known,** and where a sequel might be found (judgment, ruling, original record).

No stories found? Say so in one sentence. Do not fill the section with general history; that belongs under "Time and place".

## Fact check
| Fact | Was in the file | Outcome | Proof |
|---|---|---|---|
| birth | 1801 (no source) | confirmed: baptised 12-3-1801 | … |
| occupation | farmer | corrected: shoemaker | … |
| child I1234 | child in F56 | removed: no record | searched: … |

## New facts from other registers
Per register what it yielded: militia, population register, notarial, court, newspapers. Mention registers that yielded nothing too, briefly.

## Time and place
Per life station (place and years): what was going on there and then, and where does that touch his life according to the sources? For every statement say whether it comes **from the sources** (with archive source; if it hangs on an uncertain identity, with the word of the certainty scale) or is **context** (no proof that it touched him personally). Not "demonstrable": that word is not on the scale, and `lineage review` flags it. For every context statement give the source (URL or publication). The life story draws on this section.

## Parents, partners and children
- Parents: confirmed or changed, and with which record.
- Partners: per marriage date, place and record.
- Children: table with ID, name, born/baptised, died, and whether the child is new, confirmed or removed.

## Removed
What is gone, the old value, and what was searched. The same information is in the NOTEs in the tree.

## Open questions
What was not found, and where the next step lies (archive, inventory, or which scan). A site that stayed unreachable is listed here with the reason and the time of the last attempt.

## Added to the queue
| ID | Name | Relation | Reason | Priority |
|---|---|---|---|---|

## For the coordinator
Corrections whose old value stands elsewhere, uncertain decisive readings (file names of the scan and crop, which letters are uncertain), a blog proposal.

Blog-worthy: yes/no, with one sentence why.
```

---

# Life story: `<life_stories>/<ID>.md`

Find the folder with `lineage config path life_stories`. A narrative version of the same life, for the family, in the project language. Examples of good life stories in this project: see `project.md`.

```markdown
# <Name> (<birth year>-<death year>)

*<Kinship, from `lineage kinship <ID>`, written out: for example "Brother of <name> (<ID>), the great-great-grandfather of <target person> (<ID>)." The target persons and an example line are in `project.md`.>*

<The story, in chronological paragraphs.>

<Close: where the life ends, and how the family line continues to today.>

---

**Sources:** <the main records and registers, briefly>. All facts with references: `<person_reports>/<ID>.md`.

**Background** (about the time and place, not about the person himself): [<subject>](<url>) (<for what>); …
```

Dutch life stories use `**Bronnen:**` and `**Achtergrond**`; the book builder and the Gramps Web sync accept both. The italic kinship line, the `---` line and the `**Background`/`**Achtergrond` tail line must stay where they are, because the tools cut the story body out between them.

Notes:
- **Tell it, but invent nothing.** Every fact in the story comes from the report: dates, places, occupations, names of witnesses, quotes from records, the description. Colour is allowed ("between the knocking of the shoemaker's hammer"), as long as it fits what is established, such as a house full of shoemakers.
- **Say when we do not know.** Motives, feelings and connections that no source names, you put explicitly as a question or possibility: "What went through his mind, we do not know. We do know what he did." A naming or a cause that is stated nowhere, you name as such.
- **No clause without a source.** Reviews kept finding one clause the source does not carry: "the usual rate", "named after Cornelis's father", "two grown children" (of whom only one was probable), "so together". After writing, reread every clause with an explanation, naming, count, cause or custom: is it in the report? If not, strike it or make it a question or possibility. A naming that fits both parents, you name on both sides.
- **Give background: what was going on where he was?** For the main places and moments in his life look up what happened then and there, and weave that through the story. Think of the garrison town and the war of that moment, the flood or epidemic in the village, the rise of a local industry, or a notable event nearby. An example is in `project.md`. Rules:
  - Only background that adds something to this life, no general history lesson.
  - Every background statement has a source (Wikipedia, an archive or local history site, a publication). Give it under a separate heading **Background** in the sources line, as a link with a few words for what it is for. If you cannot find a statement in a source, leave it out.
  - Do not suggest the person was involved if no source says so. Write "Whether he was ever there, we do not know" or "Whether he was destined for Atjeh is stated nowhere".
- **Images that add something** may go in: photos, prints, drawings, old maps, postcards, posters or newspaper illustrations. For example the church where someone was baptised, the street where he lived, the ship he left on, or a map of the garrison town. Scans of records do not belong here: they are in the report. Rules:
  - **Only if it contributes** to this story, and as close as possible to the time and place. A photo of the church from 1900 for someone who married there in 1890, yes; a random village photo, no.
  - **Origin and rights:** use image banks with a clear licence, such as Wikimedia Commons, the image banks of regional archives, national museums and archives, or national newspaper and heritage portals (in the Netherlands for example BHIC, RA Tilburg, SALHA, Stadsarchief Rotterdam, Rijksmuseum, Nationaal Archief, Delpher, Het Geheugen). Take only images in the public domain or under a free licence (CC0, CC-BY, CC-BY-SA). If in doubt, do not use it, but name the find place as a link.
  - **Storage:** `<life_stories>/images/<ID>/<short-name>.jpg` (Dutch projects used `afbeeldingen/<ID>/`; keep what the project already has), reduced to at most 1200 pixels wide and about 300 kB, never over 500 kB (for example with Python/Pillow or `convert`). These go into git.
  - **Photos of the person himself** from the project's media folder (not in git; what is there is in `project.md`) may be used if the person is deceased. Refer to them relatively and do not copy them into git.
  - **In the story:** put the image at the paragraph it belongs to, with a caption in the form `![<description>](images/<ID>/<name>.jpg)`, directly followed by an italic line `*<what and where, year>. Source: [<image bank>](<url>), <licence>.*`. An image is context, not proof: do not say the person is in it or was there unless a source says so.
  - At most a handful per story; rather two good ones than six ordinary ones.
- **Explain terms in the running text,** such as substitute (plaatsvervanger in the draft), pro Deo (free legal aid) or akte van indemniteit, and put quotes from records between quotation marks.
- **The close connects with today.** If someone other than the main person appears in the story (a brother, a child), explain why: how does the line run via that person to the target persons in `project.md`? A side branch without descendants ends with the family who got the news or passed on the name. Never let the close jump to someone else without explanation.
- **The line to today** runs to the target persons in `project.md` and no further than that file allows. It also says which target person reads most naturally and how the names run (who has whose surname); follow that exactly.
- **Certainty:** use for a statement the same word of the certainty scale as the report ("presumed" stays presumed, not "probable" or "almost certain").
- Length: as long as the facts and background carry, usually 500 to 1200 words. No em-dashes. Living persons are not named, except those `project.md` expressly names.
