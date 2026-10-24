import pytest

from pravki.docx_reader import DocxError
from pravki.extract import extract_tracked
from pravki.readers import read_document, sniff_format
from tests.helpers import make_docx, make_odt, odt_del, odt_del_region, odt_ins, odt_ins_region, p, r, ins, dele


def tp(*content, style=""):
    st = f' text:style-name="{style}"' if style else ""
    return f"<text:p{st}>{''.join(content)}</text:p>"


def test_tracked_replace_insert_delete_are_read_with_author(tmp_path):
    body = (tp("1. Предмет договора") +
            tp("2.1. Цена ", odt_del("ct1"), odt_ins("ct2", "2 000 000"), " рублей.") +
            tp("2.2. Срок оплаты определён."))
    tracked = odt_del_region("ct1", "2 400 000") + odt_ins_region("ct2")
    doc = read_document(str(make_odt(tmp_path / "t.odt", body, tracked)))
    assert doc.authors == ["Контрагент"] and doc.has_tracked
    para = doc.paragraphs[1]
    assert [(s.kind, s.text, s.author) for s in para.segments] == [
        ("equal", "2.1. Цена ", ""), ("del", "2 400 000", "Контрагент"), ("ins", "2 000 000", "Контрагент"), ("equal", " рублей.", "")]
    assert para.label == "2.1" and para.label_in_text
    assert doc.paragraphs[2].near == "2.1"
    [ch] = extract_tracked(doc)
    assert (ch.kind, ch.clause, ch.before, ch.after, ch.author) == ("replace", "2.1", "2 400 000", "2 000 000", "Контрагент")


def test_inserted_and_deleted_whole_paragraphs(tmp_path):
    # вставка начинается в одном абзаце и заканчивается в следующем: оба абзаца вставлены целиком
    body = (tp("3.1. Поставка.") + tp('<text:change-start text:change-id="ct1"/>3.2. Новое условие первое.') +
            tp("3.3. Ещё одно новое.", '<text:change-end text:change-id="ct1"/>') + tp(odt_del("ct2")) + tp("3.4. Остаётся."))
    tracked = odt_ins_region("ct1") + odt_del_region("ct2", "3.9. Старое условие.")
    changes = extract_tracked(read_document(str(make_odt(tmp_path / "t.odt", body, tracked))))
    assert [(c.kind, c.clause, c.before, c.after) for c in changes] == [
        ("para_insert", "3.2", "", "Новое условие первое."),
        ("para_insert", "3.3", "", "Ещё одно новое."),
        ("para_delete", "3.9", "Старое условие.", "")]
    # вставка закрылась: следующий абзац обычный
    doc = read_document(str(make_odt(tmp_path / "t.odt", body, tracked)))
    assert [s.kind for s in doc.paragraphs[4].segments] == ["equal"]


def test_comment_with_anchor_and_author(tmp_path):
    body = tp("5.3. Ответственность ", '<office:annotation office:name="a1"><dc:creator>Иванов И.</dc:creator>'
              '<dc:date>2026-10-05T11:00:00</dc:date><text:p>Просим исключить.</text:p></office:annotation>',
              "ограничена суммой", '<office:annotation-end office:name="a1"/>', " договора.")
    doc = read_document(str(make_odt(tmp_path / "t.odt", body)))
    [c] = doc.comments.values()
    assert (c.author, c.text, c.anchor, c.paragraph_index) == ("Иванов И.", "Просим исключить.", "ограничена суммой", 0)
    assert doc.paragraphs[0].comment_ids == [c.id]
    assert "Просим" not in "".join(s.text for s in doc.paragraphs[0].segments)
    [ch] = extract_tracked(doc)
    assert ch.kind == "comment" and ch.after == "Просим исключить." and ch.clause == "5.3"


def test_automatic_list_numbering_gives_clause_labels(tmp_path):
    auto = ('<text:list-style style:name="L1"><text:list-level-style-number text:level="1" style:num-format="1"/>'
            '<text:list-level-style-number text:level="2" style:num-format="1" text:display-levels="2"/></text:list-style>')
    body = ('<text:list text:style-name="L1">'
            '<text:list-item>' + tp("Предмет договора") +
            '<text:list><text:list-item>' + tp("Поставщик поставляет товар.") + '</text:list-item>'
            '<text:list-item>' + tp("Покупатель оплачивает товар.") + '</text:list-item></text:list></text:list-item>'
            '<text:list-item>' + tp("Цена договора") +
            '<text:list><text:list-item>' + tp("Цена указана в рублях.") + '</text:list-item></text:list></text:list-item></text:list>')
    doc = read_document(str(make_odt(tmp_path / "t.odt", body, automatic=auto)))
    assert [p_.label for p_ in doc.paragraphs] == ["1", "1.1", "1.2", "2", "2.1"]  # у нового пункта счёт вложенных начинается с 1
    assert not any(p_.label_in_text for p_ in doc.paragraphs)
    assert doc.paragraphs[1].list_kind == "number" and doc.paragraphs[1].level == 1


def test_bullets_have_no_label(tmp_path):
    auto = '<text:list-style style:name="B"><text:list-level-style-bullet text:level="1"/></text:list-style>'
    body = '<text:list text:style-name="B"><text:list-item>' + tp("первый пункт перечня") + "</text:list-item></text:list>"
    [para] = read_document(str(make_odt(tmp_path / "t.odt", body, automatic=auto))).paragraphs
    assert para.label == "" and para.list_kind == "bullet"


def test_table_cells_keep_position(tmp_path):
    body = ('<table:table><table:table-row><table:table-cell>' + tp("Наименование") + '</table:table-cell>'
            '<table:table-cell>' + tp("Цена") + '</table:table-cell></table:table-row>'
            '<table:table-row><table:table-cell>' + tp("Товар") + '</table:table-cell>'
            '<table:table-cell>' + tp("100") + '</table:table-cell></table:table-row></table:table>')
    paras = read_document(str(make_odt(tmp_path / "t.odt", body))).paragraphs
    assert [(x.in_table, x.table) for x in paras] == [(True, (0, 0, 0, 1)), (True, (0, 0, 1, 1)), (True, (0, 1, 0, 1)), (True, (0, 1, 1, 1))]


def test_spaces_tabs_and_bold_spans(tmp_path):
    auto = '<style:style style:name="T1" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>'
    body = tp('Цена:<text:s text:c="2"/><text:span text:style-name="T1">100</text:span><text:tab/>руб.')
    [para] = read_document(str(make_odt(tmp_path / "t.odt", body, automatic=auto))).paragraphs
    assert [(s.text, s.bold) for s in para.segments] == [("Цена:  ", False), ("100", True), ("\tруб.", False)]


def test_sniff_formats_and_bad_files(tmp_path):
    odt = str(make_odt(tmp_path / "a.odt", tp("текст")))
    docx = str(make_docx(tmp_path / "a.docx", p(r("текст"))))
    assert sniff_format(odt) == "odt" and sniff_format(docx) == "docx"
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert sniff_format(str(pdf)) == "pdf"
    txt = tmp_path / "a.txt"
    txt.write_text("hello")
    for bad in (str(txt), str(make_odt(tmp_path / "s.ods", tp("x"), mimetype="application/vnd.oasis.opendocument.spreadsheet")),
                str(tmp_path / "нет.odt")):
        with pytest.raises(DocxError):
            sniff_format(bad)
    broken = tmp_path / "b.odt"
    broken.write_bytes(b"PK\x03\x04garbage")
    with pytest.raises(DocxError):
        read_document(str(broken))


def test_docx_and_odt_of_the_same_contract_give_the_same_changes(tmp_path):
    docx = make_docx(tmp_path / "t.docx",
                     p(r("1. Предмет договора")) +
                     p(r("2.1. Цена "), dele("2 400 000", 1), ins("2 000 000", 2), r(" рублей.")) +
                     p(ins("2.2. Новый пункт об авансе.", 3)) +
                     p(r("2.3. Срок оплаты определён.")))
    body = (tp("1. Предмет договора") + tp("2.1. Цена ", odt_del("c1"), odt_ins("c2", "2 000 000"), " рублей.") +
            tp(odt_ins("c3", "2.2. Новый пункт об авансе.")) + tp("2.3. Срок оплаты определён."))
    odt = make_odt(tmp_path / "t.odt", body, odt_del_region("c1", "2 400 000") + odt_ins_region("c2") + odt_ins_region("c3"))
    key = lambda doc: [(c.kind, c.clause, c.before, c.after, c.author) for c in extract_tracked(doc)]
    from pravki.docx_reader import read_docx
    from pravki.odt_reader import read_odt

    assert key(read_odt(str(odt))) == key(read_docx(str(docx)))
    assert len(key(read_odt(str(odt)))) == 2


def test_merged_cells_shift_columns(tmp_path):
    body = ('<table:table><table:table-row><table:table-cell table:number-columns-spanned="2">' + tp("Итого") + '</table:table-cell>'
            '<table:covered-table-cell/><table:table-cell>' + tp("100") + '</table:table-cell></table:table-row></table:table>')
    paras = read_document(str(make_odt(tmp_path / "t.odt", body))).paragraphs
    assert [x.table for x in paras] == [(0, 0, 0, 2), (0, 0, 2, 1)]


def test_numbering_continues_only_when_the_list_says_so(tmp_path):
    auto = '<text:list-style style:name="L1"><text:list-level-style-number text:level="1" style:num-format="1"/></text:list-style>'
    item = lambda t: "<text:list-item>" + tp(t) + "</text:list-item>"
    body = ('<text:list text:style-name="L1">' + item("Первый пункт") + item("Второй пункт") + "</text:list>" + tp("Пояснение между списками.") +
            '<text:list text:style-name="L1" text:continue-numbering="true">' + item("Третий пункт") + "</text:list>" +
            tp("Ещё пояснение.") + '<text:list text:style-name="L1">' + item("Новый список") + "</text:list>")
    doc = read_document(str(make_odt(tmp_path / "t.odt", body, automatic=auto)))
    assert [p_.label for p_ in doc.paragraphs if p_.list_kind] == ["1", "2", "3", "1"]
