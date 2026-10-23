"""Ответ контрагенту в Word: принять / отклонить / встречная редакция по каждой правке."""
import zipfile

from lxml import etree

from pravki.annotate import DISCLAIMER, annotate_docx
from pravki.answer import build_answer
from pravki.compare import compare_versions
from pravki.docx_reader import q, read_docx
from pravki.model import ANNOTATOR
from pravki.unified import build_unified
from tests.helpers import dele, ins, make_docx, p, r

BASE = p(r("1.1. Срок оплаты 10 дней.")) + p(r("1.2. Неустойка 0,1%.")) + p(r("1.3. Подсудность — Москва."))
THEIRS = (p(r("1.1. Срок оплаты "), dele("10", 1), ins("60", 2), r(" дней."))
          + p(r("1.2. Неустойка "), dele("0,1%", 3), ins("0,01%", 4), r("."))
          + p(r("1.3. Подсудность — Москва."), ins(" Претензионный порядок не обязателен.", 5)))
COMMENT = ('<w:comment w:id="7" w:author="Контрагент"><w:p><w:r><w:t>Просим 60 дней.</w:t></w:r></w:p></w:comment>')


def _setup(tmp_path, theirs=THEIRS, comments=None):
    base = read_docx(str(make_docx(tmp_path / "b.docx", BASE)))
    tp = str(make_docx(tmp_path / "t.docx", theirs, comments=comments))
    t = read_docx(tp)
    changes = compare_versions(base, t, ["Мы"])
    unified = str(tmp_path / "u.docx")
    annotate_docx(tp, unified, changes, build_unified(base, t, {"Мы"}, changes))
    return [c.to_dict() for c in changes], unified


def _answer(tmp_path, choices, **kw):
    changes, unified = _setup(tmp_path, **kw)
    by_clause = {c["clause"]: c["id"] for c in changes}
    out = str(tmp_path / "answer.docx")
    stats = build_answer(unified, out, changes, {by_clause[k]: v for k, v in choices.items()}, "Иванова А.")
    return read_docx(out), stats


def _text(para, kinds=("equal", "ins")):
    return "".join(s.text for s in para.segments if s.kind in kinds)


def test_accept_and_reject_tracked_changes(tmp_path):
    doc, stats = _answer(tmp_path, {"1.1": {"choice": "accept"}, "1.2": {"choice": "reject"}})
    assert _text(doc.paragraphs[0]) == "1.1. Срок оплаты 60 дней."
    assert _text(doc.paragraphs[1]) == "1.2. Неустойка 0,1%."
    assert {s.kind for s in doc.paragraphs[0].segments} == {"equal"}  # правка принята — отметок не осталось
    assert {s.kind for s in doc.paragraphs[1].segments} == {"equal"}
    assert stats["accept"] == 1 and stats["reject"] == 1
    with zipfile.ZipFile(tmp_path / "answer.docx") as z:
        xml = etree.fromstring(z.read("word/document.xml"))
    # Word не показывает w:delText вне w:del: отклонённое удаление должно стать обычным текстом
    assert not [t for t in xml.iter(q("delText")) if not any(a.tag == q("del") for a in t.iterancestors())]


def test_changes_without_choice_stay_tracked(tmp_path):
    doc, _ = _answer(tmp_path, {"1.1": {"choice": "accept"}})
    assert [(s.kind, s.text) for s in doc.paragraphs[1].segments if s.kind != "equal"] == [("del", "0,1%"), ("ins", "0,01%")]


def test_counter_proposal_is_our_tracked_change(tmp_path):
    doc, stats = _answer(tmp_path, {"1.1": {"choice": "counter", "text": "30"}})
    marked = [(s.kind, s.text, s.author) for s in doc.paragraphs[0].segments if s.kind != "equal"]
    assert marked == [("del", "10", "Иванова А."), ("ins", "30", "Иванова А.")]  # их «60» убрано, наше «30» вставлено
    assert stats["counter"] == 1


def test_counter_to_their_insertion_replaces_it(tmp_path):
    doc, _ = _answer(tmp_path, {"1.3": {"choice": "counter", "text": " Срок ответа на претензию — 10 дней."}})
    marked = [(s.kind, s.text, s.author) for s in doc.paragraphs[2].segments if s.kind != "equal"]
    assert marked == [("ins", " Срок ответа на претензию — 10 дней.", "Иванова А.")]


def test_our_notes_removed_party_comments_and_disclaimer_kept(tmp_path):
    body = THEIRS.replace("<w:p><w:pPr></w:pPr><w:r><w:t xml:space=\"preserve\">1.1.",
                          '<w:p><w:pPr></w:pPr><w:commentRangeStart w:id="7"/><w:r><w:t xml:space="preserve">1.1.', 1)
    body = body.replace(" дней.</w:t></w:r></w:p>",
                        ' дней.</w:t></w:r><w:commentRangeEnd w:id="7"/><w:r><w:commentReference w:id="7"/></w:r></w:p>', 1)
    doc, stats = _answer(tmp_path, {"1.1": {"choice": "accept"}}, theirs=body, comments=COMMENT)
    assert [c.author for c in doc.comments.values()] == ["Контрагент"]  # наши примечания вырезаны
    assert stats["наших примечаний убрано"] == 4  # по одному на каждую правку (3 + комментарий)
    last = doc.paragraphs[-1]
    assert _text(last) == DISCLAIMER and {s.author for s in last.segments} == {ANNOTATOR}


def test_paragraph_insert_and_delete(tmp_path):
    base_doc = BASE
    theirs = (p(r("1.1. Срок оплаты 10 дней.")) + p(dele("1.2. Неустойка 0,1%.", 3), ppr='<w:rPr><w:del w:id="9" w:author="Контрагент" w:date="2026-10-05T10:00:00Z"/></w:rPr>')
              + p(r("1.3. Подсудность — Москва.")) + p(ins("1.4. Новый пункт.", 5), ppr='<w:rPr><w:ins w:id="8" w:author="Контрагент" w:date="2026-10-05T10:00:00Z"/></w:rPr>'))
    changes, unified = _setup(tmp_path, theirs=theirs)
    kinds = {c["kind"]: c["id"] for c in changes}
    out = str(tmp_path / "a.docx")
    build_answer(unified, out, changes, {kinds["para_delete"]: {"choice": "reject"}, kinds["para_insert"]: {"choice": "accept"}}, "Мы")
    texts = [_text(x) for x in read_docx(out).paragraphs if _text(x).strip()]
    assert texts[:4] == ["1.1. Срок оплаты 10 дней.", "1.2. Неустойка 0,1%.", "1.3. Подсудность — Москва.", "1.4. Новый пункт."]
    out2 = str(tmp_path / "a2.docx")
    build_answer(unified, out2, changes, {kinds["para_delete"]: {"choice": "accept"}, kinds["para_insert"]: {"choice": "reject"}}, "Мы")
    texts2 = [_text(x) for x in read_docx(out2).paragraphs]
    # удалённый пункт исчез вместе с абзацем: пустой строки на его месте нет
    assert texts2[:2] == ["1.1. Срок оплаты 10 дней.", "1.3. Подсудность — Москва."] and "1.4. Новый пункт." not in texts2
