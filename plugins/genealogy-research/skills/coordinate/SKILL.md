---
name: coordinate
description: Coordinate several parallel deep-research rounds in a genealogy project. Pick what to start from the queue, start rounds in their own worktrees, watch them, review each report against the diff, merge, and handle limits, accounts and mail requests. Invoke by hand (`/coordinate`); needs a runner that can run rounds in parallel.
disable-model-invocation: true
---

# Coordinating the queue

For the session that steers several deep-research rounds. Agents do the research itself, each on one person, in its own worktree and branch (see the `deep-research` skill). You choose what gets started, watch progress, review reports and merge them.

Read `lineage config runner` first. With `inline` there is nothing to coordinate: an inline runner runs one round per session, in the session itself, and the user starts the next one by hand. Parallel rounds need `hc`, `herdr` or `headless`.

Then read `<research>/project.md` (research folder: `lineage config path research`). It holds what is specific to this project: target persons, the direct line, the stems and their precedence, the current limits on rounds and accounts, machine facts, what must happen after a merge (update a site, propose a blog post), and which optional services the project uses (Gramps Web, a forum, paternal-line notices, mail). Everything below applies to every project. Read the project's lessons too (`lineage config path lessons`), if the file exists.

Write reports, log lines, questions and request letters in the project language (`lineage config value language`).

## Queue

Queue file: `lineage config path queue`, edited with `lineage queue ...`:

| Command | Purpose |
|---|---|
| `show [--all]` | open and running items, with round, priority and ID block |
| `add <ID>... --reason ... [--via <ID>] [--priority n] [--round n]` | add; existing items stay; possibly living persons are skipped automatically |
| `next` | the next open item that shares no family with running work |
| `start <ID>` | status in progress, with its own ID block of 999 numbers; refuses when a family is shared with running work |
| `done <ID> --report <path>` | finish |
| `skip <ID> --reason ...` | do not research |
| `normalize` | after a merge: merge duplicate lines (the most advanced status wins) |

**Direct line first:** `queue next` and `queue show` limit themselves to ancestors of the start of the direct line (`project.md`) and running work. Open items in side branches stay but are not started; `--side-branches` shows or picks them anyway. **Stem items always come first:** the men of a stem and all their wives, including a first or second wife the line does not descend from, are never a side branch. **The user's picks come before all of that:** an item with priority 0 (`queue add <ID> --priority 0`, only on the user's request) is started first, also in a side branch.

**Order of the stems:** which stems exist, in which order and from which person, is in `project.md`. `queue next` picks first by stem (the father-to-father line with the wives of those men; built-in default `STEMS` in `queue.py`, or `stems.tsv` next to the queue with `name<TAB>ID[<TAB>men-first]` per line), and within a stem by round and priority. A follow-up round is not an open item in the queue: if the oldest man of a higher stem has a worthwhile follow-up round, start that before the open item `queue next` names.

Order: lowest round first, then lowest priority, with the precedence from `project.md` (start the line that takes precedence there first, even if `next` picks someone else). A finished person gets a follow-up round with `lineage round start <ID> --follow-up`, a targeted brief with `--brief <path>` (the file must be committed in main). The user can add persons with a low priority number to let them go first.

## Starting

```bash
lineage round start <ID> [--model opus|sonnet]
```

The script:
1. sets the person in progress in the queue and commits that in `main`;
2. creates the worktree `.worktrees/dr-<ID>` on branch `dr/<ID>`;
3. starts the research lead through the runner (hc: a terminal `dr-<id>` in its own tab `<ID> <person>` in your space of the Herdr app, labelled `lineage.round=<ID>`, its helpers as its child terminals; herdr: its own tab named after the person, the tab ID in `<output>/runner-tab` of the worktree; headless: a background process, `<output>/leader.pid` and `leader.log`);
4. gives it the brief.

`<output>` is `lineage config path output` inside the worktree. The lead starts its helper agents itself with `lineage round helper` (see "Division of labour" in the `deep-research` skill). At the end the lead runs `lineage round finish`, which writes `<output>/DONE` in the worktree and closes the tab (hc: the terminal). The report, the commits and the helper results (`<output>/helpers/`) stay in the worktree for your review.

Pick the model by person: `opus` for everything before about 1850 and for complicated cases, `sonnet` can do for well-documented 19th and 20th century persons.

**Account.** The account names come from `lineage config accounts` (one line per account, `name<TAB>config_dir`; without `[accounts]` a single `default`). A new round starts on the first account listed in `<git-common-dir>/dr-accounts` (without that file: the first account from the config). Which accounts are allowed is in `project.md`. Helpers inherit their leader's account; the account of a round is in `<output>/account` of the worktree.

**Undoing a round that has done nothing yet** (to give its slot to another, or because it was started wrongly): `lineage round undo <ID>`. It closes the tab (hc: the terminals), removes worktree and branch and reverts the queue commit of the start. It refuses as soon as the branch has commits, the worktree has changes or `<output>/DONE` exists.

**The coordinator's own records** (for example a marked link after a decision by the user): take an ID block that is not in the `id_block` column of the queue (`awk -F'\t' '$8!=""{print $8}' <queue> | sort -n | tail`) and not in the tree. The highest ID in the tree plus one is wrong: that block may already be assigned to a running round, and the record would have to be renumbered. A round started later skips blocks that are in the tree.

**The guard.** Switching accounts is done by the guard, a plain loop without Claude (hc: the terminal "guard"; herdr: in its own tab), so it keeps going even when the coordinator itself is at its limit. Start it at the beginning of a coordination session with `lineage round start-guard` (does nothing if it already runs, also when it runs from cron). With hc it can run from cron instead: `lineage round start-guard --cron` installs a crontab line that runs one pass (`lineage guard --once --coordinator`) every two minutes and closes the guard terminal; then the user can close every session while waiting for a limit, and the guard starts a coordinator once an allowed account has room. `--no-cron` removes the line. Every two minutes it looks at each round that is not done. If the screen of a stalled lead or helper shows a reached usage limit ("You've hit your ... limit, resets ...", also the weekly limit with a date; the warning "You've used 76% of ..." does not count), it records the reset in `<git-common-dir>/dr-limit-<account>` and resumes the round on an account with room, with the model and brief from `<output>/model` and `<output>/brief`. If all accounts are full, it waits until the earliest reset and then resumes. A lead that is gone two rounds in a row while the research is not done is resumed too. It merges nothing and starts no new research. Log: `<git-common-dir>/dr-guard.log`; `lineage guard --once --dry-run` shows what it would do now. It logs one line per pass: per round the account, the status of the lead, the number of helpers and the action, plus the state of the accounts and of the coordinator.

With `--coordinator` (how `start-guard` starts it) it also guards the coordination itself: `lineage round watch` writes a heartbeat per pane into `dr-coordinator.alive.d/` every loop. If there has been no heartbeat for half an hour and no agent `coordinator` runs, it starts one with `lineage round start-coordinator <account>` (hc: terminal "coordinator"; herdr: own tab "coordinator"; opus, auto mode, on an account with room); if that one hits a limit it restarts it on the other account; if it stands still without a watcher it nudges it once per half hour. There is only ever one coordinator: if the watcher of another session (another pane than the auto-coordinator's) beats, the guard closes the auto-coordinator (its terminal or tab) as soon as that stands still and main is clean (never in the middle of a merge). A session that coordinates itself therefore always starts the watcher. While the guard runs (heartbeat `dr-guard.alive`), `watch` leaves switching to it; without a guard `watch` does it itself, but only at the session limit. `DR_AUTO_SWITCH=0` turns that off. `--account auto` picks by itself: the round's previous account if free, otherwise another; with `--resume` that is the default. New rounds start on the first allowed account, even if that is at its limit: then pick another allowed account or `auto` yourself.

**Limits on rounds and accounts.** In `<git-common-dir>/dr-max-rounds` (one number) and `dr-accounts` (the allowed account names, from `lineage config accounts`). The guard resumes a round only if fewer leads run than the limit and picks only allowed accounts; `lineage round start` starts on the first allowed account by default and refuses another. If the limit is 1, start a new round only after the previous one is merged, and first resume a round that still waits for a slot (a worktree without `<output>/DONE` and without a lead) with `lineage round start <ID> --resume` before taking someone new from the queue. If the user wants more in parallel or another account, change those two files (empty or absent = no limit, all accounts). The current state and temporary agreements are in `project.md`; update it when the user changes the limit.

**How many at once.** A round is an agent (about 300 MB), and every helper is an agent too: `lineage round helper` starts no new one while 24 agents run in total (`DR_MAX_AGENTS`) or the round already has three (`DR_MAX_HELPERS`). Machine facts (memory, cores) are in `project.md`; check with `free -h` and the load average. Run at most five rounds at once unless `project.md` says otherwise: not for the memory, but because the coordinator must review every report before it is merged, and with helpers each round counts double or triple. If it gets tight, stop finished agents before starting new ones.

**Writing and background agents too** (for example rewriting life stories) work in their own worktree and branch, never in the directory of `main`. Otherwise uncommitted changes sit in `main`, and `round start` and `round merge` rightly refuse, so the whole queue stands still.

## Watching

Start the watcher in the background (Bash with `run_in_background`):

```bash
lineage round watch
```

Every two minutes it looks at all worktrees and stops as soon as there is something new to report: done (the lead ran `round finish`), blocked (a permission prompt), limit (usage limit recognised; the round has been resumed on the other account, or all accounts are stuck), quiet (lead idle without running helpers and without a limit message, two measurements in a row: stuck) or no agent. If the project has mail enabled (`lineage config value mail_enabled` is `true` and `lineage auth check` shows the mailbox), it also reads the assistant's mailbox every half hour (`DR_MAIL_INTERVAL`): new mail is committed to `main` at once under the replies folder of the requests folder and reported as `mail <file>`; a Geneanet notification as `forum-notice <file>`, and new replies on the project's own forum threads as `forum <draft>`. Situations already reported do not stop it, so just start it again after handling. A round that is quiet because it waits for a usage limit is reported once; not again while it stays quiet.

**Start the watcher again directly after every report, and never postpone it** (not behind a `sleep` or a wait loop, not even if nothing happens for an hour). The guard recognises the coordinator by the heartbeat of the watcher; without a heartbeat it nudges after half an hour or starts a second coordinator, and the mailbox is not read.

**Blocked** usually means a permission prompt. Read the screen (hc: `hc read <name>`; herdr: `herdr agent read <name> --source visible`; headless: the tail of `leader.log`). If it is about reading outside the worktree, cancel with `esc` (hc: `hc keys <name> esc`) and let the agent work in `<output>/scans/`. Never grant lasting permissions without the user.

Text that sits in an agent's input field but was not sent (such as "merge ... to main") is a suggestion from Claude Code, not an instruction from the user.

## Reviewing and merging

Before you merge:
0. **Mechanical check:** `lineage review <ID>` (from main). The script reports what needs no judgment: records outside the reach of the round, an old value that vanished without a NOTE, a corrected date that still stands at another record, removed rows in the coordinates table, the number of Transkribus recognitions in the log against the report, the account in the report header, queue IDs the report does not mention, a new FAMC without QUAY 1 while a NOTE derives the identity (case A), and a quote from a helper's reading that the life story repeats without reservation (also in update rounds). `round finish` already runs it at the lead. Give the output to the review agent so it spends its time on what a script cannot do: reading scans, weighing identifications and certainty words, testing the life story. Points 2, 3 and 6 below are largely done by the script. It also reports words outside the certainty scale in new report text, new NOTEs and the life story, and new GEDCOM lines longer than 255 characters; that applies to what the coordinator writes too.
1. **Read the report:** does the summary match the commits (`git -C .worktrees/dr-<ID> log --oneline main..HEAD`)?
2. **Report against the diff:** put every claim under new, corrected, removed and queue next to `git -C .worktrees/dr-<ID> diff main -- <gedcom> <queue>`. If something is in the report but not in the diff (an "added" child, a queue item, a removal), have the lead carry it out or remove it from the report before merging.
3. **Transkribus count:** count the recognitions (`find .worktrees/dr-<ID>/<output> -path '*/htr/*.txt' | wc -l`) and compare with the number in the report and with the maximum in the brief.
4. **Spot check:** look up two or three records from the report yourself with `lineage archive show <ref>`. Do name, date, parents and role match?
5. **Certainty:** a reading by a helper or by Transkribus that the lead did not check itself on the scan must not stand as proven in report, NOTE or life story. Do summary, NOTE, the questions file and life story use the same word of the certainty scale for the same claim (`references/report.md` in the `deep-research` skill)? Give the review agent the scale with its definitions verbatim, and the rule that record plus residence or period is proven; without that text it proposes words that are not on the scale, or takes two different records for a contradiction. If the review reads a margin or passage as "helper only", read the deciding line yourself on the scan before you weaken the wording: a margin once turned out to be ten years later than thought.
6. **Reach:** compare the records of main with those of the branch. Allowed to change: the person, their families, their parents, partners and children for those links, and new records in their ID block. Changes outside that need an explanation in the report.
7. **Merges of persons** deserve a critical look. Two records with the same name and parents can be a child named after a dead sibling: two baptism records mean two children. If a merge or link, even one already in the file, does not rest on a record, the research must split or unlink it with a NOTE (see the principles in the `deep-research` skill).

Then:

```bash
lineage round merge <ID>
```

The script:
1. merges the branch, keeping both sides of log, questions, queue and reports;
2. normalizes the queue and removes duplicate source records;
3. sets the person to done, adds to them in the tree the note `Deep research <date>: <report>` (an earlier round's is replaced), and validates and tests;
4. keeps the scans in the project's scans folder (outside git);
5. closes the round's tab (hc: its terminals) if still open, and removes worktree and branch;
6. removes Claude Code's temp folders (`/tmp/claude-<uid>/...--worktrees-dr-<ID>`) of every worktree that no longer exists. They would otherwise stay and fill the /tmp quota, after which Bash output and `mktemp` fail.

With `--keep` worktree, branch and tab stay.

**After the merge** come the steps `project.md` names: for example update a site, a blog proposal at `Blog-worthy: yes` (Dutch: `Blogwaardig: ja`), a notice when a line became one generation longer. A blog post is never written by the lead itself; it comes only after the user's choice.

**Question map.** After the merge (and after updating the questions file): `lineage question-map` and republish the page `reports/question-map.html` where `project.md` says (for example to the same artifact URL; pass the `url` when publishing from another session). Commit the question-map history table with it: every update is a measuring point in the progression.

**Have blog text read first.** A blog post or follow-up the coordinator writes goes online only after a subagent (sonnet) has tested every factual claim against the reports: certainty words, quotes verbatim, dates and finding places, and the scope of what was searched ("page by page", "none" versus "not found"). In one follow-up that check found eleven points that were firmer than the reports.

**An uncertain deciding reading.** If a lead names under "For the coordinator" (in a Dutch report "Voor de coördinator") a reading that stays uncertain and on which a link depends, put the scan and the crop to the user as `project.md` says, with the readings of the models and of the lead next to it.

**A reading that refutes an earlier round.** If a round reads a record that an earlier round had only interpreted from the index (a case where "this concerns the children and heirs of X" was taken as the death of the wrong X), correct report, NOTE and life story of that other person and record the old interpretation in the NOTE.

**Corrections to other records.** After merging, `lineage round merge` names the life stories that now lag. If the round corrected a date or name that also stood at relatives (see the NOTE lines of `lineage review` and "For the coordinator" in the report), fix that yourself in the GEDCOM, with a NOTE about the old value, and plan update rounds for the stories named. Limit every text replacement in the GEDCOM to the records you mean (`lineage.edit.record` and `block_end`), never the whole file: a phrase like "twenty years after" also occurs in other persons' NOTEs, and a blind replacement changes them (and can break words). `round merge` then reports them as outside the reach of the round.

**Recording lessons.** After every review add one line at the bottom of the project's lessons file (`lineage config path lessons`): date, round, what the review found (or "nothing"), and whether it is a known pattern. Your own mistakes as coordinator belong there too.

Then give the user a short summary per person: what is new, what is corrected and what is removed, and who was added to the queue. Say which choices are the user's.

**Links without a direct record.** Check every new parent, child or partner link against "Linking without a direct record" in `references/report.md` of the `deep-research` skill:
- Is it proven?
- If not: does the relationship appear in a record (case A) or nowhere (case B)?
- Is the marking present (QUAY 1 and a NOTE)?
- Is there a decision by the user?

A probable link without a decision goes to the user. A case B link without reasoning you remove (it becomes a NOTE) before merging.

## Rounds in another agent runtime

A round may run in another agent tool (for example opencode through a model gateway) only if the project's `CLAUDE.md` or `project.md` allows it, and with which data restrictions. Weaker models tend to report changes as done that are not in the diff, and to invent sources, so:

- **Full review** of every such round, not a spot check: the whole report against the diff (point 2 above) and at least ten records looked up yourself with `lineage archive show <ref>`. What is wrong, Claude repairs (a follow-up round or a repair in the worktree) before you merge.
- **Hard requirements in the brief**, always: everything the report calls new is in the diff; the queue is really updated (`lineage queue add`, not only in the report); only sources the agent opened itself; check ages and relationships against the records; the diff check from the `deep-research` skill at the end.
- **Brief through a file.** Long prompts do not arrive through a pane prompt in such tools. Put the brief in a file in `<output>` of the worktree and send one short line ("Read <output>/<file> and carry it out.").
- **No `<output>/account`** in such a worktree: the guard would otherwise resume the round on Claude at a limit. That holds as long as `round start` has no option for another agent runtime.

## Updating life stories

A life story is written on the report of that moment. Later research (a child, a parent, a follow-up round) records new facts in the tree, and then the story lags. Git dates both sides, so no date is needed in the story:

```bash
lineage stale                  # stories whose record changed after the story, with the commits
lineage stale --short          # IDs only
lineage stale <ID> <ID>        # only these persons
```

A story counts as lagging when the last commit to the person's own record, one of their families (FAMS) or a child in those families is younger than the last commit to `<reports>/life-stories/<ID>.md`. So touched family members make the list too: whoever researches a child puts the parents on the list. The note `Deep research <date>` does not count as a change, and neither does re-wrapping long lines with CONC: a flag stays only if the text of the record, CONC joined, now differs from that at the commit of the story. The `git blame` takes half a minute and is cached per version of the GEDCOM (`<git-common-dir>/dr-stale-cache.json`).

Updating runs as a light round, so watcher and merge treat it the same:

```bash
lineage round start <ID> --update-story     # sonnet by default
```

No queue, no ID block, no helpers: one lead in its own worktree and tab (name with "(update)", marker `<output>/stale`) that only rewrites `<reports>/life-stories/<ID>.md` on the new facts, and completes the report if a fact is in the tree but not in the report. It ends with `round finish`, so `watch` reports it as done. Check that the tree was not touched (`round merge` refuses otherwise) and read the story. If the story stayed unchanged, `round merge` records the check in the stories-checked table, so the story does not keep surfacing. Update rounds count towards the round limit, but are short; take one between the researches as soon as a slot frees up, and the direct line goes first.

If an updated life story must go somewhere afterwards (a site, a note), `project.md` says so.

## Improvement round

`round merge` counts the merged rounds (`<git-common-dir>/dr-rounds-since-improvement`) and at ten (`DR_IMPROVE_AFTER`) reports "time for an improvement round". Then:
1. Read the project's lessons file from the previous improvement round (the last heading `## Improvement round <date>`).
2. Find the patterns: what came back more than once, or cost the user a correction?
3. If a script can establish it (a count, a comparison of two files, a line that disappears), build it into `lineage review` (`review.py`, with a test) or into one of the round scripts. If it takes judgment, write a short rule in the `deep-research` skill, its `references/report.md`, or this file, at the step where it went wrong, with the example.
4. Under the lessons put a heading `## Improvement round <date>` with what you changed, and set the counter to 0: `echo 0 > "$(git rev-parse --git-common-dir)/dr-rounds-since-improvement"`.
5. Validate, test, commit, and give the user a short summary. Changes to `CLAUDE.md` or `project.md` go to the user first. Changes to the plugin's own skills are changes to a shared tool: say so, and let the user decide how they reach other projects.

## Requests by mail

This section applies only when the project has mail enabled (`[mail] enabled = true` in lineage.toml, `lineage config value mail_enabled`) and the mailbox is set up (`lineage auth check`). Without it, requests stay drafts in the requests folder for the user to send.

Sources that can only be obtained by mail (an archive, museum or private person) are drafts in `lineage config path requests`, one file per request with address, subject and mail text (see the `deep-research` skill, the step on requests). The coordinator sends them from the assistant's own mailbox, following the project's rules on correspondence in `CLAUDE.md`: only when every other source is exhausted, and only after the user's explicit approval of that one draft. Never send a draft without it. Show drafts with their full text (`--text`).

```bash
lineage requests                 # open requests (draft and sent)
lineage requests --text          # drafts still to be sent, with full mail text
lineage requests --mark <name> sent|answered|closed
```

```bash
lineage mail test                       # check login
lineage mail send <name> --approved     # only after the user's approval; sets status sent and message-id
lineage mail inbox                      # new mail into the replies folder, linked to the request
```

The watcher reads the mailbox every half hour and reports new mail as `mail <file>`; read it yourself too at the start of a coordination session (`lineage mail inbox`, then commit). Research leads see replies at preparation through `lineage requests --person <ID>`. Process every reply with a source (log, questions, report, or a follow-up round with `--brief`), mark the request `answered` or `closed`, or propose a follow-up mail as a new draft.

Mail sparingly: do not spam institutions. Do not stockpile held drafts. Questions that can only be answered by mail are open questions at the person in the questions file, tagged `[mail: <institution>]`. Make a draft of them only when the question is really worth it, every other source is exhausted, no mail without a reply is pending at that institution and that institution has not just replied; then bundle all `[mail: ...]` questions for that institution into that one mail. No reminders shortly after a mail. Never put two mails to the same institution to the user at the same time. Check that the address really belongs to the institution. A mail the user sent themselves gets sender `user`: the reply then arrives in the user's own mailbox. When a reply comes, a follow-up round or the coordinator processes it with a source, and the request becomes `answered` or `closed`.

## Optional project services

Only if `project.md` says the project uses them:
- **Gramps Web** (`lineage gramps sync`): run after merging a round, after a blog post, after (re)writing life stories and after updating the questions.
- **Geneanet forum** (`lineage forum post|read`): only for what `project.md` allows; mail notices from the forum are filed separately by `lineage mail inbox`.
- **Paternal-line notice** (`lineage paternal --notify`): after a merge, when the direct line got one generation older.
- **Coordinates** (`lineage coordinates fill`): when `validate` reports places without a row.
