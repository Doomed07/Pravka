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
    theirs = p(r("1.1. Срок "), dele("10", author="Юрист"), ins("20", author="Юрист"), r(" дней."))
    doc, _ = _unified(tmp_path, p(r("1.1. Срок 20 дней.")), theirs, ours=["Юрист"])
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


# ---------------------------------------------------------------- таблицы
def _tc(*paras, span=1):
    pr = f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>' if span > 1 else ""
    return f"<w:tc>{pr}{''.join(paras)}</w:tc>"


def _tbl(*rows):
    return "<w:tbl>" + "".join(f"<w:tr>{''.join(r)}</w:tr>" for r in rows) + "</w:tbl>"


def test_table_cells_keep_coordinates_and_empty_cells(tmp_path):
    """Таблица из Word не рассыпается: у каждой ячейки есть номер таблицы, строка, столбец; пустые ячейки на месте."""
    from pravki.pipeline import review_files
    from tests.helpers import make_docx, p, r

    def doc(price):
        return (p(r("1.2. Перечень оказываемых услуг")) +
                _tbl([_tc(p(r("№"))), _tc(p(r("Наименование услуги"))), _tc(p(r("Сумма, руб.")))],
                     [_tc(p(r("1"))), _tc(p(r("Участие в мероприятии"))), _tc(p(r(price)))],
                     [_tc(p(r("Итого")), span=2), _tc(p(r("")))]) +
                p(r("Содержание услуги закреплено в Приложении № 1.")))

    base = make_docx(tmp_path / "base.docx", doc("475 000"))
    theirs = make_docx(tmp_path / "theirs.docx", doc("500 000"))  # цену поменяли без отметки
    rv = review_files(str(theirs), str(base))
    cells = [d for d in rv.document if d["table"]]
    assert len(cells) == 8  # 3 + 3 + 2 ячейки, включая пустую; старое значение цены — в той же ячейке
    assert {tuple(d["table"][:3]) for d in cells} == {(0, 0, 0), (0, 0, 1), (0, 0, 2), (0, 1, 0), (0, 1, 1), (0, 1, 2),
                                                      (0, 2, 0), (0, 2, 2)}
    itogo = next(d for d in cells if d["table"][1] == 2 and d["table"][2] == 0)
    assert itogo["table"][3] == 2  # объединённая ячейка шириной в два столбца
    price = [s for d in cells if d["table"][1] == 1 and d["table"][2] == 2 for s in d["segments"]]
    # тихая правка цены видна в своей ячейке: было 475 000, стало 500 000 (одна правка, а не удалённый и вставленный абзац)
    assert {(s["k"], s["t"]) for s in price} == {("silent_del", "475 000"), ("silent_ins", "500 000")}
    assert [(c.kind, c.before, c.after) for c in rv.changes] == [("replace", "475 000", "500 000")]
    # таблица идёт одним куском: между её ячейками нет абзацев вне таблицы
    flags = [bool(d["table"]) for d in rv.document]
    assert flags == [False] + [True] * 8 + [False]
    outside = [d for d in rv.document if not d["table"]]
    assert all(d["table"] is None for d in outside) and len(outside) == 2


def test_replaced_clause_is_one_change_on_both_paragraphs(tmp_path):
    base = p(r("1.3. Первый.")) + p(r("1.4. Список направляется на почту за 1 день.")) + p(r("1.5. Последний."))
    theirs = p(r("1.3. Первый.")) + p(r("1.4. Список определяется формой на сайте за 5 дней.")) + p(r("1.5. Последний."))
    doc, changes = _unified(tmp_path, base, theirs)
    assert len(changes) == 1 and changes[0].kind == "replace" and changes[0].detail["replaced_para"] == "clause"
    assert "почту" in changes[0].before and "сайте" in changes[0].after
    assert [para["changes"] for para in doc] == [[], [changes[0].id], [changes[0].id], []]


def test_party_comments_are_kept_whole_with_side(tmp_path):
    body = p('<w:commentRangeStart w:id="1"/>', r("1.1. Срок 10 дней."), '<w:commentRangeEnd w:id="1"/>',
             '<w:r><w:commentReference w:id="1"/></w:r>')
    comments = ('<w:comment w:id="1" w:author="Юрист" w:date="2026-03-27T10:00:00Z"><w:p><w:r><w:t>Просим 10 дней.</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Иначе не успеем.</w:t></w:r></w:p></w:comment>')
    t = read_docx(str(make_docx(tmp_path / "t.docx", body, comments=comments)))
    doc = build_unified(None, t, {"Юрист"}, [])
    assert doc[0]["comments"] == [{"author": "Юрист", "date": "2026-03-27T10:00:00Z", "text": "Просим 10 дней.\nИначе не успеем.",
                                   "ours": True, "anchor": "1.1. Срок 10 дней."}]
