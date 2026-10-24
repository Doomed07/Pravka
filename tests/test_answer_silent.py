"""Ответ на правки без отметки в рецензировании: текст контрагента становится нашей правкой в рецензировании.

Главная проверка: если отклонить все такие правки, то после «принять все» в Word текст совпадает с нашей редакцией.
"""
import re

from pravki.annotate import annotate_docx
from pravki.answer import build_answer
from pravki.answer_silent import pattern
from pravki.compare import compare_versions
from pravki.docx_reader import read_docx, view_paragraphs
from pravki.model import ANNOTATOR
from pravki.textdiff import normalize
from pravki.unified import build_unified
from tests.helpers import make_docx, p, r

AUTHOR = "Иванова А."


def _run(tmp_path, base_body, theirs_body, decide):
    base = read_docx(str(make_docx(tmp_path / "b.docx", base_body)))
    tp = str(make_docx(tmp_path / "t.docx", theirs_body))
    theirs = read_docx(tp)
    changes = compare_versions(base, theirs, ["Мы"])
    document = build_unified(base, theirs, {"Мы"}, changes)
    unified = str(tmp_path / "u.docx")
    annotate_docx(tp, unified, changes, document)
    dicts = [c.to_dict() for c in changes]
    out = str(tmp_path / "answer.docx")
    stats = build_answer(unified, out, dicts, {c["id"]: decide(c) for c in dicts}, AUTHOR, document)
    return read_docx(out), stats, dicts


def _accepted(doc):
    """Текст после «принять все» в Word, без нашего дисклеймера."""
    return [normalize(t) for para, t in view_paragraphs(doc, "accepted", set()) if normalize(t)
            and not any(s.author == ANNOTATOR for s in para.segments)]


def _ours(doc):
    return [(s.kind, s.text) for para in doc.paragraphs for s in para.segments
            if s.kind != "equal" and s.author == AUTHOR]


def test_pattern_tolerates_quotes_dashes_and_spaces():
    # «было/стало» правки нормализованы (прямые кавычки, дефис), а в файле Word — «ёлочки» и длинное тире
    assert re.search(pattern(normalize("услуги «Заказчика» – по договору")), "услуги «Заказчика»  — по договору")


def test_reject_number_in_split_runs(tmp_path):
    base = p(r("1.1. Срок оплаты 10 дней."))
    theirs = p(r("1.1. Срок опл"), r("аты 6"), r("0 дн"), r("ей."))  # Word режет текст где угодно
    doc, stats, _ = _run(tmp_path, base, theirs, lambda c: {"choice": "reject"})
    assert _ours(doc) == [("del", "60"), ("ins", "10")]
    assert _accepted(doc) == ["1.1. Срок оплаты 10 дней."] and stats["reject"] == 1


def test_ambiguous_place_is_chosen_by_our_version(tmp_path):
    base = p(r("1.1. Оплата 30 дней, приёмка 10 дней."))
    theirs = p(r("1.1. Оплата 30 дней, приёмка 30 дней."))
    doc, _, _ = _run(tmp_path, base, theirs, lambda c: {"choice": "reject"})
    assert _accepted(doc) == ["1.1. Оплата 30 дней, приёмка 10 дней."]


def test_reject_inserted_and_deleted_words(tmp_path):
    base = p(r("1.1. Срок 10 рабочих дней.")) + p(r("1.2. Оплата по счёту."))
    theirs = p(r("1.1. Срок 10 дней.")) + p(r("1.2. Оплата по счёту без предоплаты."))
    doc, stats, _ = _run(tmp_path, base, theirs, lambda c: {"choice": "reject"})
    assert _accepted(doc) == ["1.1. Срок 10 рабочих дней.", "1.2. Оплата по счёту."]
    assert stats["reject"] == 2 and stats["без отметки"] == 0


def test_reject_inserted_and_deleted_paragraphs(tmp_path):
    base = p(r("1.1. Первый.")) + p(r("1.2. Неустойка 0,1% в день.")) + p(r("1.3. Третий."))
    theirs = p(r("1.1. Первый.")) + p(r("1.3. Третий.")) + p(r("1.4. Подсудность — суд Казани."))
    doc, stats, _ = _run(tmp_path, base, theirs, lambda c: {"choice": "reject"})
    assert _accepted(doc) == ["1.1. Первый.", "1.2. Неустойка 0,1% в день.", "1.3. Третий."]
    assert stats["reject"] == 2
    # абзац контрагента удалён целиком, вместе с концом абзаца: в Word не останется пустой строки
    gone = [x for x in doc.paragraphs if x.segments and all(seg.kind == "del" and seg.author == AUTHOR for seg in x.segments)]
    assert gone and all(x.mark == "del" for x in gone)


def test_counter_and_accept(tmp_path):
    base = p(r("1.1. Срок оплаты 10 дней.")) + p(r("1.2. Неустойка 0,1%."))
    theirs = p(r("1.1. Срок оплаты 60 дней.")) + p(r("1.2. Неустойка 0,01%."))

    def decide(c):
        return {"choice": "counter", "text": "20"} if c["clause"] == "1.1" else {"choice": "accept"}

    doc, stats, _ = _run(tmp_path, base, theirs, decide)
    assert _ours(doc) == [("del", "60"), ("ins", "20")]
    assert _accepted(doc) == ["1.1. Срок оплаты 20 дней.", "1.2. Неустойка 0,01%."]
    assert stats["counter"] == 1 and stats["accept"] == 1


def test_counter_without_text_is_not_applied(tmp_path):
    doc, stats, _ = _run(tmp_path, p(r("1.1. Срок 10 дней.")), p(r("1.1. Срок 60 дней.")),
                         lambda c: {"choice": "counter", "text": "  "})
    assert _ours(doc) == [] and stats["без отметки"] == 1


def test_punctuation_added_at_the_end_is_found(tmp_path):
    doc, stats, _ = _run(tmp_path, p(r("8.2. Изменения оформляются соглашением сторон")),
                         p(r("8.2. Изменения оформляются соглашением сторон.")), lambda c: {"choice": "reject"})
    assert _accepted(doc) == ["8.2. Изменения оформляются соглашением сторон"] and stats["reject"] == 1


def test_reject_everything_restores_our_version_on_synthetic_contracts(tmp_path):
    """Отклонить все правки (отмеченные и без отметки) → после «принять все» текст равен нашей редакции."""
    import os

    from pravki.pipeline import review_files
    from pravki.synth import generate_case, side_config

    for tpl in ("supply", "services"):
        for seed in (2, 3):
            case = generate_case(str(tmp_path / f"{tpl}{seed}"), tpl, seed)
            for variant in ("tracked", "clean"):
                rv = review_files(case["paths"][variant], case["paths"]["base"], None, side=side_config(case))
                uni = str(tmp_path / "u.docx")
                annotate_docx(case["paths"][variant], uni, rv.changes, rv.document)
                dicts = [c.to_dict() for c in rv.changes]
                out = str(tmp_path / "a.docx")
                build_answer(uni, out, dicts, {c["id"]: {"choice": "reject"} for c in dicts}, AUTHOR, rv.document)
                want = [normalize(t) for _, t in view_paragraphs(read_docx(case["paths"]["base"]), "accepted", set())
                        if normalize(t)]
                assert _accepted(read_docx(out)) == want, (tpl, seed, variant)
                os.remove(out)


def test_first_version_clause_decisions_reach_the_file(tmp_path):
    """Первая версия: положения без отметок в рецензировании. Решения юриста (отклонить, встречная редакция) должны
    попасть в файл нашей правкой; «принять» и нерешённое оставляют текст как есть."""
    from pravki.intake import clause_changes
    body = (p(r("1.1. Акт подписывается в течение 5 рабочих дней со дня получения.")) +
            p(r("2.1. Оплата производится в течение 30 дней после подписания акта.")) +
            p(r("3.1. Исполнитель отвечает за нарушение сроков неустойкой в размере 1% в день.")))
    src = str(make_docx(tmp_path / "first.docx", body))
    changes = [c.to_dict() for c in clause_changes(read_docx(src))]
    assert len(changes) == 3
    choices = {changes[0]["id"]: {"choice": "counter", "text": "2.3.5. Акт подписывается в течение 7 рабочих дней."},
               changes[1]["id"]: {"choice": "reject"}, changes[2]["id"]: {"choice": "accept"}}
    out = str(tmp_path / "answer.docx")
    stats = build_answer(src, out, changes, choices, AUTHOR, None)
    assert stats["counter"] == 1 and stats["reject"] == 1 and stats["accept"] == 1 and stats["без отметки"] == 0
    doc = read_docx(out)
    ours = _ours(doc)
    assert ("ins", "2.3.5. Акт подписывается в течение 7 рабочих дней.") in ours
    assert any(k == "del" and "Оплата производится" in t for k, t in ours)
    assert not any("неустойкой" in t for _, t in ours)  # принятое не тронуто
