from pravki.compare import compare_versions
from pravki.docx_reader import read_docx
from tests.helpers import dele, ins, make_docx, p, r


def _docs(tmp_path, base_body, theirs_body, **kw):
    b = read_docx(str(make_docx(tmp_path / "base.docx", base_body)))
    t = read_docx(str(make_docx(tmp_path / "theirs.docx", theirs_body, **kw)))
    return b, t


def test_identical_documents_have_no_changes(tmp_path):
    body = p(r("1.1. Текст.")) + p(r("1.2. Ещё текст."))
    b, t = _docs(tmp_path, body, body)
    assert compare_versions(b, t) == []


def test_silent_edit_is_found(tmp_path):
    b, t = _docs(tmp_path, p(r("2.2. Оплата в течение 10 дней.")), p(r("2.2. Оплата в течение 30 дней.")))
    ch = compare_versions(b, t)
    assert len(ch) == 1 and ch[0].source == "diff" and (ch[0].before, ch[0].after) == ("10", "30")


def test_silent_edit_next_to_tracked_one(tmp_path):
    base = p(r("1.1. Срок 10 дней.")) + p(r("1.2. Штраф 5%."))
    theirs = p(r("1.1. Срок "), dele("10"), ins("20"), r(" дней.")) + p(r("1.2. Штраф 9%."))
    b, t = _docs(tmp_path, base, theirs)
    ch = compare_versions(b, t)
    assert [(c.source, c.before, c.after) for c in ch] == [("tracked", "10", "20"), ("silent", "5", "9")]


def test_rejecting_tracked_changes_restores_base(tmp_path):
    base = p(r("1.1. Срок 10 дней."))
    theirs = p(r("1.1. Срок "), dele("10"), ins("20"), r(" дней."))
    b, t = _docs(tmp_path, base, theirs)
    assert [c.source for c in compare_versions(b, t)] == ["tracked"]


def test_cosmetic_differences_are_ignored(tmp_path):
    base = p(r("1.1. Услуги «Заказчика» – по договору."))
    theirs = p(r('1.1. Услуги  "Заказчика"  -  по договору.'))
    b, t = _docs(tmp_path, base, theirs)
    assert compare_versions(b, t) == []


def test_empty_paragraphs_do_not_matter(tmp_path):
    base = p(r("1.1. А.")) + p(r("1.2. Б."))
    theirs = p() + p(r("1.1. А.")) + p() + p() + p(r("1.2. Б."))
    b, t = _docs(tmp_path, base, theirs)
    assert compare_versions(b, t) == []


def test_silent_paragraph_deleted_and_inserted(tmp_path):
    base = p(r("1.1. Первый.")) + p(r("1.2. Защитное положение об ответственности.")) + p(r("1.3. Третий."))
    theirs = p(r("1.1. Первый.")) + p(r("1.3. Третий.")) + p(r("1.4. Совсем новый пункт."))
    b, t = _docs(tmp_path, base, theirs)
    kinds = sorted(c.kind for c in compare_versions(b, t))
    assert kinds == ["para_delete", "para_insert"]


def test_our_tracked_changes_in_their_file_are_not_theirs(tmp_path):
    # мы отправили версию с нашей правкой; контрагент её не трогал
    base = p(r("1.1. Срок "), ins("30", 1, "Мы"), r(" дней."))
    theirs = p(r("1.1. Срок "), ins("30", 1, "Мы"), r(" дней."))
    b, t = _docs(tmp_path, base, theirs)
    assert compare_versions(b, t, our_authors=["Мы"]) == []


def test_no_base_gives_only_tracked(tmp_path):
    t = read_docx(str(make_docx(tmp_path / "t.docx", p(r("1.1. "), ins("Новое."), r(" Старое.")))))
    ch = compare_versions(None, t)
    assert len(ch) == 1 and ch[0].source == "tracked"


def test_reordered_clauses_are_reported(tmp_path):
    base = p(r("1.1. Раз.")) + p(r("1.2. Два.")) + p(r("1.3. Три."))
    theirs = p(r("1.1. Раз.")) + p(r("1.3. Три.")) + p(r("1.2. Два."))
    b, t = _docs(tmp_path, base, theirs)
    assert compare_versions(b, t)  # перестановка не должна пройти незамеченной
