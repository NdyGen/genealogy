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


def test_new_link_without_source():
    old = ged("0 @I1@ INDI", "1 NAME John /Faber/", "0 @F1@ FAM")
    bare = ged("0 @I1@ INDI", "1 NAME John /Faber/", "1 FAMC @F1@",
               "1 NOTE Parents from the burial record S1.", "0 @F1@ FAM", "1 CHIL @I1@")
    sourced = bare.replace("1 FAMC @F1@", "1 FAMC @F1@\n2 SOUR @S1@\n3 QUAY 3")
    assert review.unsourced_links(old, bare) == [("I1", "F1")]
    assert review.unsourced_links(old, sourced) == []
    assert review.unsourced_links(bare, bare) == []


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


def test_link_argued_proven_on_a_record_naming_the_kinship_is_left_to_the_review():
    """Five rounds in a row the FAMC warning was a false alarm on a link whose own NOTE opens with "proven" and
    cites the division that names the parents, with QUAY 2 or 3: the leader decided on purpose. A link without
    such a NOTE, or with "not proven", is still reported."""
    old = ged("0 @I1@ INDI", "1 NAME John /Faber/", "0 @F1@ FAM")
    child = ("0 @I1@ INDI", "1 NAME John /Faber/", "1 FAMC @F1@", "2 SOUR @S1@", "3 QUAY {q}",
             "2 NOTE {note}", "1 NOTE Identification: patronymic and birthplace.", "0 @F1@ FAM", "1 CHIL @I1@")
    argued = "Proven: the division of 1635 names John son of Paul. That he is our John rests on two features."
    for q in (2, 3):
        assert review.derived_links(old, ged(*(r.format(q=q, note=argued) for r in child))) == []
    weak = ged(*(r.format(q=2, note="Not proven: the division names John son of Paul.") for r in child))
    assert review.derived_links(old, weak) == [("I1", "F1")]
    unsourced = ged(*(r.format(q=0, note=argued) for r in child))
    assert review.derived_links(old, unsourced) == [("I1", "F1")]


def test_skipped_as_possibly_living_while_the_round_dated_him():
    """`queue add` skipped a brother as possibly living before the round gave him a birth bound of 1635."""
    old_queue = QUEUE_HEADER + "\nI1\tin_progress\t1\t1\t\t\t\t500001-500999\t"
    row = "\nI2\tskipped\t5\t2\tI1\tbrother, division 1635; possibly living, do not research\t2026-11-04\t\t"
    new = ged(*FAMILY, "0 @I2@ INDI", "1 BIRT", "2 DATE BEF 15 JAN 1635")
    assert review.skipped_but_old(old_queue, old_queue + row, new) == ["I2"]
    young = ged(*FAMILY, "0 @I2@ INDI", "1 BIRT", "2 DATE 1950")
    assert review.skipped_but_old(old_queue, old_queue + row, young) == []
    on_purpose = row.replace("possibly living, do not research", "died young, both records found")
    assert review.skipped_but_old(old_queue, old_queue + on_purpose, new) == []
    assert any("I2 skipped as possibly living" in w for w in check(ged(*FAMILY), new, queue_new=old_queue + row).warnings)


def test_queue_reason_with_another_grade_than_the_report():
    """The queue said "possibly father of", the report "presumed" for the same claim about the same ID."""
    old_queue = QUEUE_HEADER + "\nI1\tin_progress\t1\t1\t\t\t\t500001-500999\t"
    new_queue = old_queue + "\nI5\topen\t5\t2\tI1\tbrother; possibly father of Kate (I8)\t2026-11-04\t\t"
    report = "- **Lost ancestry (presumed):** no link of Kate (I8) to I5.\n| I5 | Ansel | brother | possibly father of Kate | 5 |"
    found = review.grade_mismatch(old_queue, new_queue, {"report": report})
    assert len(found) == 1 and "presumed" in found[0]
    same = report.replace("(presumed)", "(possible)")
    assert review.grade_mismatch(old_queue, new_queue, {"report": same}) == []
    two_claims = "Parents proven; I5 probably the elder brother, possibly father of Kate."
    assert review.grade_mismatch(old_queue, new_queue, {"report": two_claims}) == []
    living = new_queue.replace("possibly father of Kate (I8)", "possibly living, do not research")
    assert review.grade_mismatch(old_queue, living, {"report": report}) == []


def test_new_mail_question_while_the_report_calls_a_source_unread():
    """A mail goes out only when every other source is exhausted; a round asked for one while its own report
    still listed four online inventories as unread."""
    question = "- [ ] I1 John Faber [mail: National Archive]: muster rolls of his company."
    report = "- **Billeting lists inv. 930-933:** unread, 1200 scans.\n- **Court rolls 1002:** not online yet, not read."
    assert review.mail_while_unread(question, report) == ["- **Billeting lists inv. 930-933:** unread, 1200 scans."]
    assert review.mail_while_unread(question, report, questions_old=question + " Older text.") == []
    assert review.mail_while_unread("- [ ] I1 John Faber: muster rolls.", report) == []
    dutch = "- **Inkwartiering inv. 930-933:** ongelezen. *(Achterhaald: gelezen op 4-11.)*"
    assert review.mail_while_unread(question, dutch) == []
    u = check(ged(*FAMILY), ged(*FAMILY), report_new="Round on personal, 0 recognitions.\n" + report,
              questions_new=question)
    assert any("[mail: ...]" in w for w in u.warnings)


def test_proven_and_helper_in_one_sentence_is_reported():
    report = "**Parents (proven).** Baptism 1647 read by a helper agent, not re-read."
    assert review.proven_next_to_helper(report) == [report]
    report = "Parents proven on the baptism of 1647, a helper agent's reading."
    assert review.proven_next_to_helper(report) == [report]


def test_helper_in_another_sentence_or_list_item_is_quiet():
    report = (
        "Identification proven on the baptism (read myself, scan 0046, fol. 12). "
        "A second Anna was not found by the helper agent.\n"
        "- Parents proven: marriage 1644.\n- Siblings from a helper agent, not linked."
    )
    assert review.proven_next_to_helper(report) == []


def test_quoted_proven_about_the_review_itself_is_quiet():
    report = "Review reports 'proven' next to a helper agent twice: false alarm, I read the scans myself."
    assert review.proven_next_to_helper(report) == []


def test_proven_on_a_regest_or_index_is_reported():
    texts = {"report": "Death before 1626 proven on the regest of fol. 33. Baptism bewezen op de index."}
    assert len(review.proven_on_derived(texts)) == 2
    quiet = {"report": "Proven on the scan (read myself); the regest gives the same date. Niet bewezen op het regest."}
    assert review.proven_on_derived(quiet) == []


def test_place_or_patronymic_as_second_feature_is_reported():
    report = ("Burial 1749: (1) name with patronymic; (2) residence Klein-Dongen, where his house stood.\n"
              "Begraving 1776: (1) patroniem Peter in beide registers, (2) woonplaats Leijsen.")
    assert len(review.name_counted_twice({"report": report})) == 2
    quiet = ("Burial 1749: (1) name, patronymic and residence are one feature; (2) the period: alive in 1749.\n"
             "Overlijden 1767: (1) weduwe van Claas; (2) woonplaats 't End.")
    assert review.name_counted_twice({"report": quiet}) == []


def test_pronoun_mismatch_in_own_birth_note():
    old = ged("0 @I1@ INDI\n1 SEX M")
    new = ged(
        "0 @I1@ INDI\n1 SEX M",
        "0 @I2@ INDI\n1 SEX F\n1 BIRT\n2 DATE BET 1623 AND 1648\n2 NOTE Afgeleid. Zijn moeder was\n3 CONC  toen weduwe.",
        "0 @I3@ INDI\n1 SEX M\n1 CHR\n2 NOTE Haar vader\n3 CONC  was schepen.",
    )
    assert review.pronoun_mismatch(old, new) == [("I2", "Zijn moeder"), ("I3", "Haar vader")]


def test_pronoun_mismatch_ignores_other_notes_and_old_text():
    note = "2 NOTE Zijn moeder was weduwe."
    old = ged(f"0 @I1@ INDI\n1 SEX F\n1 BIRT\n{note}")
    new = ged(
        f"0 @I1@ INDI\n1 SEX F\n1 BIRT\n{note}\n1 RESI\n2 NOTE Zijn vader, haar schoonvader, woonde er.",
        "0 @I2@ INDI\n1 SEX F\n1 NOTE Haar man; zijn moeder heette Jans.",
        "0 @I3@ INDI\n1 SEX U\n1 BIRT\n2 NOTE Zijn moeder.",
    )
    assert review.pronoun_mismatch(old, new) == []


def test_new_link_on_quay_2_only():
    old = ged(*FAMILY[:2], *FAMILY[3:])
    def linked(quays):
        lines = ["1 FAMC @F1@"]
        for q in quays:
            lines += ["2 SOUR @S1@", f"3 QUAY {q}"]
        return ged(*FAMILY[:2], *lines, *FAMILY[3:])
    assert review.unmarked_links(old, linked([2])) == [("I1", "F1")]
    assert review.unmarked_links(old, linked([2, 2])) == [("I1", "F1")]
    assert review.unmarked_links(old, linked([2, 3])) == []
    assert review.unmarked_links(old, linked([1])) == []
    assert review.unmarked_links(linked([2]), linked([2])) == []
    assert any("QUAY 2" in w for w in check(old, linked([2])).warnings)


def test_date_after_today():
    today = dt.date(2026, 11, 11)
    texts = {"report": "read on 12-11-2026; baptised 3-4-1650; reread 11-11-2026; 31-2-2027"}
    assert review.future_dates(texts, today) == ["report: date 12-11-2026 lies after today"]
    report = "Round on personal. Transkribus recognitions in this round: 0. Reread 12-11-2026."
    tree = ged(*FAMILY)
    assert any("12-11-2026" in w for w in check(tree, tree, report_new=report, today=today).warnings)
