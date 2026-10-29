# General lessons from reviews of deep-research rounds

Patterns that recurred across many rounds and reviews, without project details. Project-specific lessons (with person IDs and dates) belong in the project's own `lessons.md` next to `project.md`; add a line there per review: date, round, what the review found (or "nothing"), and whether it is a known pattern. The coordinator's own mistakes belong there too. When a pattern keeps coming back, it becomes a rule in the skill or a check in `lineage review` (see the `coordinate` skill, improvement round).

## Certainty

- **The scale word drifts between documents.** The same statement is "presumed" in the questions file, "probable" in the report and "almost certain" in the life story. Look the word up in every place (summary, NOTE, questions, log, life story) and make them equal. Rewritten questions often keep an old word at the front.
- **Words off the scale creep in** ("demonstrable", "almost certain", "undoubtedly"). The skill itself once asked for one as a label; the fix was to contrast "from the sources" with "context". `lineage review` flags these words.
- **Certainty is lost in a derived statement.** A sum that includes an uncertain amount, a gap in days computed from a doubtful date, "two grown children" where one is only probable, "so together": the uncertainty of a part disappears in the derived sentence. Recompute derived statements from the certain parts only, or carry the uncertainty along.
- **A chain of derived identities counts as one feature.** If feature two (a brother, a godparent) is itself identified only by name and patronymic, the link is case A (kinship in a record, identity derived), not proven. "The only baptism in the index" is a search outcome, not a feature.
- **Name plus occupation plus residence is not a link.** Judgments, notarial records and index hits matched on these alone were wrongly attached to a person more than once. Make a "not linked" NOTE and an open question instead.
- **A new FAMC whose NOTE derives the identity needs QUAY 1.** If the NOTE says the identity "rests on" patronymic, naming or birthplace, the link is probable at best (case A). `lineage review` warns when it sees this; it is also a false alarm when the link actually rests on another record (a division of an estate naming both parents, a marriage record). Say in the report which record carries the link.
- **Merging name forms without a record.** Equating two spellings or patronymics ("Aertsen" and "Arts") as one person was stated as fact more than once. Without a record, make it a probable equation in a NOTE.

## Helpers and readings

- **A helper's reading is never proven.** A death, a marginal note or a year read by a helper agent must be reread by the research lead on the scan, or called probable. A marginal note once turned out to be nine years later than the helper read, because a year written as words ("seventeen hundred and eighty seven") was converted wrongly. The scan reader must give year words literally and the conversion separately.
- **Index lines can mean the wrong person.** An explanation based on an index line alone ("concerns the children and heirs of X") may refer to another X. The later round that reads the full record corrects the earlier one: the coordinator then fixes the earlier person's report, NOTE and life story.
- **An index gives the death day as the burial date.** Check the record before using the date as a burial.
- **A review agent does not know the scale well.** Give it the definitions of the certainty scale. It may propose words off the scale, and it can raise false alarms (two different baptisms in one year taken for a contradiction; an old value that was a helper's reading). Check its findings against the scan.
- **A normalised reading quoted as literal.** A quote in the report must be what the scan says, not the modernised spelling or the name you expected.

## Corrections and follow-up rounds

- **A correction touches more than one record.** A date or name corrected in one report still stands in a partner's record, a child's, another life story. Name where else the old value stands, so the coordinator can fix it, and read the whole source before you correct what a source or earlier researcher says (it may say it elsewhere).
- **"Outside my reach" for a record that is in the brief.** A record named in the assignment is inside the reach. Leaving its corrections undone is a recurring mistake.
- **A follow-up round leaves the old text behind.** New findings added at the bottom while the summary, a candidate list, "almost certain" or "not searched" above contradict them. Mark old parts as replaced or rewrite them, and carry a helper's marginal reading into NOTE and life story as such.
- **Commit a repair in the worktree at once.** An uncommitted fix was lost when another session merged and removed the worktree.
- **Over-long GEDCOM lines.** Adding a sentence to an existing note can make a `CONC` line longer than 255 characters; `lineage validate` may not say so, `lineage review` does.

## Sources and scans

- **Scans in a scratchpad are lost.** Crops and downloads belong in `<output>/scans/`; only that folder is kept at merge, and a reviewer must be able to reread them.
- **Read the marginal notes.** Repayments, heirs and kinship hide in the margin of protocols and pledge books; read them at full resolution.
- **Build a line of evidence from the reports of all persons involved**, not only from the report of the person at hand. A neighbouring round may already have weakened a candidate or read the tax register.
- **A parallel site burst gets the IP blocked.** Use the project's throttled command for archive images; stop at the first 429 or 403.
- **A review or a regeneration of a document can invent a "contradiction".** Verify a flagged contradiction on the record before changing anything.

## Operations

- **A full disk while merging.** If the copy of scans to the project folder fails with "No space left on device", do not remove anything. Leave the worktree standing, check half-copied scans with `cmp`, make room, delete the half-copied folder, and run the merge again. A merge script that continues to the worktree removal after a failed copy would lose the scans; stop at the first error.
- **A watcher behind a sleeping loop.** A background watcher started behind a `sleep` loop reported "quiet" again and again. Start long-running watchers in their own process, not behind a loop in the session.
- **Do not take an ID from another round's block.** The coordinator's own records get an ID from the coordinator block, never from a running round's block.
- **Check the output of a wait loop.** `pgrep -f` finds itself; use the runner's notification instead.
- **Transkribus model without explanation.** If the non-default model was used, say why in the report. Not scriptable; the review agent catches it.
- **Blog follow-ups state more than the reports.** Reread any derived text (blog, summary for a third party) against the reports sentence by sentence.
