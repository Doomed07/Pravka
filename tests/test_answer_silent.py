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


def test_first_version_clause_decisions_become_word_comments(tmp_path):
    """Первая версия: ответ юриста на положение — примечание Word к абзацу от его имени; текст контрагента не меняется."""
    from pravki.intake import clause_changes
    body = (p(r("1.1. Акт подписывается в течение 5 рабочих дней со дня получения.")) +
            p(r("2.1. Оплата производится в течение 30 дней после подписания акта.")) +
            p(r("3.1. Исполнитель отвечает за нарушение сроков неустойкой в размере 1% в день.")))
    src = str(make_docx(tmp_path / "first.docx", body))
    unified = str(tmp_path / "u.docx")
    chs = clause_changes(read_docx(src))
    annotate_docx(src, unified, chs, [])  # как в сервисе: единая версия содержит примечания
    changes = [c.to_dict() for c in chs]
    assert len(changes) == 3
    choices = {changes[0]["id"]: {"choice": "counter", "text": "Давайте сочтемся на 7 рабочих днях"},
               changes[1]["id"]: {"choice": "reject"}, changes[2]["id"]: {"choice": "accept"}}
    out = str(tmp_path / "answer.docx")
    stats = build_answer(unified, out, changes, choices, AUTHOR, None)
    assert stats["counter"] == 1 and stats["reject"] == 1 and stats["accept"] == 1 and stats["без отметки"] == 0
    import zipfile
    z = zipfile.ZipFile(out)
    comments = z.read("word/comments.xml").decode()
    assert "Давайте сочтемся на 7 рабочих днях" in comments and AUTHOR in comments and "Не согласны" in comments
    assert ANNOTATOR not in comments
    doc = read_docx(out)
    assert _ours(doc) == []  # текст договора не тронут: ни вставок, ни удалений
    assert z.read("word/document.xml").decode().count("commentReference") == 2


def test_site_paragraph_edit_becomes_tracked_changes(tmp_path):
    """Юрист правит текст абзаца на сайте: в Word это наши вставки и удаления по словам. «Принять все» даёт новый
    текст, «отклонить наше» — прежний. Абзац с правкой контрагента не трогается."""
    old = "2.3.5. Акт подписывается в течение 5 рабочих дней со дня получения, иначе считается подписанным."
    new = "2.3.5. Акт подписывается в течение семи рабочих дней со дня получения."
    body = p(r("2.3.5. Акт подписывается в те"), r("чение 5 рабочих дней со дня пол"), r("учения, иначе считается подписанным.")) + p(r("Второй абзац остаётся."))
    src = str(make_docx(tmp_path / "first.docx", body))
    out = str(tmp_path / "answer.docx")
    stats = build_answer(src, out, [], {"P000": {"choice": "edit", "text": new}, "P099": {"choice": "edit", "text": "x"}},
                         AUTHOR, None)
    assert stats["edit"] == 1 and stats["без отметки"] == 1  # P099 — абзаца нет
    doc = read_docx(out)
    assert _accepted(doc)[0] == normalize(new) and normalize("Второй абзац остаётся.") in _accepted(doc)
    ours = _ours(doc)
    assert ("del", "5") in ours and ("ins", "семи") in ours  # по словам, а не весь абзац
    rejected = [normalize(t) for _, t in view_paragraphs(doc, "rejected", set()) if normalize(t)]
    assert rejected[0] == normalize(old)
    # абзац, где уже есть правка контрагента, не трогаем
    tracked = p(r("Срок "), '<w:ins w:id="7" w:author="Они" w:date="2026-01-01T00:00:00Z"><w:r><w:t>10 дней</w:t></w:r></w:ins>')
    src2 = str(make_docx(tmp_path / "t.docx", tracked))
    stats2 = build_answer(src2, str(tmp_path / "a2.docx"), [], {"P000": {"choice": "edit", "text": "Срок 5 дней"}}, AUTHOR, None)
    assert stats2["edit"] == 0 and stats2["без отметки"] == 1


def test_sentence_broken_by_paragraph_is_found_and_joined_in_word(tmp_path):
    """«…на основании гл. 26.2-1» и отдельным абзацем «НК РФ.»: оба абзаца склеиваются нашей правкой в рецензировании;
    заголовки, пронумерованные и обычные короткие абзацы не трогаются; отклонённая склейка в файл не попадает."""
    from pravki.docx_reader import view_paragraphs
    body = (p(r("1.3 Стоимость услуг составляет 475 000 рублей. НДС не облагается на основании гл. 26.2-1")) + p(r("НК РФ.")) +
            p(r("2.1 Исполнитель обязан оказать услуги надлежащего качества в согласованный срок")) + p(r("Подписи сторон")) +
            p(r("3.1 Заказчик оплачивает услуги в течение десяти дней со дня подписания акта.")) + p(r("Конец.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    theirs = read_docx(src)
    document = build_unified(None, theirs, set(), [])
    marked = [d["index"] for d in document if d.get("join_next")]
    assert marked == [0]  # только «НК РФ.»; «Подписи сторон» без точки — не хвост предложения, а «Конец.» следует за законченным
    out = str(tmp_path / "a.docx")
    stats = build_answer(src, out, [], {}, AUTHOR, document)
    assert stats["join"] == 1
    joined = [normalize(t) for _, t in view_paragraphs(read_docx(out), "accepted", set()) if normalize(t)]
    assert joined[0].endswith("26.2-1 НК РФ.") and "НК РФ." not in joined[1:2]
    stats2 = build_answer(src, str(tmp_path / "b.docx"), [], {"J000": {"choice": "reject"}}, AUTHOR, document)
    assert stats2["join"] == 0


def test_continuation_in_lowercase_is_joined_even_when_long_and_with_a_note(tmp_path):
    """«2.3.5 В течение 5 (пяти)» и длинный абзац «рабочих дней …»: начало со строчной буквы — признак продолжения.
    Абзац-список, заголовок, пронумерованный пункт и законченное предложение не склеиваются."""
    body = (p(r("2.3.5 В течение 5 (пяти)")) + p(r("рабочих дней со дня получения вернуть Организатору подписанный акт. Стороны вправе подписывать Акты через ЭДО.")) +
            p(r("2.4 Заказчик вправе отказаться от договора.")) + p(r("поставщик обязан вернуть аванс.")) +
            p(r("2.5 Стороны согласовали следующее")) + p(r("3.1 Поставка осуществляется в срок.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    assert [d["index"] for d in document if d.get("join_next")] == [0]


def test_join_keeps_numbering_and_format_of_the_first_paragraph(tmp_path):
    """В Word при удалении знака абзаца склеенный абзац берёт вид второго (нумерация слетала, выравнивание менялось).
    Поэтому текст второго переносится в первый, а второй удаляется целиком: у первого остаётся его w:pPr."""
    import zipfile
    from lxml import etree
    num = '<w:numPr><w:ilvl w:val="1"/><w:numId w:val="7"/></w:numPr>'
    body = p(r("В течение 5 (пяти)"), ppr=num) + p(r("рабочих дней со дня получения акта."), ppr='<w:jc w:val="right"/>') + p(r("Следующий пункт."))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    assert document[0].get("join_next")
    out = str(tmp_path / "a.docx")
    assert build_answer(src, out, [], {}, AUTHOR, document)["join"] == 1
    root = etree.fromstring(zipfile.ZipFile(out).read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras = root.findall(".//w:p", ns)
    assert paras[0].find("w:pPr/w:numPr", ns) is not None and paras[0].find("w:pPr/w:rPr/w:del", ns) is None
    assert paras[1].find("w:pPr/w:rPr/w:del", ns) is not None  # второй абзац удаляется целиком нашей правкой
    accepted = [normalize(t) for _, t in view_paragraphs(read_docx(out), "accepted", set()) if normalize(t)]
    assert accepted[0] == "В течение 5 (пяти) рабочих дней со дня получения акта." and accepted[1] == "Следующий пункт."


def test_edit_of_a_joined_paragraph_changes_both_parts_and_keeps_numbering(tmp_path):
    """Юрист правит склеенный абзац целиком: новый текст ложится в первую часть (с её нумерацией), вторая удаляется."""
    import zipfile
    from lxml import etree
    num = '<w:numPr><w:ilvl w:val="1"/><w:numId w:val="7"/></w:numPr>'
    body = p(r("В течение 5 (пяти)"), ppr=num) + p(r("рабочих дней со дня получения акта."), ppr='<w:jc w:val="right"/>') + p(r("Следующий пункт."))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    new = "В течение 7 (семи) рабочих дней со дня получения акта, но не позднее срока оплаты."
    out = str(tmp_path / "a.docx")
    stats = build_answer(src, out, [], {"P000": {"choice": "edit", "text": new}}, AUTHOR, document)
    assert stats["edit"] == 1 and stats["join"] == 1 and stats["без отметки"] == 0
    accepted = [normalize(t) for _, t in view_paragraphs(read_docx(out), "accepted", set()) if normalize(t)]
    assert accepted == [normalize(new), "Следующий пункт."]
    root = etree.fromstring(zipfile.ZipFile(out).read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras = root.findall(".//w:p", ns)
    assert paras[0].find("w:pPr/w:numPr", ns) is not None and paras[1].find("w:pPr/w:rPr/w:del", ns) is not None
    # а если склейку отклонили, правка относится только к первой части и вторая остаётся на месте
    stats2 = build_answer(src, str(tmp_path / "b.docx"), [], {"J000": {"choice": "reject"}}, AUTHOR, document)
    assert stats2["join"] == 0


def test_word_broken_by_paragraph_is_joined_without_a_space(tmp_path):
    """«Орг» / «анизатор имеет право…»: слово разорвано границей абзаца, склеивать без пробела. «на» / «основании» — это
    два слова, между ними пробел."""
    body = (p(r("2.5.1 Организатор обязан оказать услуги надлежащего качества.")) + p(r("2.5.3. Орг")) +
            p(r("анизатор имеет право отказаться от исполнения Договора при условии соблюдения положений Договора.")) +
            p(r("2.6 Исполнитель вправе действовать на")) + p(r("основании доверенности, выданной Заказчиком в срок.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    flags = {d["index"]: (d.get("join_next"), d.get("join_glue")) for d in document if d.get("join_next")}
    assert flags == {1: (True, True), 3: (True, None)}
    out = str(tmp_path / "a.docx")
    assert build_answer(src, out, [], {}, AUTHOR, document)["join"] == 2
    accepted = [normalize(t) for _, t in view_paragraphs(read_docx(out), "accepted", set()) if normalize(t)]
    assert accepted[1].startswith("2.5.3. Организатор имеет право") and "на основании доверенности" in accepted[2]


def test_word_broken_inside_is_glued_by_dictionary_when_the_contract_does_not_have_it_elsewhere(tmp_path):
    """Целого слова в договоре больше нет: решает словарь русского языка. «Орг» / «анизатор» — словарь не знает ни одной
    половины, «Исполни» / «тель» — знает только целое; «на» / «основании» — два настоящих слова, пробел остаётся."""
    body = (p(r("2.5.3. Орг")) + p(r("анизатор имеет право отказаться от исполнения Договора при условии соблюдения положений.")) +
            p(r("2.6 Права и обязанности сторон определены здесь, а также Исполни")) +
            p(r("тель вправе отказаться от исполнения договора при условии оплаты.")) +
            p(r("2.7 Подрядчик вправе действовать на")) + p(r("основании доверенности, выданной Заказчиком в срок.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    glue = {d["index"]: bool(d.get("join_glue")) for d in document if d.get("join_next")}
    assert glue == {0: True, 2: True, 4: False}


def test_extra_spaces_are_removed_by_our_tracked_deletion(tmp_path):
    """«пять  тысяч», «право.            отказаться»: из серии пробелов остаётся один, лишние удаляются нашей правкой в
    рецензировании. После «принять все» текст без двойных пробелов; прежний текст получается «отклонить наше»."""
    body = (p(r("Стоимость пять  тысяч рублей, оплата в тече"), r("ние 10 дней.  Исполнитель имеет право.            отказаться.")) +
            p(r("Обычный абзац без лишних пробелов.")) + p(r("Правим сами  здесь.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    assert [d["index"] for d in document if d.get("extra_spaces")] == [0, 2]
    out = str(tmp_path / "a.docx")
    stats = build_answer(src, out, [], {"P002": {"choice": "edit", "text": "Правим сами здесь."}}, AUTHOR, document)
    assert stats["spaces"] == 1 and stats["edit"] == 1  # абзац 2 правит юрист: пробелы убирает его правка
    doc = read_docx(out)
    accepted = [t for _, t in view_paragraphs(doc, "accepted", set()) if t.strip()]
    assert accepted[0] == "Стоимость пять тысяч рублей, оплата в течение 10 дней. Исполнитель имеет право отказаться."
    assert accepted[2] == "Правим сами здесь."
    rejected = [t for _, t in view_paragraphs(doc, "rejected", set()) if t.strip()]
    assert "право.            отказаться" in rejected[0] and "пять  тысяч" in rejected[0]


def test_stray_dot_inside_a_sentence_is_found_and_removed_in_word(tmp_path):
    """«право.   отказаться»: точка посреди предложения убирается нашей правкой. Сокращения, номера пунктов и начало нового
    предложения с заглавной буквы не трогаются; отказ (D<абзац>) и правка юриста отменяют исправление."""
    from pravki.unified import find_stray_dots
    assert find_stray_dots("согласно ст. 5 и п. 2.1, стоимость 100 руб. и более. Новое предложение, т.е. так") == []
    assert find_stray_dots("услуги оказаны. б) поставка и Конец. Новое") == []
    assert find_stray_dots("Кор. счёт: 30101810400000, Расч. счёт: 40702, Почт. адрес: Москва") == []  # реквизиты
    body = p(r("2.2 Участник имеет право.            отказаться от участия.")) + p(r("Срок: согласно ст. 5 и п. 2.1 договора."))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    assert [d["index"] for d in document if d.get("stray_dots")] == [0]
    out = str(tmp_path / "a.docx")
    stats = build_answer(src, out, [], {}, AUTHOR, document)
    assert stats["dots"] == 1 and stats["spaces"] == 1
    doc = read_docx(out)
    assert [t for _, t in view_paragraphs(doc, "accepted", set()) if t.strip()][0] == "2.2 Участник имеет право отказаться от участия."
    assert ("del", ".") in _ours(doc)
    assert "право." in [t for _, t in view_paragraphs(doc, "rejected", set()) if t.strip()][0]
    for decision in ({"D000": {"choice": "reject"}}, {"P000": {"choice": "edit", "text": "2.2 Участник имеет право. отказаться."}}):
        assert build_answer(src, str(tmp_path / "b.docx"), [], decision, AUTHOR, document)["dots"] == 0


def test_extra_spaces_are_removed_in_a_joined_paragraph_too(tmp_path):
    """В склеенном абзаце лишние пробелы первой части тоже убираются (раньше такой абзац пропускался)."""
    body = (p(r("1.3 Стоимость услуг: четыреста семьдесят пять  тысяч рублей, НДС не облагается на основании гл. 26.2-1")) +
            p(r("НК РФ.")) + p(r("Следующий пункт.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    assert document[0].get("join_next") and document[0].get("extra_spaces")
    out = str(tmp_path / "a.docx")
    stats = build_answer(src, out, [], {}, AUTHOR, document)
    assert stats["join"] == 1 and stats["spaces"] == 1
    accepted = [t for _, t in view_paragraphs(read_docx(out), "accepted", set()) if t.strip()]
    assert accepted[0] == "1.3 Стоимость услуг: четыреста семьдесят пять тысяч рублей, НДС не облагается на основании гл. 26.2-1 НК РФ."


def test_paragraph_deleted_and_added_on_the_site_become_tracked_changes(tmp_path):
    """Удаление абзаца (X<абзац>, reject) и новый абзац после (A<абзац>, edit): наша правка в рецензировании. Новый абзац
    наследует вид (нумерацию) того, после которого стоит. В удалённом абзаце другие правки не делаются."""
    import zipfile
    from lxml import etree
    num = '<w:numPr><w:ilvl w:val="1"/><w:numId w:val="7"/></w:numPr>'
    body = (p(r("1.1 Первый пункт  с лишним пробелом."), ppr=num) + p(r("1.2 Лишний пункт, который удаляем.  ")) +
            p(r("1.3 Третий пункт."), ppr=num) + p(r("1.4 Последний пункт.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    out = str(tmp_path / "a.docx")
    choices = {"X001": {"choice": "reject"}, "A002": {"choice": "edit", "text": "Новый пункт один.\nНовый пункт два."}}
    stats = build_answer(src, out, [], choices, AUTHOR, document)
    assert stats["delete"] == 1 and stats["add"] == 2 and stats["без отметки"] == 0
    accepted = [t for _, t in view_paragraphs(read_docx(out), "accepted", set()) if t.strip()]
    assert accepted == ["1.1 Первый пункт с лишним пробелом.", "1.3 Третий пункт.", "Новый пункт один.", "Новый пункт два.", "1.4 Последний пункт."]
    root = etree.fromstring(zipfile.ZipFile(out).read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras = root.findall(".//w:p", ns)
    assert paras[1].find("w:pPr/w:rPr/w:del", ns) is not None  # второй абзац удалён целиком
    new = [x for x in paras if x.find("w:pPr/w:rPr/w:ins", ns) is not None]
    assert len(new) == 2 and all(x.find("w:pPr/w:numPr", ns) is not None for x in new)
    rejected = [t for _, t in view_paragraphs(read_docx(out), "rejected", set()) if t.strip()]
    assert "1.2 Лишний пункт, который удаляем." in " ".join(rejected) and "Новый пункт один." not in rejected


def test_joined_paragraph_is_deleted_with_both_parts(tmp_path):
    """Склеенный абзац (две части) удаляется целиком: обе части зачёркнуты нашей правкой, склейка не делается."""
    body = (p(r("1.1 Первый пункт.")) + p(r("1.2 Срок оплаты в течение 5 (пяти)")) + p(r("рабочих дней со дня получения акта.")) +
            p(r("1.3 Последний пункт.")))
    src = str(make_docx(tmp_path / "t.docx", body))
    document = build_unified(None, read_docx(src), set(), [])
    assert document[1].get("join_next")
    out = str(tmp_path / "a.docx")
    stats = build_answer(src, out, [], {"X001": {"choice": "reject"}}, AUTHOR, document)
    assert stats["delete"] == 2 and stats["join"] == 0 and stats["без отметки"] == 0
    accepted = [t for _, t in view_paragraphs(read_docx(out), "accepted", set()) if t.strip()]
    assert accepted == ["1.1 Первый пункт.", "1.3 Последний пункт."]
    rejected = [t for _, t in view_paragraphs(read_docx(out), "rejected", set()) if t.strip()]
    assert rejected == ["1.1 Первый пункт.", "1.2 Срок оплаты в течение 5 (пяти)", "рабочих дней со дня получения акта.", "1.3 Последний пункт."]


def test_comment_with_reasons_can_accompany_a_deleted_paragraph(tmp_path):
    """Обоснование удаления: комментарий юриста (C<абзац>) — примечание Word от его имени к абзацу; абзац при этом удалён
    нашей правкой, а текст комментария не попадает в текст договора."""
    import zipfile
    from lxml import etree
    body = p(r("1.1 Первый пункт.")) + p(r("1.2 Лишний пункт, который мы удаляем.")) + p(r("1.3 Последний пункт."))
    src = str(make_docx(tmp_path / "t.docx", body))
    unified = str(tmp_path / "u.docx")
    annotate_docx(src, unified, [], [])  # как в сервисе: в единой версии есть часть примечаний
    document = build_unified(None, read_docx(src), set(), [])
    out = str(tmp_path / "a.docx")
    choices = {"X001": {"choice": "reject"}, "C001": {"choice": "edit", "text": "Пункт дублирует 1.1, поэтому исключаем."},
               "C099": {"choice": "edit", "text": "нет такого абзаца"}}
    stats = build_answer(unified, out, [], choices, AUTHOR, document)
    assert stats["delete"] == 1 and stats["comment"] == 1 and stats["без отметки"] == 1
    z = zipfile.ZipFile(out)
    comments = z.read("word/comments.xml").decode()
    assert "Пункт дублирует 1.1, поэтому исключаем." in comments and AUTHOR in comments
    assert "К удалённому пункту «1.2 Лишний пункт, который мы удаляем.»" in comments  # понятно, о чём речь
    root = etree.fromstring(z.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    anchored = [x for x in root.findall(".//w:p", ns) if x.find("w:commentRangeStart", ns) is not None]
    assert len(anchored) == 1 and anchored[0].find("w:pPr/w:rPr/w:del", ns) is None  # примечание на оставшемся абзаце, виден всегда
    accepted = [t for _, t in view_paragraphs(read_docx(out), "accepted", set()) if t.strip() and "Правки" not in t]
    assert accepted == ["1.1 Первый пункт.", "1.3 Последний пункт."]
    assert z.read("word/document.xml").decode().count("commentReference") >= 1
