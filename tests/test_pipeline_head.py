from pravki.pipeline import review_files
from pravki.parties import PARTY_TOPIC, SideConfig
from tests.helpers import ins, make_docx, p, r

PRE = "ООО «Альфа», именуемое в дальнейшем «Исполнитель», и ИП Иванов И.И., именуемый в дальнейшем «Заказчик», действующий на основании записи ОГРНИП № "


def _review(tmp_path, base_body, theirs_body, authors):
    b = str(make_docx(tmp_path / "b.docx", base_body))
    t = str(make_docx(tmp_path / "t.docx", theirs_body))
    return review_files(t, b, "playbooks/services_example.yaml", our_authors=authors,
                        side=SideConfig(confirm_role="Исполнитель"))


def test_requisites_edit_in_preamble_goes_to_lawyer(tmp_path):
    clause = p(r("1. Предмет договора")) + p(r("1.1. Исполнитель оказывает услуги."))
    rv = _review(tmp_path, p(r(PRE + "от 27.11.2019.")) + clause, p(r(PRE + "312345678901234 от 27.11.2019.")) + clause, ["Юрист"])
    edit = next(c for c in rv.changes if "312345678901234" in c.after)
    assert edit.topic == PARTY_TOPIC and edit.lawyer_decision_needed and edit.rule_id == "PARTY"
    assert not edit.suggested  # позиция плейбука к реквизитам не относится


def test_accepted_change_from_our_version_skips_playbook(tmp_path):
    clause = p(r("1. Предмет договора"))
    base = clause + p(r("2.1. Ответственность Исполнителя ограничена суммой "), ins("стоимости Услуг", author="Коллега"), r("."))
    theirs = clause + p(r("2.1. Ответственность Исполнителя ограничена суммой стоимости Услуг."))
    rv = _review(tmp_path, base, theirs, ["Юрист"])
    ch = next(c for c in rv.changes if c.detail.get("accepted_from_base"))
    assert ch.lawyer_decision_needed and ch.rule_id == "" and "Коллега" in ch.explanation


def test_document_without_preamble_has_no_head(tmp_path):
    from pravki.docx_reader import read_docx
    from pravki.parties import head_indices

    appendix = p(r("Приложение № 1")) + p(r("Индивидуальные опции:")) + p(r("Выступление с докладом;"))
    assert head_indices(read_docx(str(make_docx(tmp_path / "a.docx", appendix)))) == set()
    contract = p(r("ДОГОВОР № 7")) + p(r(PRE + "123.")) + p(r("Стороны заключили договор:")) + p(r("1. Предмет договора"))
    assert head_indices(read_docx(str(make_docx(tmp_path / "c.docx", contract)))) == {0, 1}
