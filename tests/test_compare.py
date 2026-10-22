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


# ---------------------------------------------------------------- накопительный файл: правки контрагента прошлых раундов
def _cumulative(tmp_path):
    """Отправленная версия содержит нерешённую правку Admin прошлого раунда и нашу правку; контрагент добавил новую."""
    old_admin = lambda n: dele("5", n, "Admin") + ins("10", n + 1, "Admin")  # noqa: E731
    base = (p(r("1.1. Оплата в течение "), old_admin(1), r(" дней.")) +
            p(r("1.2. Неустойка "), ins("0,1%", 3, "Мы"), r(" в день.")) +
            p(r("1.3. Срок поставки 7 дней.")))
    theirs = (p(r("1.1. Оплата в течение "), old_admin(1), r(" дней.")) +
              p(r("1.2. Неустойка "), ins("0,1%", 3, "Мы"), r(" в день.")) +
              p(r("1.3. Срок поставки "), dele("7", 4, "Admin"), ins("20", 5, "Admin"), r(" дней.")))
    b = str(make_docx(tmp_path / "base.docx", base))
    t = str(make_docx(tmp_path / "theirs.docx", theirs))
    return b, t


def test_pending_changes_of_previous_round_are_carried_not_silent(tmp_path):
    b, t = _cumulative(tmp_path)
    ch = compare_versions(read_docx(b), read_docx(t), ["Мы"])
    assert [c for c in ch if c.source != "tracked"] == []  # ничего «тихого»
    by_after = {c.after: c for c in ch}
    assert by_after["10"].detail.get("carried") and "из прошлого раунда" in by_after["10"].flags
    assert not by_after["20"].detail.get("carried")


def test_foreign_author_in_sent_version_is_not_taken_as_ours(tmp_path):
    from pravki.pipeline import review_files
    b, t = _cumulative(tmp_path)
    rv = review_files(t, base_path=b, our_authors=["Мы"])
    assert any(c.after == "20" and c.author == "Admin" for c in rv.changes)  # новая правка не пропала
    assert any("не указанные как наши: Admin" in w for w in rv.warnings)
    assert any("нерешёнными" in w for w in rv.warnings)


def test_several_authors_without_explicit_ours_hides_nobody(tmp_path):
    from pravki.pipeline import review_files
    b, t = _cumulative(tmp_path)
    rv = review_files(t, base_path=b)
    assert any(c.after == "20" for c in rv.changes)
    assert any("наши авторы не указаны" in w for w in rv.warnings)


def test_single_author_of_sent_version_is_still_ours(tmp_path):
    base = p(r("1.1. Срок "), dele("5", 1, "Мы"), ins("10", 2, "Мы"), r(" дней."))
    theirs = p(r("1.1. Срок "), dele("5", 1, "Мы"), ins("10", 2, "Мы"), r(" дней."))
    b = read_docx(str(make_docx(tmp_path / "b.docx", base)))
    t = read_docx(str(make_docx(tmp_path / "t.docx", theirs)))
    assert compare_versions(b, t) == []


def test_accepted_tracked_change_from_our_version_is_named(tmp_path):
    # правку в нашей версии внёс коллега (его нет среди наших авторов), контрагент принял её без отметки
    base = p(r("1.1. Срок "), ins("10", author="Коллега"), r(" дней."))
    b, t = _docs(tmp_path, base, p(r("1.1. Срок 10 дней.")))
    ch = compare_versions(b, t, ["kandu"])
    assert len(ch) == 1 and ch[0].detail.get("accepted_from_base") == ["Коллега"]
    assert "Коллега" in ch[0].notes[0]


def test_real_silent_edit_is_not_taken_for_accepted_change(tmp_path):
    base = p(r("1.1. Срок "), ins("10", author="Коллега"), r(" дней."))
    b, t = _docs(tmp_path, base, p(r("1.1. Срок 15 дней.")))
    ch = compare_versions(b, t, ["kandu"])
    assert ch and not any(c.detail.get("accepted_from_base") for c in ch)
