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


def _unlabeled(tmp_path):
    base = p(r("Вводный абзац.")) + p(r("Список делегатов направляется на почту.")) + p(r("Заключительный абзац."))
    theirs = p(r("Вводный абзац.")) + p(r("Делегатов регистрируют через форму на сайте.")) + p(r("Заключительный абзац."))
    return _docs(tmp_path, base, theirs)


def test_unnumbered_replacement_is_merged_only_if_model_says_so(tmp_path):
    b, t = _unlabeled(tmp_path)
    assert [c.kind for c in compare_versions(b, t)] == ["para_delete", "para_insert"]
    assert [c.kind for c in compare_versions(b, t, judge=lambda x, y: False)] == ["para_delete", "para_insert"]
    merged = compare_versions(b, t, judge=lambda x, y: True)
    assert [c.kind for c in merged] == ["replace"] and merged[0].detail["replaced_para"] == "model"


def test_model_merged_replacement_goes_to_lawyer(tmp_path):
    from pravki.parties import SideConfig
    from pravki.pipeline import review_files

    class Judge:
        def same_condition(self, a, b):
            return True

        def confirms_technical(self, ch):
            return True

        def apply(self, ch, neighbours=()):
            pass

    clause = p(r("1. Предмет договора"))
    base = clause + p(r("Список делегатов направляется на почту.")) + p(r("Заключительный абзац."))
    theirs = clause + p(r("Делегатов регистрируют через форму на сайте.")) + p(r("Заключительный абзац."))
    rv = review_files(str(make_docx(tmp_path / "t.docx", theirs)), str(make_docx(tmp_path / "b.docx", base)),
                      "playbooks/services_example.yaml", explainer=Judge(), side=SideConfig(confirm_role="Исполнитель"))
    ch = next(c for c in rv.changes if c.detail.get("replaced_para"))
    assert ch.lawyer_decision_needed and "заменён" in ch.action


def test_model_cannot_merge_paragraphs_on_different_topics(tmp_path):
    base = p(r("Вводный абзац.")) + p(r("Исполнитель вправе привлекать субподрядчиков.")) + p(r("Заключительный абзац."))
    theirs = p(r("Вводный абзац.")) + p(r("Стоимость услуг включает НДС 20%.")) + p(r("Заключительный абзац."))
    b, t = _docs(tmp_path, base, theirs)
    assert [c.kind for c in compare_versions(b, t, judge=lambda x, y: True)] == ["para_delete", "para_insert"]


# ---------------------------------------------------------------- юрист начал отвечать прямо в файле контрагента
def _at(tag, text, n, author, date):
    t = "delText" if tag == "del" else "t"
    return f'<w:{tag} w:id="{n}" w:author="{author}" w:date="{date}"><w:r><w:{t} xml:space="preserve">{text}</w:{t}></w:r></w:{tag}>'


def _answered_in_their_file(tmp_path):
    """Отправили версию с нашей правкой от 27.03; контрагент вставил «не позднее 8 апреля», а мы 01.04 прямо в его
    файле заменили «8» на «12» и дописали ОГРНИП."""
    sent = "2026-03-27T16:00:00Z"
    later = "2026-04-01T10:00:00Z"
    base = p(r("1.1. Оплата по счёту"), _at("ins", " Организатора", 1, "Мы", sent), r(".")) + p(r("Реквизиты: ИНН 123."))
    nested_del = ('<w:ins w:id="5" w:author="Admin" w:date="2026-03-30T10:00:00Z"><w:del w:id="6" w:author="Мы" '
                  f'w:date="{later}"><w:r><w:delText xml:space="preserve">8</w:delText></w:r></w:del></w:ins>')
    theirs = (p(r("1.1. Оплата по счёту"), _at("ins", " Организатора", 1, "Мы", sent),
                _at("ins", ", но не позднее ", 4, "Admin", "2026-03-30T10:00:00Z"), _at("ins", "12", 7, "Мы", later),
                nested_del, _at("ins", " апреля", 8, "Admin", "2026-03-30T10:00:00Z"), r(".")) +
              p(r("Реквизиты: ИНН 123."), _at("ins", " ОГРНИП 456.", 9, "Мы", later)))
    return str(make_docx(tmp_path / "base.docx", base)), str(make_docx(tmp_path / "theirs.docx", theirs))


def test_our_edits_made_after_sent_version_are_not_theirs(tmp_path):
    from pravki.pipeline import review_files
    b, t = _answered_in_their_file(tmp_path)
    rv = review_files(t, base_path=b, our_authors=["Мы"])
    assert [c for c in rv.changes if c.source != "tracked"] == []  # «12» и ОГРНИП — не «тихие» правки контрагента
    assert [(c.author, c.after) for c in rv.changes] == [("Admin", ", но не позднее 8 апреля")]  # «8» контрагента на месте
    assert any("ваши правки, сделанные после отправленной версии (мест: 3, пункты: 1.1)" in w for w in rv.warnings)


def test_our_old_edits_left_in_their_file_stay_ours(tmp_path):
    from pravki.compare import without_new_ours
    b, t = _answered_in_their_file(tmp_path)
    doc, n = without_new_ours(read_docx(b), read_docx(t), {"Мы"})
    first = "".join(s.text for s in doc.paragraphs[0].segments if s.author == "Мы")
    assert n == 3 and first == " Организатора"  # правка из отправленной версии осталась нашей


def test_our_later_rework_of_our_own_insertion_is_not_silent(tmp_path):
    # 27.03 мы вписали абзац; 31.03 переписали свою же вставку прямо в файле контрагента: часть старого текста
    # исчезла без отметки (свою вставку Word удаляет без следа). Это наша правка, а не «тихая» правка контрагента
    from pravki.pipeline import review_files
    sent, later = "2026-03-27T16:00:00Z", "2026-03-31T15:00:00Z"
    base = p(r("1.4. Права.")) + p(_at("ins", "Список направляется на почту за 1 день.", 1, "Мы", sent))
    theirs = p(r("1.4. Права.")) + p(_at("ins", "Список", 1, "Мы", sent), _at("ins", " заполняется на сайте", 2, "Мы", later),
                                      _at("ins", " за 5 дней.", 3, "Мы", sent))
    b, t = str(make_docx(tmp_path / "b.docx", base)), str(make_docx(tmp_path / "t.docx", theirs))
    rv = review_files(t, base_path=b, our_authors=["Мы"])
    assert rv.changes == []
    # а «тихая» правка контрагента в том же абзаце видна
    theirs2 = p(r("1.4. Права ИЗМЕНЕНЫ.")) + p(_at("ins", "Список", 1, "Мы", sent),
                                                _at("ins", " заполняется на сайте", 2, "Мы", later))
    t2 = str(make_docx(tmp_path / "t2.docx", theirs2))
    silent = [c.after for c in review_files(t2, base_path=b, our_authors=["Мы"]).changes if c.source == "silent"]
    assert len(silent) == 1 and "ИЗМЕНЕНЫ" in silent[0]


def test_restored_text_is_silent_even_where_we_edited_later(tmp_path):
    # мы удалили фразу 27.03; контрагент отклонил удаление (фраза вернулась без отметки), а мы 31.03 поправили пункт
    from pravki.pipeline import review_files
    sent, later = "2026-03-27T16:00:00Z", "2026-03-31T15:00:00Z"
    base = p(r("6.1. Срок договора."), _at("del", " Организатор вправе расторгнуть без убытков.", 1, "Мы", sent))
    theirs = p(r("6.1. Срок договора."), _at("ins", " Год.", 2, "Мы", later), r(" Организатор вправе расторгнуть без убытков."))
    b, t = str(make_docx(tmp_path / "b.docx", base)), str(make_docx(tmp_path / "t.docx", theirs))
    silent = [c.after for c in review_files(t, base_path=b, our_authors=["Мы"]).changes if c.source != "tracked"]
    assert len(silent) == 1 and "расторгнуть" in silent[0]


def test_site_shows_our_later_edits_as_plain_text(tmp_path):
    # на сайте договор как в Word: наши новые правки — обычный текст, а не «правки без отметки» контрагента
    from pravki.pipeline import review_files
    b, t = _answered_in_their_file(tmp_path)
    doc = review_files(t, base_path=b, our_authors=["Мы"]).document
    kinds = {s["k"] for para in doc for s in para["segments"]}
    text = " ".join("".join(s["t"] for s in para["segments"] if s["k"] in ("equal", "ins")) for para in doc)
    assert not kinds & {"silent_ins", "silent_del", "own"}
    assert "12" in text and "ОГРНИП 456" in text


def test_site_marks_their_silent_edit_but_not_ours_in_the_same_clause(tmp_path):
    from pravki.pipeline import review_files
    sent, later = "2026-03-27T16:00:00Z", "2026-04-01T10:00:00Z"
    base = p(r("Реквизиты: ИНН 123, счёт 40702."), _at("ins", " Банк А.", 1, "Мы", sent))
    theirs = p(r("Реквизиты: ИНН 123, счёт 99999."), _at("ins", " Банк А.", 1, "Мы", sent), _at("ins", " ОГРНИП 456.", 2, "Мы", later))
    b, t = str(make_docx(tmp_path / "b.docx", base)), str(make_docx(tmp_path / "t.docx", theirs))
    doc = review_files(t, base_path=b, our_authors=["Мы"]).document
    silent = "".join(s["t"] for para in doc for s in para["segments"] if s["k"] == "silent_ins")
    assert "99999" in silent and "ОГРНИП" not in silent


def _mark_del(n, author="Контрагент"):
    return f'<w:rPr><w:del w:id="{n}" w:author="{author}" w:date="2026-10-05T10:00:00Z"/></w:rPr>'


def test_breaks_in_requisites_are_one_change(tmp_path):
    # контрагент свёл строки реквизитов в одну: три удалённых знака абзаца подряд — одна правка, а не три
    from pravki.extract import extract_tracked
    body = (p(r("10. Реквизиты сторон")) + p(r("Адрес: г. Москва"), ppr=_mark_del(1)) + p(r("ИНН 7701234567"), ppr=_mark_del(2)) +
            p(r("Банк: Альфа"), ppr=_mark_del(3)) + p(r("БИК 044525593")) + p(r("Телефон: 123"), ppr=_mark_del(4)) + p(r("Почта: a@b.ru")))
    doc = read_docx(str(make_docx(tmp_path / "t.docx", body)))
    breaks = [c for c in extract_tracked(doc) if "склейка абзацев" in c.flags]
    assert [c.before for c in breaks] == ["[разрыв абзаца] × 3", "[разрыв абзаца]"]
    assert breaks[0].detail["revs"] == ["1", "2", "3"] and breaks[0].detail["breaks"] == [1, 2, 3]
