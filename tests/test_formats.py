"""Те же договоры в других форматах: odt и PDF дают те же правки и те же выводы плейбука, что docx."""
import base64
import re

import pytest

from pravki import engine_api
from pravki.compare import label_policy
from pravki.docx_reader import DocxError, read_docx
from pravki.pdf_reader import PDF_NOTE
from pravki.pipeline import review_files
from pravki.playbook import load_playbook
from pravki.readers import read_document
from pravki.synth import generate_case, side_config
from tests.helpers import make_docx, make_odt, odt_from_doc, p, pdf_from_docx, r

CASES = [("supply", seed) for seed in (1, 3, 5)] + [("services", seed) for seed in (1, 2, 4)]


def _pb(tpl):
    return load_playbook(f"playbooks/{tpl}_example.yaml")


def _key(rv, with_body=True):
    return sorted((c.clause, c.kind, c.before if c.kind != "comment" else "", c.after, c.source, c.topic, c.level) for c in rv.changes
                  if with_body or c.kind != "comment")


@pytest.mark.parametrize("tpl,seed", CASES)
def test_odt_gives_the_same_review_as_docx(tmp_path, tpl, seed):
    case = generate_case(str(tmp_path / "c"), tpl, seed)
    for variant in ("tracked", "clean"):  # с рецензированием и без: во втором все отличия найдены сравнением
        a = review_files(case["paths"][variant], case["paths"]["base"], _pb(tpl), side=side_config(case))
        theirs = odt_from_doc(tmp_path / f"{variant}.odt", read_docx(case["paths"][variant]))
        base = odt_from_doc(tmp_path / "base.odt", read_docx(case["paths"]["base"]))
        b = review_files(str(theirs), str(base), _pb(tpl), side=side_config(case))
        assert _key(a) == _key(b), (tpl, seed, variant)
        assert len(b.changes) > 5


@pytest.mark.parametrize("tpl,seed", CASES)
def test_pdf_gives_the_same_changes_as_docx_compared_to_our_docx(tmp_path, tpl, seed):
    case = generate_case(str(tmp_path / "c"), tpl, seed)
    ref = review_files(case["paths"]["clean"], case["paths"]["base"], _pb(tpl), side=side_config(case))
    pdf = pdf_from_docx(tmp_path / "t.pdf", case["paths"]["clean"])
    got = review_files(str(pdf), case["paths"]["base"], _pb(tpl), side=side_config(case))
    # комментарии в PDF не переносятся; номера пунктов в PDF напечатаны, у нашего docx — автонумерация: правок «1.» быть не должно
    assert _key(ref, with_body=False) == _key(got, with_body=False), (tpl, seed)
    assert PDF_NOTE in got.warnings and len(got.changes) > 5
    segments = [s for para in got.document for s in para["segments"]]
    assert any(s["k"] == "silent_ins" for s in segments)  # правки без отметки видны в единой версии
    # напечатанный в PDF номер пункта не должен выглядеть вставкой: «1.», «2.1.» и т. п.
    assert not [s for s in segments if s["k"] == "silent_ins" and re.fullmatch(r"\s*(?:\d{1,2}(?:\.\d{1,2}){1,3}[.)]?|\d{1,2}[.)])\s*", s["t"]) and s["t"].count(".") < 3]


def test_pdf_needs_our_version(tmp_path):
    case = generate_case(str(tmp_path / "c"), "supply", 1)
    pdf = pdf_from_docx(tmp_path / "t.pdf", case["paths"]["clean"])
    with pytest.raises(DocxError, match="нужна ваша отправленная версия"):
        review_files(str(pdf), None, _pb("supply"))


def test_typed_vs_unnumbered_labels_are_not_changes(tmp_path):
    typed = make_docx(tmp_path / "t.docx", p(r("1. Цена и порядок оплаты")) + p(r("1.1. Цена товара составляет 100 рублей.")))
    plain = make_docx(tmp_path / "p.docx", p(r("Цена и порядок оплаты")) + p(r("Цена товара составляет 100 рублей.")))
    t, pl = read_docx(str(typed)), read_docx(str(plain))
    assert label_policy(pl, t) == (False, True)  # напечатанные номера есть только у версии контрагента: убираем их оттуда
    assert label_policy(t, pl) == (True, False)
    assert label_policy(t, t) == (False, False)  # номера напечатаны в обеих: изменённый номер — правка
    assert label_policy(pl, pl) == (False, False)
    assert review_files(str(typed), str(plain), None).changes == []
    assert review_files(str(plain), str(typed), None).changes == []
    # настоящая правка в тексте при разной нумерации находится, а номера не мешают
    edited = make_docx(tmp_path / "e.docx", p(r("1. Цена и порядок оплаты")) + p(r("1.1. Цена товара составляет 120 рублей.")))
    [ch] = review_files(str(edited), str(plain), None).changes
    assert (ch.kind, ch.before, ch.after) == ("replace", "100", "120")


def test_changed_number_is_still_a_change_when_both_type_numbers(tmp_path):
    a = make_docx(tmp_path / "a.docx", p(r("1. Предмет договора")) + p(r("1.1. Поставщик поставляет товар партиями по заявкам.")))
    b = make_docx(tmp_path / "b.docx", p(r("1. Предмет договора")) + p(r("1.2. Поставщик поставляет товар партиями по заявкам.")))
    [ch] = review_files(str(b), str(a), None).changes
    assert (ch.kind, ch.before, ch.after) == ("replace", "1.1", "1.2")


def _post(tmp_path, theirs, base, extra=None):
    files = {"theirs": open(theirs, "rb").read()}
    if base:
        files["base"] = open(base, "rb").read()
    return engine_api.review({"playbook": "supply_example.yaml", "confirm_role": "Поставщик", **(extra or {})}, files)


def test_engine_review_of_odt_and_pdf_has_no_word_file(tmp_path, monkeypatch):
    monkeypatch.delenv("PRAVKI_LLM_URL", raising=False)
    case = generate_case(str(tmp_path / "c"), "supply", 3)
    status, docx = _post(tmp_path, case["paths"]["tracked"], case["paths"]["base"])
    assert status == 200 and docx["source_format"] == "docx" and base64.b64decode(docx["unified_docx"])[:2] == b"PK"

    odt = odt_from_doc(tmp_path / "t.odt", read_docx(case["paths"]["tracked"]))
    status, data = _post(tmp_path, odt, case["paths"]["base"])
    assert status == 200 and data["source_format"] == "odt" and data["unified_docx"] == ""
    assert base64.b64decode(data["report_xlsx"])[:2] == b"PK" and data["changes"] and data["document"]
    assert [c["clause"] for c in data["changes"] if c["kind"] != "comment"] == [c["clause"] for c in docx["changes"] if c["kind"] != "comment"]

    pdf = pdf_from_docx(tmp_path / "t.pdf", case["paths"]["clean"])
    status, data = _post(tmp_path, pdf, case["paths"]["base"])
    assert status == 200 and data["source_format"] == "pdf" and data["unified_docx"] == ""
    assert PDF_NOTE in data["warnings"] and data["changes"]

    status, data = _post(tmp_path, pdf, None)
    assert status == 400 and "нужна ваша отправленная версия" in data["message"]

    junk = tmp_path / "junk.docx"
    junk.write_bytes(b"hello world")
    status, data = _post(tmp_path, junk, case["paths"]["base"])
    assert status == 400 and "неизвестный формат" in data["message"]


def test_read_document_of_each_format_has_format_label(tmp_path):
    case = generate_case(str(tmp_path / "c"), "services", 1)
    assert read_document(case["paths"]["base"]).format == "docx"
    assert read_document(str(odt_from_doc(tmp_path / "a.odt", read_docx(case["paths"]["base"])))).format == "odt"
    assert read_document(str(pdf_from_docx(tmp_path / "a.pdf", case["paths"]["base"]))).format == "pdf"


def _doc(labels):
    """DocxDoc из (номер, напечатан ли в тексте, текст)."""
    from pravki.model import DocxDoc, Paragraph, Segment

    paras = [Paragraph(index=i, label=lab, label_in_text=typed, segments=[Segment("equal", text)]) for i, (lab, typed, text) in enumerate(labels)]
    return DocxDoc(path="", paragraphs=paras, comments={}, authors=[])


def test_numbers_are_typed_when_at_least_half_of_labeled_paragraphs_print_them():
    from pravki.compare import _types_labels

    typed = lambda n: (f"{n}", True, f"{n}. Текст пункта")
    auto = lambda n: (f"{n}", False, "Текст пункта")
    assert _types_labels(_doc([typed(1), typed(2), typed(3), auto(4), auto(5)]))  # 3 из 5
    assert _types_labels(_doc([typed(1), auto(2)]))  # ровно половина
    assert not _types_labels(_doc([typed(1), auto(2), auto(3)]))
    assert not _types_labels(_doc([("", False, "Без номера")]))  # пунктов с номерами нет


def test_automatic_numbers_are_left_alone_even_if_the_text_looks_like_a_number():
    from pravki.compare import paired_views

    auto = _doc([("1", False, "1 января поставка начинается")])  # номер «1» дал редактор; «1 января» — текст
    typed = _doc([("1.1", True, "1.1. Поставка начинается")])
    base_view, their_view = paired_views(auto, typed, frozenset())
    assert base_view[0][1] == "1 января поставка начинается" and their_view[0][1] == "Поставка начинается"
