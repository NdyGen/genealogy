# Glossary: Dutch to English

Fixed translations for the move from ndygen to lineage. Every module, test, script, skill and agent uses these names. Add a term here before using a new translation.

## Modules

| Dutch | English |
|---|---|
| `aanvragen.py` | `requests.py` (module `lineage.requests`; never `import requests` from the third-party package inside it) |
| `archief.py` | `archive.py` |
| `bewaker.py` | `guard.py` |
| `bewerk.py` | `edit.py` |
| `bijwerken.py` | `stale.py` |
| `boek.py` | `book.py` |
| `controle.py` | `review.py` |
| `coordinaten.py` | `coordinates.py` |
| `gramps_lezen.py` | `gramps_read.py` |
| `grampsboom.py` | `gramps_tree.py` |
| `vaderlijn.py` | `paternal.py` |
| `verwantschap.py` | `kinship.py` |
| `vragenkaart.py` | `question_map.py` (and `question_map.html`) |
| `wachtrij.py` | `queue.py` (module `lineage.queue`) |
| unchanged | `browser.py`, `checks.py`, `cli.py`, `dates.py`, `forum.py`, `gedcom.py`, `gramps.py`, `graph.py`, `htr.py`, `mail.py`, `merge.py`, `rat.py`, `reports.py`, `scan.py`, `web.py` |

## CLI

Global: `--bestand` becomes `--file` (it goes before the subcommand, as before: `lineage --file x.ged person I1`). The console script `ndygen` becomes `lineage`.

| Dutch | English |
|---|---|
| `overzicht` | `summary` |
| `valideer` (`--niveau`) | `validate` (`--level`) |
| `zoek <woorden>` | `search <words>` |
| `persoon <id>` | `person <id>` |
| `kwartierstaat` | `ancestors` (`--generaties` becomes `--generations`) |
| `parenteel` | `descendants` |
| `boom` (`--richting voorouders/nakomelingen`, `--uit`) | `tree` (`--direction ancestors/descendants`, `--out`) |
| `controle` | `review` |
| `bijwerken` (`--kort`, `--gecontroleerd`, `--rechte-lijn`) | `stale` (`--short`, `--checked`, `--direct-line`) |
| `aanvragen` (`--alles`, `--persoon`, `--tekst`, `--markeer`) | `requests` (`--all`, `--person`, `--text`, `--mark`) |
| `mail test` / `mail verstuur <naam> --akkoord` / `mail postvak` | `mail test` / `mail send <name> --approved` / `mail inbox` |
| `gramps status` / `gramps bijwerken` (`--droog`, `--overschrijf`) | `gramps status` / `gramps sync` (`--dry-run`, `--overwrite`) |
| `coordinaten index` / `zoek` (`--adres`, `--jaar`) / `aanvullen` | `coordinates index` / `search` (`--address`, `--year`) / `fill` |
| `boek` (`--uit`, `--jongste-eerst`) | `book` (`--out`, `--youngest-first`) |
| `verwant` (`--naar`, `--doelen`) | `kinship` (`--to`, `--targets`) |
| `vaderlijn` (`--vanaf`, `--meld`, `--staat`) | `paternal` (`--from`, `--notify`, `--state`) |
| `vragenkaart` (`--vanaf`, `--vragen`, `--historie`, `--uit`; default `rapporten/vragenkaart.html`) | `question-map` (`--from`, `--questions`, `--history`, `--out`; default `reports/question-map.html`) |
| `wachtrij` (`--wachtrij`) | `queue` (`--queue`) |
| `wachtrij toon` (`--alles`, `--zijtakken`) | `queue show` (`--all`, `--side-branches`) |
| `wachtrij voeg-toe` (`--door`, `--reden`, `--prioriteit`, `--ronde`) | `queue add` (`--via`, `--reason`, `--priority`, `--round`) |
| `wachtrij volgende` | `queue next` |
| `wachtrij start` (`--forceer`, `--vervolg`) | `queue start` (`--force`, `--follow-up`) |
| `wachtrij klaar` (`--rapport`, `--datum`, `--geen-notitie`) | `queue done` (`--report`, `--date`, `--no-note`) |
| `wachtrij overslaan` | `queue skip` |
| `wachtrij normaliseer` | `queue normalize` |
| `archief zoek` (`--plaats`, `--rol`, `--bron`, `--aantal`, `--type`) / `archief toon` | `archive search` (`--place`, `--role`, `--source`, `--limit`, `--type`) / `archive show` |
| `rat zoek` / `stuk` / `download` (`--map`) / `rem` (`--vrijgeven`) / `uitsnede` (`--vergroot`) ; `--toegang`, `--aantal` | `rat search` / `item` / `download` (`--dir`) / `throttle` (`--release`) / `crop` (`--scale`) ; `--fonds`, `--limit` |
| `bewaker` (`--eenmalig`, `--droog`, `--coordinator`) | `guard` (`--once`, `--dry-run`, `--coordinator`) |
| `scan` (`--map`) | `scan` (`--dir`) |
| `htr` (`--tel`, `--sinds`, `--droog`) | `htr` (`--count`, `--since`, `--dry-run`) |
| `forum plaats` (`--voorbeeld`) / `forum lees` (`--map`) | `forum post` (`--preview`) / `forum read` (`--dir`) |

Positional arguments: `zoek <woorden>` is `search <words>`, `archief zoek <naam...>` is `archive search <name...>`, `rat zoek <termen...>` is `rat search <terms...>`, `rat stuk|download <inventaris>` is `rat item|download <inventory>`, `rat uitsnede <bestand> <kader>` is `rat crop <image> <frame>`, `htr <beelden>` is `htr <images>`, `mail verstuur <naam>` is `mail send <name>`, `forum plaats <bestand>` is `forum post <draft>` (not `file`, which would clash with the global `--file`). `wachtrij toon --alles/--zijtakken` and `wachtrij volgende --zijtakken` are `--all` / `--side-branches`.

Help texts and messages are written in English. They go through the message catalog (see "Output language") once that exists; until then, write plain English strings.

## Data formats

Queue (`queue.tsv`) columns: `id status prioriteit ronde door reden toegevoegd idreeks rapport` become `id status priority round via reason added id_block report`.

| Dutch status | English status |
|---|---|
| queue: `open`, `bezig`, `klaar`, `overgeslagen` | `open`, `in_progress`, `done`, `skipped` |
| requests: `concept`, `aangehouden`, `verstuurd`, `beantwoord`, `afgesloten` | `draft`, `on_hold`, `sent`, `answered`, `closed` |
| forum: `concept`, `geplaatst`, `afgesloten` | `draft`, `posted`, `closed` |

Request front matter: `aan`, `instelling`, `onderwerp`, `personen`, `aangemaakt`, `afzender`, `status`, `verstuurd`, `antwoord-op`, `beantwoord` become `to`, `institution`, `subject`, `persons`, `created`, `sender`, `status`, `sent`, `in-reply-to`, `answered`. Sender value `andy` becomes `user`.

Request attachments header `bijlagen` becomes `attachments`. Reply and forum-notification files saved by `mail inbox` use the keys `from`, `subject`, `date`, `request`, `message-id`, `attachments` (were `van`, `onderwerp`, `datum`, `aanvraag`, `message-id`, `bijlagen`); an unlinked reply is named `unlinked` (was `ongekoppeld`). The mail body section `## Achtergrond` becomes `## Background` (both are cut from the sent text).

Forum drafts: header keys `titel`, `personen`, `uitsneden`, `draad`, `geplaatst`, `reacties` become `title`, `persons`, `crops`, `thread`, `posted`, `replies`; the appended section `## Reacties` becomes `## Replies`.

Readers accept the old Dutch column names, keys and statuses as well, and write the English ones. `lineage migrate` will rewrite existing files once; after that the Dutch fallback can be removed.

## Files and folders the tools read or write

| Dutch | English default |
|---|---|
| `data/stamboom.ged` | `data/tree.ged` |
| `onderzoek/` | `research/` |
| `onderzoek/wachtrij.tsv` | `research/queue.tsv` |
| `onderzoek/vragen.md` | `research/questions.md` |
| `onderzoek/log.md` | `research/log.md` |
| `onderzoek/aanvragen/` (`antwoorden/`) | `research/requests/` (`replies/`) |
| `onderzoek/forum/` (`meldingen/`) | `research/forum/` (`notifications/`) |
| `onderzoek/blog/` | `research/blog/` |
| `onderzoek/verwant.tsv` | `research/targets.tsv` (moves into `lineage.toml` later) |
| `onderzoek/stammen.tsv` | `research/stems.tsv` (moves into `lineage.toml` later; option `mannen-eerst` becomes `men-first`) |
| `onderzoek/levensverhalen-gecontroleerd.tsv` | `research/stories-checked.tsv` |
| `onderzoek/vragenkaart.tsv` (columns `datum`, `keuze`, `ter plaatse`, `opgelost`, `gaten`, `voorouders`) | `research/question-map.tsv` (`date`, `choice`, `on_site`, `solved`, `gaps`, `ancestors`) |
| `rapporten/` | `reports/` |
| `rapporten/personen/` | `reports/persons/` |
| `rapporten/levensverhalen/` | `reports/life-stories/` |
| `rapporten/boeken/` | `reports/books/` |
| `data/coordinaten.tsv` | `data/coordinates.tsv` |
| `uitvoer/` (worktree) | `output/` |
| `uitvoer/scans` | `output/scans` |
| `bronnen/scans/opgehaald/` | `sources/scans/fetched/` |
| `uitvoer/KLAAR` | `output/DONE` |
| `uitvoer/bijwerk`, `uitvoer/opdracht` | `output/update`, `output/brief` (`account` and `model` unchanged; see docs/rounds.md) |
| `bronnen/scans/aanvragen/` | `sources/scans/requests/` |
| `<git-common-dir>/dr-bewaker.json`, `.log`, `.alive` | `dr-guard.json`, `.log`, `.alive` |
| `~/.config/ndygen/mail.env` (`NDYGEN_MAIL_ADRES`, `_WACHTWOORD`, `_SMTP`, `_IMAP`) | `~/.config/lineage/mail.env` (`LINEAGE_MAIL_ADDRESS`, `_PASSWORD`, `_SMTP`, `_IMAP`); old file and keys still read |
| `~/.config/ndygen/geneanet.env` (`NDYGEN_GENEANET_GEBRUIKER`, `_WACHTWOORD`) | `~/.config/lineage/geneanet.env` (`LINEAGE_GENEANET_USER`, `_PASSWORD`); old file and keys still read |
| `~/.cache/ndygen/geneanet-state.json` | `~/.cache/lineage/geneanet-state.json` |
| `~/.config/ndygen/`, `~/.cache/ndygen/` | `~/.config/lineage/`, `~/.cache/lineage/` |
| env `NDYGEN_*` | env `LINEAGE_*` |
| `<git-common-dir>/ndygen-htr.log` | `<git-common-dir>/lineage-htr.log` |
| `~/.cache/ndygen/rat/` (`rem.json`, `rem.lock`; keys `stil_tot`, `reden`, `laatste`) | `~/.cache/lineage/rat/` (`throttle.json`, `throttle.lock`; keys `locked_until`, `reason`, `last`) |
| `~/.config/ndygen/transkribus.env` (`NDYGEN_TRANSKRIBUS_GEBRUIKER`, `_WACHTWOORD`, `_URL`) | `~/.config/lineage/transkribus.env` (`LINEAGE_TRANSKRIBUS_USER`, `_PASSWORD`, `_URL`); the old file path and keys are still read |
| `<git-common-dir>/dr-*` state files | unchanged names (`dr-accounts`, `dr-max-rondes` becomes `dr-max-rounds`, `dr-limiet-<acc>` becomes `dr-limit-<acc>`, `dr-vaderlijn` becomes `dr-paternal`, `dr-bijwerken-cache.json` becomes `dr-stale-cache.json`) |

Paths are module-level defaults for now; they move into `lineage.toml` `[paths]` in the config phase.

Do not change values stored outside the repository: the Gramps Web attribute keys `ndygen-vraag`, `ndygen-status`, `ndygen-blog` and the Gramps handle/ID scheme stay byte-identical (an existing server already holds them). Keep them as named constants with a comment saying why.

## Domain terms

| Dutch | English |
|---|---|
| persoon, gezin, bron, akte | person, family, source, record (a civil or church act) |
| voorouder, nakomeling, kwartierstaat, parenteel | ancestor, descendant, ancestor table, descendant table |
| rechte lijn | direct line |
| vaderlijn, stam, stamvader | paternal line, stem, progenitor |
| zijtak | side branch |
| kwartierstaat (Sosa number) | ancestor table (ahnentafel number) |
| ontbrekende ouders | missing parents |
| doelpersoon | target person |
| verwantschap | kinship |
| levensverhaal | life story |
| levensboek | life book |
| onderzoeksleider | research lead |
| hulpagent | helper agent |
| coördinator, wachter, bewaker | coordinator, watcher, guard |
| ronde, vervolgronde | round, follow-up round |
| ID-reeks | ID block |
| samenvoegen | merge |
| afronden | finish |
| aanvraag (mail aan archief) | request |
| concept | draft |
| akkoord | approval |
| inventarisnummer, toegang | inventory number, fonds |
| uitsnede | crop |
| rem, stillegging | throttle, lockout |
| scan, transcriptie | scan, transcription |
| doop, ondertrouw, huwelijk, begraven | baptism, marriage banns, marriage, burial |
| gecontroleerd | checked |

Dutch archival terms that have no exact English equivalent (ondertrouw, schepenprotocol, kohier, DTB, bevolkingsregister, gezinskaart, memorie van successie) stay Dutch in skills and references, with a short English gloss at first use.

## Fixtures

Test fixtures use invented persons and invented archive records only. Do not copy names, places plus dates, or record identifiers from `data/stamboom.ged` or from real Open Archieven responses.
