from pravki.compare import compare_versions
from pravki.docx_reader import read_docx
from pravki.unified import build_unified
from tests.helpers import dele, ins, make_docx, p, r


def _unified(tmp_path, base_body, theirs_body, ours=()):
    b = read_docx(str(make_docx(tmp_path / "base.docx", base_body))) if base_body is not None else None
    t = read_docx(str(make_docx(tmp_path / "theirs.docx", theirs_body)))
    changes = compare_versions(b, t, list(ours))
    return build_unified(b, t, set(ours), changes), changes


def _marked(doc):
    return [(s["k"], s["t"]) for para in doc for s in para["segments"] if s["k"] != "equal"]


def test_tracked_changes_are_shown_in_text(tmp_path):
    doc, changes = _unified(tmp_path, p(r("1.1. Срок 10 дней.")), p(r("1.1. Срок "), dele("10"), ins("20"), r(" дней.")))
    assert _marked(doc) == [("del", "10"), ("ins", "20")]
    assert doc[0]["changes"] == [changes[0].id]


def test_silent_edit_is_marked_separately(tmp_path):
    doc, changes = _unified(tmp_path, p(r("2.2. Оплата в течение 10 дней.")), p(r("2.2. Оплата в течение 30 дней.")))
    assert _marked(doc) == [("silent_del", "10"), ("silent_ins", "30")]
    assert doc[0]["changes"] == [changes[0].id]


def test_our_own_changes_are_plain_text(tmp_path):
    theirs = p(r("1.1. Срок "), dele("10", author="kandu"), ins("20", author="kandu"), r(" дней."))
    doc, _ = _unified(tmp_path, p(r("1.1. Срок 20 дней.")), theirs, ours=["kandu"])
    assert _marked(doc) == []
    assert "".join(s["t"] for s in doc[0]["segments"]) == "1.1. Срок 20 дней."


def test_paragraph_removed_without_tracking_stays_in_place(tmp_path):
    base = p(r("1.1. Первый.")) + p(r("1.2. Неустойка не взыскивается.")) + p(r("1.3. Третий."))
    theirs = p(r("1.1. Первый.")) + p(r("1.3. Третий."))
    doc, changes = _unified(tmp_path, base, theirs)
    texts = ["".join(s["t"] for s in para["segments"]) for para in doc]
    assert texts == ["1.1. Первый.", "1.2. Неустойка не взыскивается.", "1.3. Третий."]
    assert doc[1]["index"] == -1 and doc[1]["segments"][0]["k"] == "silent_del"
    assert doc[1]["changes"] == [c.id for c in changes if c.kind == "para_delete"]


def test_tracked_and_silent_in_one_paragraph(tmp_path):
    base = p(r("1.1. Срок 10 дней, штраф 5%."))
    theirs = p(r("1.1. Срок "), dele("10"), ins("20"), r(" дней, штраф 9%."))
    doc, changes = _unified(tmp_path, base, theirs)
    assert _marked(doc) == [("del", "10"), ("ins", "20"), ("silent_del", "5"), ("silent_ins", "9")]
    assert sorted(doc[0]["changes"]) == sorted(c.id for c in changes)


def test_without_base_only_tracked_changes(tmp_path):
    doc, _ = _unified(tmp_path, None, p(r("1.1. Срок "), dele("10"), ins("20"), r(" дней.")))
    assert _marked(doc) == [("del", "10"), ("ins", "20")]


def test_auto_numbering_label_is_shown_separately(tmp_path):
    from tests.test_reader import NUM

    numbered = '<w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr>'
    theirs = p(r("Срок 10 дней."), ppr=numbered) + p(r("2.2. Номер в тексте."))
    t = read_docx(str(make_docx(tmp_path / "t.docx", theirs, numbering=NUM)))
    doc = build_unified(None, t, set(), [])
    assert [para["label"] for para in doc] == ["1.1", ""]


def test_cosmetic_differences_are_not_marked(tmp_path):
    doc, _ = _unified(tmp_path, p(r("1.1. Услуги «Заказчика» – срок 10 дней.")), p(r('1.1. Услуги "Заказчика" - срок 20 дней.')))
    assert _marked(doc) == [("silent_del", "10"), ("silent_ins", "20")]
