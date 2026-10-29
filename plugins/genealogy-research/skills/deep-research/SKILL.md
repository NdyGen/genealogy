---
name: deep-research
description: In-depth genealogical research (deep research) on one person in the project's family tree. Checks every fact against archive sources, removes what cannot be verified (keeping it as a note), corrects demonstrable errors, searches registers beyond baptism, marriage and burial (population registers, militia, notarial, court, newspapers), places the life next to local and national history, checks and completes parents, partners and children, and adds newly found family members to the research queue. Use it whenever someone asks to research a person (by ID such as I123 or by name) thoroughly, completely or "in depth", wants a deep research or a life story, wants to know what else can be found about an ancestor, or asks to work through the research queue or to start agents on persons from the queue.
---

# Deep research on one person

You research **one person** as completely as possible, record what can be proven and report it readably for the user. You check the direct family along the way; people you newly find go into the queue for a round of their own. That keeps each research bounded, and the tree still grows round after round.

Coordinating several researches (filling the queue, starting agents, merging)? Use the `coordinate` skill. The rest of this file is for whoever carries out the research.

**Project file.** This skill is shared by many projects. What differs per project is in the project's own files: `lineage config path project` (usually `research/project.md`) and `lineage config path lessons` (usually `research/lessons.md`). They hold the target persons and their IDs, the direct line and its stems, who may be named as living in "the line to today", the language conventions, examples of good life stories, and agreements about map, blog, forum, mail and publication. **Read both first**; where they contradict an example here, they win. Dutch examples and archive names in this skill illustrate a method, not your project.

**Language.** Run `lineage config value language`. Write the report, the life story, the log, the questions and any request text in that language, and the NOTE text you put in the tree too. Templates in this skill are given in English; `references/report.md` lists the Dutch headings used so far, because some tools recognise them.

**Finding files.** Never assume a folder. Ask the CLI: `lineage config path <key>` gives the location, `--relative` the path below the project root. Keys used below: `gedcom` (the tree), `queue`, `questions`, `log`, `project`, `background`, `requests`, `person_reports`, `life_stories`, `output` (the worktree's output folder).

## Principles

The user wants a tree in which every fact is right. The rules follow from that:

- **Proof or nothing.** A fact stays or is added when an archive document names it: a record, register, protocol or newspaper item. Trees of others, automatic matches and "probably" are search hints, not proof.
- **Identify on at least two features.** Link a record to a person only when two independent features agree, for example parents, partner, age, birthplace or occupation. Say in your report which features they were. A name plus a place is not enough; people of the same name in the same village are very common.
- **Without a record, split; with a record, state it as fact.** This holds for what is already in the file too. Were two persons or two marriages merged into one record, or was someone attached to a family, without a record that proves it? Then split the record (a new person in your own ID block) or remove the link, and put a `NOTE` at both explaining why and what is needed to merge them again. If a record does prove the link, state it as a fact with a citation. "Probably the same" or "the regest author assumes it" is not a record.
- **Unverifiable goes, but not silently.** If you searched thoroughly and a fact cannot be verified, remove it and put the old value in a `NOTE` at the record, in the project language. In English:
  `Removed on <date> (deep research <ID>): <old value> (source: <old source or 'none'>), not verifiable in <what you searched>.`
  (Dutch: `Verwijderd op <datum> (deep research <ID>): <oude waarde> (bron: <oude bron of 'geen'>), niet te verifiëren in <wat je doorzocht>.`) That way it can always be found and restored. This holds for parent-child links too: name the IDs of the old family in the note.
- **Contradictory is not unverifiable.** If two records contradict each other (an age against a baptism date, say), record the range the sources give (`BET … AND …`). Put the contradiction in a NOTE. Both records get a citation.
- **Correct demonstrable errors** with a NOTE that names the old value.
- **Birth from baptism:** a baptism record without a birth date does prove that someone was born on or before the baptism day. If there is no sourced birth date, record the birth as `BEF <day after the baptism>`, with the baptism record as citation and a NOTE: `Born on or before the baptism date <d-m-yyyy>; derived from the baptism, which gives no birth date.` No birthplace: it is not proven to equal the baptism place. A birth date without a source that merely repeats the baptism date is replaced this way (with a NOTE naming the old value). Do not just delete it.
- **Living persons.** Look up nothing about anyone born after 1925 without a known death, and send their data nowhere: no web search with their names, no external service, no mail, no forum post, no model API. Records from the last century are not public anyway. Exceptions exist only where `project.md` explicitly allows them, for a stated purpose and a stated group of persons (typically deceased persons before a cutoff year). When in doubt, do not send it.
- **Reach.** You change the researched person, his families (FAMC/FAMS) and the records of his parents, partners and children as far as those links are concerned. New persons go in your own ID block. In-depth research on relatives belongs in their own round: put them in the queue.

## Division of labour: you decide, helpers search

You are the research lead. Most of the work in a research is searching and reading: archive indexes, scans, websites. Have helper agents on a cheaper model do that, so your own context stays small. In earlier researches three quarters of the tool calls and most of the usage went into searching, because every turn rereads the whole context.

| Role | Does | Agent |
|---|---|---|
| `archive-searcher` | search records and mentions for a concrete question; returns candidates with all fields and citation, and what was searched without result | `dr-archive-searcher` |
| `scan-reader` | transcribe scans literally with uncertain readings marked; fine for 19th-century records and registers, **not** for 16th and 17th-century chancery hands (protocols, accounts): it does not read those reliably. Read those yourself, at full resolution from `lineage rat download` or `lineage scan`; at most let it locate pages | `dr-scan-reader` |
| `background` | step 4 entirely: time and place, knowledge base, images | `dr-background` |
| `life-story` | write the life story from the finished report | `dr-life-story` |

**What you do yourself:** keep the list of facts, the identification on two features, the outcome per fact (confirmed, corrected, range, removed), every change to the tree, the queue, the report and every commit. Helpers do not change the tree and do not commit.

**How to give an assignment:**
1. Write `<output>/helper/<NN>-<subject>.brief.md` (NN ascending): the question, everything the searcher needs to recognise the right person (names and spellings, year range, places, parents, partner, occupation) and what was already searched.
2. Start it in its own Bash call with `run_in_background: true`, and nothing else in that command: no `&`, `nohup` or redirect to a log file, and no wait loop with `pgrep`. Only so are you woken when it finishes (a `pgrep -f` loop finds itself and never ends):
   `lineage round helper <role> <output>/helper/<NN>-<subject>.brief.md`
   The runner starts the helper (a pane next to yours under herdr, a headless `claude -p` otherwise) and prints the path of the result (`<output>/helper/<NN>-<subject>.md`) when it is done. If it fails (exit 1), the reason is in `<NN>-<subject>.error.txt`. At most three helpers at once per research; the runner waits itself if there are more.
   **If it exits 4** (the inline runner has no helper panes): use the Agent tool instead, with `subagent_type: genealogy-research:dr-<role>` (or the project's own `dr-<role>` if `.claude/agents/dr-<role>.md` exists in the project) and the contents of the brief file as the prompt. Write the result to the same `<NN>-<subject>.md` path.
   **Traffic to a regional archive's image server** (for example the Regional Archive Tilburg): only through `lineage rat ...`, never with `curl` or a loop of your own. The command throttles for all sessions together and goes quiet after HTTP 429 or 403; then stop and do not retry (`lineage rat throttle` shows the state). Parallel downloads that kept retrying once got an IP address blocked for hours. For any other archive site, keep to a test request first and no bursts.
3. Read the result and decide.

**Make assignments big enough.** Every helper starts with its own session, and that costs something too. Give a coherent package, not one record: "the fact check of birth, marriages and death of X", "all children of family F12 in Sprang 1765-1790", "notarial and court archives Dongen 1620-1660 for X". A single `lineage archive show` or a grep you do yourself.

**Check what is decisive.** If a correction, removal or new link hangs on one record, fetch that record yourself with `lineage archive show <ref>` before you decide. A decisive scan whose transcription contains uncertainties you look at yourself. "Nothing found" counts only if the "Searched without result" overview is thorough enough; otherwise give a follow-up assignment. What a helper reports under "deviates", you weigh in your judgement and put in the report; leave it out and the reader sees an identification that looks stronger than it is (one report dropped an age of 61 against 60). And never use a fact as a feature for identification if it comes from the same source you want to link.

Working in parallel is fine as long as the packages are independent (the fact check and the background, say). While helpers work you can carry on yourself; if you only wait for them, end your turn: you are woken when a helper finishes.

## Method

You work in your own git worktree and branch. Your ID block is in the queue: `lineage queue show` lists "ids 800001-800999" next to your person. Use those numbers for new `I`, `F` and `S` records. Scans and helper files go in `<output>/scans/` inside your worktree, including the crops and reductions you read. Never put them in the agent's scratchpad or a temp folder: `lineage round merge` keeps only `<output>/scans/` (under the project's scans folder, as `dr-<ID>`), and the coordinator must be able to reread your finds. In one research the crops were lost this way.

### 1. Prepare

- Read the project file and the project's lessons (see above).
- `lineage person <ID>` and the raw records (person and families) in the tree file (`lineage config path gedcom`).
- Look for earlier findings: grep the ID in the reports folder, the questions file and the log. There is often proof or an open question already. Reuse it, but check it against the current file.
- If the project has correspondence set up (`project.md`), see whether mail about your person is running: `lineage requests --person <ID> --all`. A reply from an archive or institution shows as `reply:` under the request. Read it and process what it yields as a source; a sent request without a reply you do not send again.
- Make a list of all the person's facts: names, birth or baptism, marriages, death or burial, occupations, residences, parents, partners, children and notes. Every fact gets a status later.

### 2. Fact check

Work through the list fact by fact:

1. Find the record (`lineage archive search`, and the sources in `references/sources-nl.md` for the Netherlands; for other countries use the equivalent registers and say which you used).
2. Outcome per fact:
   - **confirmed:** add the citation, if it is not there yet;
   - **corrected:** new value, citation, NOTE with the old value;
   - **range:** for contradictory sources;
   - **removed:** unverifiable, with NOTE.
3. If the index deviates from the file and there is a scan, look at the scan (`lineage scan <ref> --dir <output>/scans`, also where curl gets a 403 or the viewer only works with JavaScript; open it with the Read tool). If you cannot read it, say so. Read scans yourself or through the `scan-reader` helper; do not send them to external vision models (tested: they invented years and names on 17th-century handwriting). A high-resolution crop of the relevant fragment reads better than the whole page. A hand that you and the scan reader cannot read may go to Transkribus (`lineage htr`, if the project has an account): only a crop of the few decisive lines, never a whole register (it costs the user credits), and you reread the result yourself on the scan (models and balance: `references/sources-nl.md`). A year in 18th-century records is often half in words: "1700 Zeeven entagtig" is 1787, not 1777; compute it yourself and check that it fits the record around it.
4. If a site does not work, follow "unreachable sites" in `references/sources-nl.md`: one test request, no hammering, and an HTML page is never a scan.

Cite as `lineage archive show <ref> --gedcom` gives it. Add an `@OA…@` source record only if it does not exist yet (`grep -c '^0 @OA…@ SOUR'`). For other websites make your own source record in your block, with archive, inventory, record or folio and URL in `PAGE`.

### 3. Other registers: life outside the sacraments

Baptism, marriage and burial give a skeleton. The life is in the other registers: where someone lived, what he did, what he owned and whether he met the judge or the newspaper. Per life phase, look at what exists for that time and place (overview in `references/sources-nl.md`):
- population registers and censuses (bevolkingsregister, volkstelling);
- militia and civic-guard (schutterij) registers;
- notarial records, such as wills, sale, lease and division of an estate;
- inheritance-tax declarations (memories van successie);
- court archives and prison registers;
- membership registers of churches (lidmaten), trade licence (patent) and tax registers;
- newspapers (in the Netherlands Delpher): family notices, court reports, advertisements, news. Delpher pages are hard for others to recheck (they load with JavaScript), so always copy the literal text of the item into the NOTE, with newspaper, date, page and Delpher identifier;
- memorial cards (bidprentjes) and genealogical collections.

**Notable facts are the story of a life.** A lawsuit, a complaint before the village court (schout en schepenen: the bailiff and aldermen of an old Dutch village), a pension, a fire, an auction or a newspaper item turn a name with dates into a person. The user finds these the finest discoveries, so do not treat them as a side issue:
- Copy the full text of the regest, record or newspaper item into the NOTE at the event: literally, in old spelling.
- Note who else appears and in what role (witness, opposing party, neighbours), and where it happened (street, house, inn).
- Keep going: is there a sequel in the same protocol or newspaper (judgment, settlement, second item)?
- **Read the marginal notes completely.** In pledge books and protocols a debt often has, years later in the margin, who received the repayment. If the creditor had died by then, those are his heirs, by name and with their husbands as guardian. Such a marginal note can prove a kinship that no record states. So also search for debts in which a sought parent was the creditor. Whoever reads only the record headings at half resolution misses the marginal notes; read them at full resolution for every record with a known name.
- Work it out in the report into a story (see "Stories" in `references/report.md`).
- Store the story in the tree too, so it is visible in every genealogy program. Make a second NOTE at the same event, after the source text, that begins with `Story:` (Dutch projects: `Verhaal:`). It holds what happened, who was there and the explanation of terms. The interpretation (what it says about his life) and the context stay in the report only: the tree contains facts. Break long text with `CONC` and `CONT`, lines of at most 255 characters; use `lineage.edit.text` for that and `lineage.edit.source` for citations (never cut next to a space; BOM and CRLF stay intact).

Record in GEDCOM, always with citation:
- occupation as `OCCU` with `DATE`;
- residence or address as `RESI`;
- property as `PROP`;
- other events as `EVEN` + `TYPE` (for example `Militia`, `Lawsuit`, `Newspaper item`, `Will`);
- a short summary or transcription in a NOTE at the event.

**Project steps for a new place or address.** If the project asks something extra for each new `PLAC` or `ADDR` (such as coordinates for a map), it is in `project.md`; do it in the same step and commit it with it.

### 4. Background: what was going on where he was?

A life story only gets meaning when you know the world it happened in. Why did a shoemaker become a gravedigger, why did a widower sign up for the colonial army, what kind of city was it where he died? So hunt for the background actively. This is a full research step, not a side issue.

The `background` helper does this step. You make the list of life stations (point 1) and put it in the brief; as soon as the fact check has delivered the stations it can start, while you go on with steps 3 and 5. Below is what it does, so you can judge its result. If it reports that it found the person himself in a source, you record that (point 4).

1. **List the life stations:** every place where the person lived, worked, served, married or died, with the years. Include the places his children moved to, if that touched his life.
2. **Per station find what happened there and then:**
   - war and army: garrison, barracks, recruiting depot, wars under way, militia and the draft lottery;
   - disasters and disease: floods, fires, epidemics, failed harvests;
   - economy and work: a local industry, an agricultural crisis, factories, peat, shipping, migrant labour;
   - government and law: the French period, regional borders, reorganisations, poor relief, the church;
   - notable events or sights nearby: a famous visit, a monument, a new railway.
   Sources are in `references/sources-nl.md` (section 4): Wikipedia on the place and the event, sites of local history societies and municipalities, newspapers for local news of those years, and publications with source references.
   Look first in the knowledge base (`lineage config path background`): per place or theme there are already facts with source from earlier researches. Do not check them again, but use them. Add what you newly find: one line per fact, with period and source. Make a new file for a place or theme that does not exist yet.
   Also watch for **images** that fit the life stations: photos, prints, old maps and postcards of the church, street, garrison town or ship. They may go in the life story (rules in `references/report.md`).
3. **Record what you find**, always with a source (URL or publication), in the report under "Time and place". Per statement say whether it comes **from the sources** about the person (with archive source, and for an uncertain identity the word of the certainty scale) or is **context**. Do not use the word "demonstrable" (Dutch "aantoonbaar"): it is not on the scale and was read as "proven" in five rounds. If you cannot find a background statement in a source, leave it out.
4. **Does the person himself appear** in a source about such an event, like a militia list, a casualty list, a newspaper item or a municipal report? Then it is a fact about him: record it in GEDCOM with citation, and work it out under "Stories". Context itself never goes in GEDCOM; it belongs in the report and the life story.

### 5. Parents, partners and children

- **Parents:** does a record (baptism, birth, marriage, death) name the parents, and do they match the family in the file? If not, correct it or remove the link following the rules above. If the kinship is not directly in a record, do not link yourself: follow "Linking without a direct record" in `references/report.md` (a marked link only after a decision of the user; without a record for the kinship, a written-out line of evidence first).
- **Partners:** find every marriage (second marriages too, through "widower of …" in records), with record.
- **Children:** find all baptisms or births with both parents in the fertile years and the family's places of residence. Think of children who died young and of naming patterns. Add missing children as new persons, with record, linked on both sides (CHIL and FAMC). Children in the file without any record are unverifiable, see the rules.

### 6. Queue

Put every newly added family member, and every parent, partner or child not yet in the queue, in it for a round of its own:

```bash
lineage queue add <ID> --via <your person> --reason "father, newly found in baptism record 1788" --round <your round + 1> --priority <n>
```

Priority: parents 2, partners 4, children 5. A lower number goes first. Which line gets priority 1 (the paternal line of a target person, say) is in `project.md`. Possibly living persons are skipped automatically.

The queue works through the direct line only: `queue next` picks only ancestors of the direct line's starting point (see `project.md`). Children and partners outside that line you do put in; they stay open as a side branch until the user releases them. Adding children to your person's family (step 5) is still part of it.

A child who died under 15 years of age and whose birth (or baptism) and death are already fixed with record gives little in a round of its own. Add it and set it to skipped immediately:
`lineage queue skip <ID> --reason "died young; birth and death fixed with record"`.
Change nothing else about the status in the queue; the coordinator does that.

### 7. Report, life story and finishing

- **Test every link before you write the report.** Go through everything you attached to a person: events, occupations, residences from an index, and every new parent, partner or child. Write down per link the two independent features. A feature that itself rests only on a name does not count as independent: in one research a brother carried the identity, but that this brother was the baptised child of 1712 followed only from name and patronymic (case A in `references/report.md`, not proven). "The only baptism in the index" is a search outcome, not a feature. If it is only name, occupation and residence (or name and place), it is not a link: make a NOTE at the person of it ("not linked", with the find place and what is still missing) and an open question. This went wrong twice in one week: a criminal judgment and a notarial record, both on name, occupation and residence alone.
- Write the report following `references/report.md` to the person reports folder (`lineage config path person_reports`, file `<ID>.md`).
- **Blog-worthy?** End the report with a line `Blog-worthy: yes` or `Blog-worthy: no` (Dutch projects: `Blogwaardig: ja/nee`), with one sentence why. Yes is for a story that also fascinates outside the family and has enough sources for a narrative piece with images: a lawsuit or feud, a war or disaster that hit the family, a striking career, a life along poor relief, army or migration, or a trail across several persons or generations (name those persons). Ordinary lives with only baptism, marriage and burial are no. Yes only with a **proven** core finding, or a story that stands without an unproven step. Do not write a blog post yourself; the coordinator proposes it to the user. Whether the project has a blog and what happens to a proposal is in `project.md`.
- **Certainty scale.** Every statement that is not established gets one word of the fixed scale: **proven** (a record with a second feature), **probable** (several independent indications), **presumed** (one pattern or feature), **possible** (name only). Only proven goes into GEDCOM as a fact or link. Summary, NOTE, the questions file and life story use the same word for the same statement (`references/report.md`).
- Then have the **life story** written by the `life-story` helper, to the life stories folder (`lineage config path life_stories`, file `<ID>.md`), following the notes at the end of `references/report.md`. Read it afterwards and commit it. The report is for accountability, the life story for the family: a story you read aloud, built on the found facts. Start with the kinship: `lineage kinship <ID>` computes towards the target persons in the project's settings (`lineage.toml`); who the targets are and how the line to today runs is in `project.md`.
- **Log:** add at the end of the log file (`lineage config path log`) a heading `## <date> · <ID> · <name> (deep research)`, with underneath in a few lines what was found, corrected and removed (with record and find place), what was not searched, the report path and the new queue IDs. `lineage round finish` refuses without such a new heading, because rounds once finished with no log entry and the coordinator had to write seven of them. Write the log in the project language.
- Tick off in the questions file what you solved. Add new open questions under the fitting chapter heading (the chapter headings are fixed: keep the ones in the file, because tools sort the questions by them). A question you treated but did not solve, you rewrite to the current state: what is known now, what is still open, with the sources. Do not paste a "State after round X" behind the old text; the history is in the log and the report.
- **Only available by mail?** If a promising source cannot be reached online or in any other way (screened or non-digitised pieces, museum or private collections, inspection after a privacy stamp), make **no** mail draft yourself. Put the question as an open question at the person in the questions file and in the report's open questions, with `[mail: <institution>]`, the precise find place (access, inventory, URL), what you already searched and what the answer would yield. The coordinator decides whether a mail is really worthwhile and then makes the draft; institutions must not be spammed. Send nothing yourself.
- `lineage validate`: no errors may be added, and warnings about your records you resolve or explain in the report.
- Do the finishing steps that `project.md` names (for example a table that goes with every new place), and the project's own checks or tests if it has any.
- The note `Deep research <dd-mm-yyyy>: <report>` at your person is added by the coordinator when merging. Do not add it yourself (the CLI recognises exactly this marker).
- The tree file stays UTF-8 with BOM and CRLF (`file <gedcom>`).
- **Commit per step**, with a message that says what and on which record, for example `I12: death Northfield 7-4-1822 (civil registry deaths Northfield 1822, record 12)`. Follow the project's commit conventions in `project.md` (attribution lines and the like). Do not commit `<output>/`: that folder is in `.gitignore` and stays out of git (no `git add -f`); what lasts belongs in the report, the tree or the knowledge base. Committed helper files collided at merge, because every round uses the same names.
- **Account in the heading:** name in your report section's heading the account from `cat <output>/account` (and after a resume both), not from memory.
- **A decisive reading that stays uncertain** (a name on which a link depends): put the full scan and the crop in `<output>/scans/`, name the file names under "For the coordinator" and say which letters are uncertain. The coordinator puts them to the user (how is in `project.md`).
- **Lay the certainty words side by side.** For every core statement (a link, an identity, a kinship) look up the word of the scale in the summary, the NOTE, the questions file (the questions you rewrote too: is an old "presumed" still in front?), the log and the life story. They must be equal. This went wrong twice in one day.
- **A helper's reading is never proven.** Search your report and NOTEs for "read by helper" (or "helper agent") and see whether "proven" stands next to it. Then read that scan yourself, or make it "probable". A death was once called proven on a helper's reading.
- **A correction touches more than one record.** If you correct a date or name that also stands at a partner, a child or in another life story, name under "For the coordinator" where else the old value stands. Outside your reach you change nothing; the coordinator sets it right. A record that is in your brief (a follow-up round started with `--brief`) is within your reach: you correct that yourself, with NOTE, report and life story. If you correct what a source or earlier researcher says (a regest, a published study), first reread that source completely: perhaps it says it elsewhere already.
- **Diff check, just before `lineage round finish`.** Lay every statement in the report under new, corrected, removed and "Added to the queue" next to `git diff main -- <gedcom> <queue>` (paths from `lineage config path`). What the report names but is not in the diff, you carry out after all or remove from the report (and from summary, log and life story). Count this round's Transkribus recognitions (`find <output> -path '*/htr/*.txt' | wc -l`) and name that number exactly in the report and the log, also when it is 0 (write "0 Transkribus recognitions"). A reading by a helper or by Transkribus that you did not reread yourself on the scan is not called proven in the report.
- Finish with `lineage round finish`: it checks that everything is committed and that there is a log heading, runs `lineage review <ID>` (records outside your reach, old values without NOTE, a corrected value that still stands elsewhere, removed rows in the coordinate table, the number of Transkribus recognitions against the log, the account in your report heading, the queue against your report) and refuses on an ERROR; a WARNING you resolve or explain in the report. Then the script reports the research to the coordinator as finished and shortly afterwards closes this research's tab. End after that in the terminal with one line: `DONE <ID>`.

## Mail, forum and other external steps

Mail to archives, forum posts, Gramps Web and similar services exist only "if the project has it set up" (`project.md`). If it does not, skip those steps and record such questions as plain open questions. Where it does, the rules are the project's, and the privacy rule above still applies: nothing about living persons.

## References

- `references/report.md`: certainty scale, linking without a direct record, report template, life story template and notes.
- `references/sources-nl.md`: sources for Dutch research, Transkribus, unreachable sites.
- `references/lessons.md`: general lessons from earlier rounds. Project-specific lessons are in the project's own `lessons.md`.
