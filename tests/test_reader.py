import pytest

from pravki.docx_reader import DocxError, read_docx, view_paragraphs
from pravki.extract import extract_tracked
from tests.helpers import A, dele, ins, make_docx, p, r


def test_insert_delete_replace(tmp_path):
    f = make_docx(tmp_path / "a.docx", p(r("Срок "), dele("10"), ins("30"), r(" дней.")))
    doc = read_docx(str(f))
    ch = extract_tracked(doc)
    assert len(ch) == 1 and ch[0].kind == "replace" and (ch[0].before, ch[0].after) == ("10", "30")
    assert ch[0].context == "Срок 10 дней." and ch[0].context_after == "Срок 30 дней."
    assert ch[0].author == "Контрагент"


def test_whole_paragraph_inserted_and_deleted(tmp_path):
    body = p(r("Остаётся.")) + p(ins("Новый пункт."), ppr=f'<w:rPr><w:ins w:id="9" {A}/></w:rPr>') + \
        p(dele("Старый пункт."), ppr=f'<w:rPr><w:del w:id="8" {A}/></w:rPr>')
    ch = extract_tracked(read_docx(str(make_docx(tmp_path / "b.docx", body))))
    assert [(c.kind, c.after or c.before) for c in ch] == [("para_insert", "Новый пункт."), ("para_delete", "Старый пункт.")]


def test_two_authors_are_separate_changes(tmp_path):
    body = p(r("а "), ins("X", 1, "Иванов"), r(" б "), ins("Y", 2, "Петров"))
    ch = extract_tracked(read_docx(str(make_docx(tmp_path / "c.docx", body))))
    assert sorted(c.author for c in ch) == ["Иванов", "Петров"]


def test_our_authors_are_not_reported(tmp_path):
    body = p(r("Срок "), ins("30", 1, "Мы"), dele("10", 2, "Они"), r(" дней."))
    doc = read_docx(str(make_docx(tmp_path / "d.docx", body)))
    ch = extract_tracked(doc, ours={"Мы"})
    assert [(c.before, c.after, c.author) for c in ch] == [("10", "", "Они")]


def test_nested_deletion_inside_our_insertion(tmp_path):
    inner = f'<w:ins w:id="1" w:author="Мы" w:date="2026-10-01T00:00:00Z">{dele("30", 2, "Они")}</w:ins>'
    doc = read_docx(str(make_docx(tmp_path / "e.docx", p(r("Срок "), inner, r(" дней.")))))
    ch = extract_tracked(doc, ours={"Мы"})
    assert [(c.kind, c.before) for c in ch] == [("delete", "30")]
    # отклонить чужие правки, свои принять: наш текст «30» возвращается
    assert view_paragraphs(doc, "rejected", {"Мы"})[0][1] == "Срок 30 дней."


def test_moves_are_paired(tmp_path):
    mv_from = f'<w:moveFrom w:id="1" {A}><w:r><w:delText>Переехавший текст.</w:delText></w:r></w:moveFrom>'
    mv_to = f'<w:moveTo w:id="2" {A}><w:r><w:t>Переехавший текст.</w:t></w:r></w:moveTo>'
    body = p("<w:r><w:t>1.1. Первый.</w:t></w:r>") + p(mv_from) + p("<w:r><w:t>2.1. Второй.</w:t></w:r>") + p(mv_to)
    ch = extract_tracked(read_docx(str(make_docx(tmp_path / "f.docx", body))))
    assert len(ch) == 1 and ch[0].kind == "move"


def test_comment_with_anchor(tmp_path):
    body = p('<w:commentRangeStart w:id="0"/>', r("Спорная фраза."), '<w:commentRangeEnd w:id="0"/>',
             '<w:r><w:commentReference w:id="0"/></w:r>')
    com = f'<w:comment w:id="0" {A}><w:p><w:r><w:t>Уберите это</w:t></w:r></w:p></w:comment>'
    ch = extract_tracked(read_docx(str(make_docx(tmp_path / "g.docx", body, comments=com))))
    assert ch[0].kind == "comment" and ch[0].after == "Уберите это" and ch[0].before == "Спорная фраза."


NUM = ('<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
       '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2."/></w:lvl></w:abstractNum>'
       '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>')


def _np(text, lvl):
    return p(r(text), ppr=f'<w:numPr><w:ilvl w:val="{lvl}"/><w:numId w:val="1"/></w:numPr>')


def test_auto_numbering_labels(tmp_path):
    body = _np("Раздел", 0) + _np("a", 1) + _np("b", 1) + _np("Раздел 2", 0) + _np("c", 1)
    doc = read_docx(str(make_docx(tmp_path / "h.docx", body, numbering=NUM)))
    assert [x.label for x in doc.paragraphs] == ["1", "1.1", "1.2", "2", "2.1"]
    assert not doc.paragraphs[1].label_in_text


def test_manual_numbering_labels_and_near(tmp_path):
    body = p(r("3.2. Текст пункта.")) + p(r("Продолжение без номера."))
    doc = read_docx(str(make_docx(tmp_path / "i.docx", body)))
    assert doc.paragraphs[0].label == "3.2" and doc.paragraphs[0].label_in_text
    assert doc.paragraphs[1].label == "" and doc.paragraphs[1].clause == "3.2"


def test_paragraph_split_by_tracked_enter_is_merged_when_rejected(tmp_path):
    # пользователь нажал Enter посреди абзаца: знак абзаца вставлен
    body = p(r("Первая часть. "), ppr=f'<w:rPr><w:ins w:id="1" {A}/></w:rPr>') + p(r("Вторая часть."))
    doc = read_docx(str(make_docx(tmp_path / "j.docx", body)))
    assert [t for _, t in view_paragraphs(doc, "rejected")] == ["Первая часть. Вторая часть."]
    assert len(view_paragraphs(doc, "accepted")) == 2


def test_table_cells_are_read(tmp_path):
    tbl = f'<w:tbl><w:tr><w:tc>{p(r("Цена"))}</w:tc><w:tc>{p(dele("100"), ins("90"))}</w:tc></w:tr></w:tbl>'
    ch = extract_tracked(read_docx(str(make_docx(tmp_path / "k.docx", tbl))))
    assert (ch[0].before, ch[0].after) == ("100", "90")


def test_not_a_docx_is_clear_error(tmp_path):
    f = tmp_path / "x.docx"
    f.write_text("это не zip")
    with pytest.raises(DocxError):
        read_docx(str(f))


def test_xml_entities_are_not_expanded(tmp_path):
    evil = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>')
    doc = read_docx(str(make_docx(tmp_path / "evil.docx", "", raw_document=evil)))
    text = "".join(s.text for para in doc.paragraphs for s in para.segments)
    assert "root:" not in text


def test_mc_fallback_not_duplicated(tmp_path):
    mc = ('<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><mc:Choice Requires="wps">'
          f'{p(r("Текст в рамке"))}</mc:Choice><mc:Fallback>{p(r("Текст в рамке"))}</mc:Fallback></mc:AlternateContent>')
    doc = read_docx(str(make_docx(tmp_path / "mc.docx", mc)))
    assert len(doc.paragraphs) == 1


def _nested(text, ins_author, del_author, n=1):
    """Текст вставил ins_author, а удалил del_author (как пишет Word: w:ins > w:del)."""
    return (f'<w:ins w:id="{n}" w:author="{ins_author}" w:date="2026-10-01T00:00:00Z">'
            f'{dele(text, n + 1, del_author)}</w:ins>')


def test_nested_foreign_insertion_deleted_by_third_party_is_gone_everywhere(tmp_path):
    # контрагент вставил «в течение 5 дней», а затем юрист удалил — текста нет ни там, ни там
    body = p(r("Оплата "), _nested("в течение 5 дней ", "Они", "Мы"), r("производится по счёту."))
    doc = read_docx(str(make_docx(tmp_path / "n1.docx", body)))
    for ours in (set(), {"Мы"}):
        assert view_paragraphs(doc, "rejected", ours)[0][1] == "Оплата производится по счёту."
        assert view_paragraphs(doc, "accepted", ours)[0][1] == "Оплата производится по счёту."


def test_nested_foreign_insertion_not_reported_as_change(tmp_path):
    body = p(r("Оплата "), _nested("в течение 5 дней ", "Они", "Они2"), r("производится по счёту."))
    doc = read_docx(str(make_docx(tmp_path / "n2.docx", body)))
    assert extract_tracked(doc, ours={"Мы"}) == []


def test_nested_whole_paragraph_inserted_and_deleted_gives_no_change(tmp_path):
    body = p(r("1.1. Остаётся.")) + p(_nested("Новый пункт, который потом убрали.", "Они", "Они2"),
                                      ppr=f'<w:rPr><w:ins w:id="9" {A}/></w:rPr>')
    doc = read_docx(str(make_docx(tmp_path / "n3.docx", body)))
    assert extract_tracked(doc, ours={"Мы"}) == []
    assert [t for _, t in view_paragraphs(doc, "rejected", {"Мы"})] == ["1.1. Остаётся."]


def test_nested_our_insertion_deleted_by_them_returns_on_reject_and_is_reported(tmp_path):
    body = p(r("Срок "), _nested("30", "Мы", "Они"), r(" дней."))
    doc = read_docx(str(make_docx(tmp_path / "n4.docx", body)))
    assert view_paragraphs(doc, "rejected", {"Мы"})[0][1] == "Срок 30 дней."
    assert view_paragraphs(doc, "accepted", {"Мы"})[0][1] == "Срок  дней."
    assert [(c.kind, c.before) for c in extract_tracked(doc, ours={"Мы"})] == [("delete", "30")]


def test_nested_both_ours_is_gone(tmp_path):
    body = p(r("Срок "), _nested("30", "Мы", "Мы"), r(" дней."))
    doc = read_docx(str(make_docx(tmp_path / "n5.docx", body)))
    assert view_paragraphs(doc, "rejected", {"Мы"})[0][1] == "Срок  дней."


def test_nested_unknown_insertion_author_is_still_nested(tmp_path):
    # у вставки нет автора (обезличенный файл): удаление всё равно вложенное
    inner = f'<w:ins w:id="1" w:date="2026-10-01T00:00:00Z">{dele("текст", 2, "Они")}</w:ins>'
    doc = read_docx(str(make_docx(tmp_path / "n6.docx", p(r("А "), inner, r(" Б.")))))
    assert view_paragraphs(doc, "rejected", {"Мы"})[0][1] == "А  Б."
    assert extract_tracked(doc, ours={"Мы"}) == []


def test_number_at_paragraph_start_is_not_a_clause_label(tmp_path):
    # «75 % от суммы…» и «475 000 руб.» — условия договора, а не номера пунктов
    body = (p(r("4.11. Размер удержания.")) + p(r("75 % от суммы предоплаты удерживается Организатором.")) +
            p(r("475 000 рублей составляет предоплата.")) + p(r("30 (тридцать) дней на оплату.")) +
            p(r("10.5 % годовых.")))
    doc = read_docx(str(make_docx(tmp_path / "lab.docx", body)))
    assert [x.label for x in doc.paragraphs] == ["4.11", "", "", "", ""]
    assert [x.clause for x in doc.paragraphs] == ["4.11"] * 5
    assert doc.paragraphs[1].segments[0].text.startswith("75 %")


@pytest.mark.parametrize("text,label", [
    ("3.2. Текст", "3.2"), ("3.2 Текст", "3.2"), ("5. Предмет", "5"), ("5) Предмет", "5"), ("5 Предмет договора", "5"),
    ("3.4. (Исключён)", "3.4"), ("1.1.1. Подпункт", "1.1.1"),
])
def test_real_clause_labels_are_kept(tmp_path, text, label):
    doc = read_docx(str(make_docx(tmp_path / "l.docx", p(r(text)))))
    assert doc.paragraphs[0].label == label


def test_appendix_starts_new_section(tmp_path):
    body = (p(r("10. Реквизиты сторон")) + p(r("ИНН 7701234567")) + p(r("Приложение № 1 к Договору на участие в мероприятии"))
            + p(r("Индивидуальные опции:")) + p(r("Выступление с докладом;")))
    paras = read_docx(str(make_docx(tmp_path / "a.docx", body))).paragraphs
    assert [x.clause for x in paras] == ["10", "10", "Приложение 1", "Приложение 1", "Приложение 1"]
    assert paras[4].heading.startswith("Приложение № 1")
