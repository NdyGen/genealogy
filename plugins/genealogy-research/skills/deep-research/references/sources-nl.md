# Sources for deep research: the Netherlands and Flanders

This guide covers the Netherlands and Flanders. Guides for other countries can sit next to it as `sources-<cc>.md` (for example `sources-de.md`). Dutch names of registers, archives and terms stay Dutch, with a short English gloss.

Which source exists depends on time and place. Start at Open Archieven: it searches many archives at once. Then try the specific websites. When searching, use spelling variants, patronymics, and `&` for two persons in one record (`"Jan Smit & Maria Jansen 1850-1860"`).

## Contents
1. Search tools
2. Registers by kind
3. Newspapers and publications
4. History and context
5. By region (experience from earlier research)
6. Transkribus (`lineage htr`)
7. Unreachable sites

## 1. Search tools

| Tool | Use |
|---|---|
| `lineage archive search "<name> <year-year>" [--type ...] [--place ...] [--role ...] [--source "BS Geboorte"]` | Open Archieven: BS, DTB, bevolkingsregister, notarial, militia, memories and more. `--source` filters on source type. |
| `lineage archive show <archive>:<id> --gedcom` | The full record with all persons and remarks, plus a ready-made source record and citation. |
| `lineage rat search <terms> [--fonds 929]` | Regionaal Archief Tilburg (RAT; for example fonds 929 Schepenbank Dongen, 962 's-Gravenmoer): searches the **titles** of inventory items (guardianships, protocols), not the records themselves. |
| `lineage rat item <inv> [--fonds ...] [--scans]` | Title, dating and scans of an inventory number, with a download URL per scan. Some printed finding aids (regesten) cite RAT inventory numbers as "RA" numbers: check a few folios before relying on that mapping. Some protocols (including 16th and 17th century ones and the unindexed geloftboeken) are online as scans; each scan is often an opening of two pages. |
| `lineage rat download <inv> [--scans 1-25,98] [--dir output/scans]` | Scans to `<dir>/<fonds>-<inv>/<nr>.jpg`; what is already there is skipped. Every scan comes from a shared cache and is fetched from Memorix only once per machine. |
| `lineage rat throttle [--test] [--release]` | Shared throttle on all RAT traffic from this machine: at least 3 s between requests (`LINEAGE_RAT_INTERVAL`), API answers kept 30 days, half an hour of silence after HTTP 429 and six hours after HTTP 403. `--test` makes one probe request and lifts a lockout if the server answers again. Never bypass with `curl` or your own loop. |
| `lineage rat crop <image> X0 Y0 X1 Y1 [--scale 2]` | Crop in grey with stretched contrast, frame as fractions of the page. Always read 17th century handwriting on a crop, not on the whole page. |
| `lineage scan <ref-or-viewer-URL>...` | Fetches the scan of an Open Archieven record at full resolution, also where curl gets a 403 or the viewer needs JavaScript, with a `.json` provenance file next to it. |
| `lineage htr <images>... [--model <name>] [--max n]` | Transkribus text recognition for a hand that you and the scan reader cannot read; costs credits. See section 6. |
| RAT 847 (Schepenbank Eninge van Oisterwijk): regesten | The protocols 1418-1810 marked "klik voor index met korte samenvattingen" have a list of regesten (abstracts; W. de Bakker, L. de Brouwer). `rat search <name> --fonds 847` searches that text but does not show it; the full text is in the Memorix API under `tree/NL-TbRAT-847/<cpath of the series>` (field `content`, with folio as `847.Sch.Otw,R.<inv>,<folio>`). Selections, especially Oisterwijk, Haaren and Udenhout. |
| Full-resolution scans (Memorix: SALHA, BHIC, RAT) | `archive show` gives a thumbnail (`images.memorix.nl/<sha|bhic|tlb>/thumb/640x480/<uuid>.jpg`), unreadable for handwriting. The full scan: `download-images.memorix.nl/<sha|bhic|tlb>/download/fullsize/<uuid>.jpg` (on 429 wait a few minutes), or IIIF `images.memorix.nl/<archive>/iiif/<uuid>/full/1800,/0/default.jpg`. `lineage scan` does this for you. |
| WieWasWie (wiewaswie.nl) | Partly other indexes than Open Archieven. |
| archieven.nl | Inventories and indexes of regional archives; also scans. |
| FamilySearch | Only indexed records and scans, no family trees. Searching needs a login with the user's own session; if the project has one set up, `project.md` says how. The session expires after a few hours: on HTTP 401 ask the user for a new one, do not retry. Only a few targeted searches per round, with pauses; the place filter `q.anyPlace` does not filter. |

## 2. Registers by kind

| Register | Period | What it yields | Where |
|---|---|---|---|
| Burgerlijke stand, BS (civil registration: birth, marriage, death) | from 1811 (Limburg 1796) | ages, occupations, residences, witnesses, acknowledgements and legitimations | Open Archieven, WieWasWie |
| DTB (dopen, trouwen, begraven: baptisms, marriages, burials) | before 1811 | parents, godparents, ondertrouw (marriage banns) | Open Archieven; Limburg: LGGI/allelimburgers.nl (plain `http://` only) |
| Bevolkingsregister (population register) | 1850-1920 (sometimes from 1820) | household, addresses, moves, occupation, religion | Open Archieven (`--source Bevolkingsregister`), archieven.nl (scans). Gemeentearchief Roermond (`rmd:`): the viewer loads with JavaScript; open the scan URL in a headless browser (Playwright with the local chromium-headless-shell) and replace `thumb` by `large` in the folio's `preserve2.archieven.nl/...?format=thumb` URL (1024 px, address and occupation are usually readable). |
| Volkstellingen (censuses) | 1795-1840 | household at one moment | archieven.nl, regional archives |
| Militieregisters (militia registers) | 1814-1920 | height, occupation, appearance, lottery, service | Open Archieven (`--source Militieregisters`), WieWasWie |
| Schutterij (civic guard) | 19th century | service in the schutterij | regional archives |
| Notariële akten (notarial deeds) | 1811+ (older: schepenprotocollen) | wills, sales, leases, estates, marriage settlements | Open Archieven (`--source Notariële archieven`), archieven.nl |
| Schepenprotocollen and rechterlijke archieven (aldermen's protocols and judicial archives) | before 1811 | ownership, debts, guardianship, family ties | regesten: doekefkes.nl (Tilburg, Dongen, Capelle, Sprang), BHIC, RA Tilburg |
| Memories van successie (inheritance tax declarations) | 1818-1927 | heirs, estate | Open Archieven, archieven.nl |
| Courts and prisons | 19th-20th century | sentences, prison registers | Open Archieven (`--source Gevangenisregisters`), Nationaal Archief |
| Lidmaten- en ledenregisters (church member registers) | 17th-19th century | church membership, moves | regional archives |
| Patent and tax registers, kadaster (land registry) | 19th century | occupation, property | regional archives, kadaster (Hisgis) |
| Bidprentjes (memorial cards) | 19th-20th century | date of death, family (note: recent persons) | Open Archieven (`hvr:`), CBG |
| CBG persoonskaarten (person cards) | died after 1938 | household around 1939-1994 | cbg.nl (paid; deceased persons only) |

## 3. Newspapers and publications

- **Delpher** (delpher.nl): national and regional newspapers from the 17th century. Finds family notices, court reports ("de rechtbank te 's-Hertogenbosch veroordeelde ..."), advertisements (business, auctions), accidents, anniversaries and elections. Search on name **plus** place, or name plus occupation; the name alone gives noise. Cite newspaper, date, page and the Delpher URL (`urn`).
- **Regional newspaper databases:** BHIC (Brabant newspapers), RHC Limburg (Limburg newspapers), Stadsarchief Breda.
- **Local-history journals and genealogies** (heemkunde: for example Taxandria, De Brabantse Leeuw, yearbooks of local history societies): they count as a source only if they point to an archival item. Then cite the archival item via the publication.

## 4. History and context

Use these to see whether a person appears in an event, and to give the report context:
- Wikipedia and the websites of municipalities and local history societies: local history, municipal mergers, local events.
- National events that often echo in records:
  - the French period (1795-1813);
  - the Belgian Revolt and the Ten Days' Campaign (militia 1830-1839);
  - cholera (1832, 1849, 1866);
  - the potato crisis (1845-1847);
  - the agricultural crisis (1878-1895);
  - the mobilisation of 1914-1918;
  - the Spanish flu (1918);
  - the crisis years of the 1930s;
  - the mobilisation of 1939 and the Second World War.
- Oorlogsgravenstichting, Erelijst, Joods Monument: only if a source demonstrably names the person, and with respect for possibly living relatives.

## 5. By region (experience from earlier research)

The project's own region is in `project.md`; this table collects what earlier research taught per region.

| Region | Archives | Points of attention |
|---|---|---|
| Langstraat (Sprang, Capelle, Waalwijk, Besoijen, Loon op Zand, 's-Gravenmoer) | SALHA, RA Tilburg, BHIC | Reformed (NG) and Catholic (RK) records mixed; shoe industry; floods 1861/1880 |
| Dongen, Oosterhout, Tilburg, Breda | RA Tilburg, Stadsarchief Breda, West-Brabants Archief | the Dongen baptism book 1640-1648 is missing; Tilburg protocols before 1593 only as regesten |
| Limburg (Roermond, Maasniel, Melick en Herkenbosch, Herten, Roggel, Heythuysen, Venlo) | RHC Limburg, LGGI, Gemeentearchief Roermond and Venlo | BS from 1796; Melick before 1801 not online |
| Abroad (Adenau, Schoten, Essen, Kirchhoven near Heinsberg) | Matricula (diocese of Trier, diocese of Aachen: among others Kirchhoven St. Hubert), Belgian State Archives (search.arch.be) | often scans only |
| Rhineland (Waldfeucht, Elmpt, Brüggen, Heinsberg and surroundings) | Landesarchiv NRW Abt. Rheinland, Personenstandsarchiv PA 1101 (church books 1571-1874) | see below |

**Landesarchiv NRW (PA 1101).** archive.nrw.de and dfg-viewer.de sit behind a bot check (Anubis); the METS and scans do not: `https://www.landesarchiv-nrw.de/digitalisate/Personenstandsarchiv_Rhld/Kirchenbuecher/BA/<folder>/<BA, 4 digits>/mets.xml` and `https://www.landesarchiv-nrw.de/data02/Personenstandsarchiv_Rhld/Kirchenbuecher/BA/<folder>/<BA>/BA_<BA>_S<NNN>.jpg` (curl, gently). Folder = `~` + BA divided by 100 (3 digits), for example BA 0538 is `~005/0538`; Waldfeucht: folder `~027`, BA 2763 baptisms 1770-1800, BA 2765 marriages 1770-1798. Folder, BA number and METS link are found through the archive.nrw.de page in a (headless) browser (Playwright): open a known Verzeichnungseinheit (for example `https://www.archive.nrw.de/archivsuche?link=VERZEICHUNGSEINHEIT-Vz_d6802066-8e4f-4137-8af1-e7ce7785ae3e`, Karken BA 1141), wait 30-60 s for the bot check, click the place in the tree (`span[title="203. Heinsberg"]`) and then `(BA nnnn)`: the detail shows LAUFZEIT (period) and INHALT (contents). Heinsberg St. Gangolf: BA 0866 (T/H 1584-1620), 0867 (T 1623-1644, H 1623-1657), 0868 (T 1645-1691), 0869 (H 1682-1714, S 1616-1691), 0870 (H 1713-1770, S 1691-1769), 0871 (T 1692-1769), 0872 (T 1770-1798), 0873 (H 1770-1798), 0874 (S 1770-1798); duplicate registers BA 0875-0879 (T = Taufen/baptisms, H = Heiraten/marriages, S = Sterbefälle/burials). Kirchhoven St. Hubert: BA 1247 (T 1733-1771), 1248 (T 1770-1798), 1249 (H 1770-1798), 1250 (S 1770-1798); this fills the gap 1771-1792 on Matricula.

## 6. Transkribus (`lineage htr`)

Text recognition through Transkribus, for hands that the lead and the scan reader do not read reliably (especially 16th and 17th century chancery hands). Text and PAGE XML go to `htr/` next to the scan; a recognised scan is never done again.

- **Credits are limited** and belong to the user. Only targeted scans, never a whole register. Every brief that allows htr names a maximum number of recognitions, and `--max` limits it per call. `lineage htr --count [--since YYYY-MM-DD]` shows the usage (a shared log for all worktrees).
- **A crop, not a double page.** Recognise a crop of the few deciding lines (`lineage rat crop`), not a whole opening of two pages: it reads better and costs less.
- **Models** (`--model` with a short name or number; any model other than the default writes to `htr/<name>.<model>.txt`, so you can compare models):

| Short name | Model | Use |
|---|---|---|
| `dutchess` | The Dutchess I (50786) | default |
| `dean` | Dutch Dean (309753) | read the 17th century Brabant schepen hand clearly better than the default; first choice for schepenprotocollen |
| `titan` | Text Titan II (579509) | for comparison |
| `notarieel` | Notarial 17th Century Super Model_v2 (40382) | for comparison, notarial deeds |
| `zeeuws` | Large Zeeuws 1550-1700 (210033) | for comparison |

  Compare models only on a crop that is decisive, and count every recognition.
- **A machine reading, not proof.** Always check a hit yourself on the scan. Not checked is not proven (certainty scale in `report.md`).
- **Count at the end:** `find <output> -path '*/htr/*.txt' | wc -l`; the number goes exactly into report and log.

## 7. Unreachable sites

Archive servers are sometimes down or give an error page (during an outage Memorix returned an HTML page with HTTP 200 instead of an image for RAT scans).

- **One test request first.** If it does not work (error, timeout, error page), do not hammer the site: no loops, no parallel requests, no other route that asks the same thing.
- **Retry at most every half hour**, and not longer than two hours after the first failed attempt. Work on what can be done meanwhile.
- **Then finish** with what worked. What is missing goes as an open question into the report and the questions file, with the finding place, the reason (which error, when tried) and what it would yield.
- **An HTML page is never a scan.** Check that a downloaded image really is an image (`file <path>`), and never read an error page as a record.
- For RAT the throttle and lockout of `lineage rat` apply as well (section 1).
