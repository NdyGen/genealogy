import datetime as dt

from lineage import review
from tests.conftest import ged

QUEUE_HEADER = "id\tstatus\tpriority\tround\tvia\treason\tadded\tid_block\treport"
LEGACY_QUEUE_HEADER = "id\tstatus\tprioriteit\tronde\tdoor\treden\ttoegevoegd\tidreeks\trapport"
FAMILY = (
    "0 @I1@ INDI", "1 NAME John /Faber/", "1 FAMC @F1@",
    "0 @I2@ INDI", "1 NAME Paul /Faber/", "1 FAMS @F1@",
    "0 @F1@ FAM", "1 HUSB @I2@", "1 CHIL @I1@",
    "0 @I9@ INDI", "1 NAME Karl /Elsewhere/",
    "1 EVEN", "2 TYPE Estate division", "2 DATE SEP 1800", "2 PLAC Northfield",
)


def check(old, new, **kw):
    args = dict(
        queue_old=QUEUE_HEADER + "\nI1\tin_progress\t1\t1\t\t\t\t500001-500999\t",
        queue_new=QUEUE_HEADER + "\nI1\tin_progress\t1\t1\t\t\t\t500001-500999\t",
        coords_old="place\tlat\nA\t1\n",
        coords_new="place\tlat\nA\t1\n",
        report_new="Round on personal. Transkribus recognitions in this round: 0.",
        account="personal",
        htr=0,
    )
    args.update(kw)
    return review.check("I1", old, new, **args)


def test_clean_round_gives_nothing():
    old = ged(*FAMILY)
    new = ged(*FAMILY, "0 @I500001@ INDI", "1 NAME New /Child/")
    assert check(old, new).text() == "no mechanical findings"


def test_record_out_of_reach_is_reported():
    old = ged(*FAMILY)
    new = ged(*FAMILY[:-3], "1 EVEN", "2 TYPE Estate division", "2 DATE 1 SEP 1803", "2 PLAC Northfield")
    assert any("I9 changed outside the reach" in m for m in check(old, new).warnings)


def test_id_block_is_found_under_the_old_column_names():
    queue = LEGACY_QUEUE_HEADER + "\nI1\tbezig\t1\t1\t\t\t\t500001-500999\t"
    assert review.id_block(queue, "I1") == "500001-500999"
    assert review.id_block(QUEUE_HEADER + "\nI1\topen\t1\t1\t\t\t\t7-9\t", "I1") == "7-9"
    assert review.id_block(queue, "I2") == ""


def test_corrected_value_without_note_and_elsewhere():
    old = ged(*FAMILY, "0 @I3@ INDI", "1 FAMS @F1@",
              "1 EVEN", "2 TYPE Estate division", "2 DATE SEP 1800", "2 PLAC Northfield")
    new = ged(*FAMILY, "0 @I3@ INDI", "1 FAMS @F1@",
              "1 EVEN", "2 TYPE Estate division", "2 DATE 1 SEP 1803", "2 PLAC Northfield")
    warnings = check(old, new).warnings
    assert any("I3: '2 DATE SEP 1800' vanished" in m for m in warnings)
    assert any(m.startswith("I9 still has 'Estate division SEP 1800 Northfield'") for m in warnings)


def test_old_value_in_a_note_is_enough():
    old = ged("0 @I1@ INDI", "1 NAME Joanna Maria /Jansen/")
    new = ged(
        "0 @I1@ INDI", "1 NAME Anna Maria /Jansen/",
        "2 NOTE Corrected: first name was 'Joanna", "3 CONC  Maria' (index).",
    )
    assert review.vanished_values(old, new) == []


def test_removed_coordinate_is_an_error_but_moving_is_not():
    old = ged(*FAMILY)
    gone = check(old, old, coords_new="place\tlat\n")
    assert any("coordinate table" in m for m in gone.errors)
    moved = check(old, old, coords_old="place\tlat\nB\t2\nA\t1\n", coords_new="place\tlat\nA\t1\nB\t2\n")
    assert moved.errors == []


def test_transkribus_account_and_queue_against_the_report():
    old = ged(*FAMILY)
    u = check(
        old, old, htr=5, account="work",
        queue_new=QUEUE_HEADER + "\nI1\tin_progress\t1\t1\t\t\t\t500001-500999\t\nI7\topen\t2\t2\tI1\t\t\t\t",
        report_new="Round on personal. **Transkribus: 4 recognitions this round.**",
    )
    assert len(u.errors) == 3
    assert "5 recognitions in the log" in u.errors[0]


def test_a_dutch_report_is_still_understood():
    old = ged(*FAMILY)
    u = check(old, old, htr=5, report_new="Ronde op personal. **Transkribus: 4 herkenningen deze ronde.**")
    assert "report mentions 4" in u.errors[0]
    text = "Ronde op personal, 0 herkenningen.\n\nOverlijden bewezen; scan gelezen door hulpagent."
    assert check(old, old, report_new=text).warnings
    assert not check(old, old, report_new=text.replace("bewezen", "niet bewezen")).warnings


def test_proven_next_to_a_helper_agent():
    old = ged(*FAMILY)
    text = "Round on personal, 0 recognitions.\n\nDeath proven; scan read by helper agent."
    assert check(old, old, report_new=text).warnings
    assert not check(old, old, report_new=text.replace("proven", "not proven")).warnings


def test_htr_count_per_round():
    log = "\n".join([
        "2026-10-22T08:00:00\t309753\t/x/.worktrees/dr-I1/output/a.jpg",
        "2026-10-22T09:00:00\t309753\t/x/sources/scans/dr-I1/b.jpg",
        "2026-10-22T09:00:00\t309753\t/x/sources/scans/dr-I12/b.jpg",
    ])
    assert review.htr_count(log, "I1", dt.datetime(2026, 10, 22, 8, 30)) == 1


def test_new_link_with_derived_identity_without_quay_1():
    old = ged("0 @I1@ INDI", "1 NAME John /Faber/", "0 @F1@ FAM")
    child = ("0 @I1@ INDI", "1 NAME John /Faber/", "1 FAMC @F1@", "2 SOUR @S1@", "3 QUAY {q}",
             "1 NOTE Identification: patronymic and birthplace.", "0 @F1@ FAM", "1 CHIL @I1@")
    proven = ged(*(r.format(q=3) for r in child))
    marked = ged(*(r.format(q=1) for r in child))
    assert review.derived_links(old, proven) == [("I1", "F1")]
    assert review.derived_links(old, marked) == []
    assert review.derived_links(proven, proven) == []
    baptism = proven.replace("patronymic and birthplace.", "with the baptism: given name and both parents. Rich.")
    assert review.derived_links(old, baptism) == []
    event = proven.replace("1 NOTE Identification: patronymic and birthplace.",
                           "1 EVEN Division\n2 NOTE Identification with the baptism: patronymic.")
    assert review.derived_links(old, event) == []


def test_removed_program_line():
    old = ged("0 @I1@ INDI", "1 _UPD 12 MAY 2021", "1 NAME John /Faber/")
    new = ged("0 @I1@ INDI", "1 NAME John /Faber/", "1 NOTE Rewritten.")
    assert review.vanished_metadata(old, new) == [("I1", "1 _UPD 12 MAY 2021")]
    assert review.vanished_metadata(old, old) == []
    assert any("_UPD" in w for w in check(old, new).warnings)


def test_helper_agent_quote_in_a_life_story():
    report = ('Read myself: "A house, barn and yard". In the margin it says "as father and heir '
              'of his deceased child" (read only by the helper agent).')
    firm = 'Christian signed "as father and heir of his deceased child". William was dead.'
    careful = firm.replace("William was dead.", "That reading is uncertain.")
    own = 'It concerned "A house, barn and yard" at Eastfield. A fine farm.'
    assert review.helper_quotes(report, firm)
    assert review.helper_quotes(report, careful) == []
    assert review.helper_quotes(report, own) == []


def test_dutch_helper_agent_quote_is_still_found():
    report = 'In de kantlijn staat "als Vader en Erfgenaam van zijn overleeden kind" (alleen door de hulpagent gelezen).'
    story = 'Christiaan tekende "als Vader en Erfgenaam van zijn overleeden kind". Wilhelmus was dood.'
    assert review.helper_quotes(report, story)


def test_word_off_the_scale():
    old = ged(*FAMILY)
    new = ged(*FAMILY, "0 @I500001@ INDI", "1 NOTE Demonstrably his son.")
    u = check(old, new, report_new="Round on personal, 0 recognitions. *Demonstrably:* he lived there.",
              story="It was almost certainly his father.")
    found = " ".join(u.warnings)
    assert "report: 'Demonstrably'" in found
    assert "GEDCOM: 'Demonstrably'" in found
    assert "life story: 'almost certainly'" in found
    dutch = check(old, new, report_new="Round on personal, 0 recognitions. *Aantoonbaar:* hij woonde er.")
    assert "report: 'Aantoonbaar'" in " ".join(dutch.warnings)


def test_new_long_gedcom_line():
    old = ged(*FAMILY)
    new = ged(*FAMILY, "0 @I500001@ INDI", "1 NOTE " + "x" * 260)
    assert any("new line of 267 characters" in m for m in check(old, new).errors)
    assert not check(old, ged(*FAMILY, "0 @I500001@ INDI", "1 NOTE short")).errors


def test_removed_rows_ignores_a_renamed_header():
    old = "plaats\tadres\nA\t\nB\t\n"
    new = "place\taddress\nA\t\n"
    assert review.removed_rows(old, new) == ["B\t"]
