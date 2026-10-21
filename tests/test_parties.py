"""C9 (наша сторона в договоре) и C10 (стороны и реквизиты в каждом раунде)."""
import json
import os
import re

import pytest

from pravki import journal
from pravki.cli import main
from pravki.parties import (
    PARTY_TOPIC, CompanyProfile, Party, PartiesError, RoleCheckError, SideConfig, canon_role, check_side,
    compare_parties, load_profile, parse_parties, parties_of,
)
from pravki.pipeline import review_files
from pravki.playbook import load_playbook
from pravki.docx_reader import read_docx
from pravki.report import render_html, write_json
from pravki.synth import generate_case, side_config
from tests.helpers import dele, ins, make_docx, p, r

ROOT = os.path.dirname(os.path.dirname(__file__))
PB = os.path.join(ROOT, "playbooks", "services_example.yaml")

ALFA = "Общество с ограниченной ответственностью «Альфа Софт»"
BETA = "Акционерное общество «Бета Групп»"
STD = (
    f"{ALFA}, ИНН 7701234567, ОГРН 1027700000001, именуемое в дальнейшем «Исполнитель», в лице генерального директора "
    f"Петрова Петра Петровича, действующего на основании Устава, с одной стороны, и {BETA}, ИНН 7702345678, "
    "именуемое в дальнейшем «Заказчик», в лице директора Сидорова Сергея Сергеевича, действующего на основании Устава, "
    "с другой стороны, заключили настоящий договор о нижеследующем:"
)
TAIL = p(r("1. Предмет договора")) + p(r("1.1. Исполнитель оказывает Заказчику услуги."))


def _doc(tmp_path, name, preamble_xml, tail=TAIL):
    return str(make_docx(tmp_path / name, p(r("ДОГОВОР № 1")) + preamble_xml + tail))


def _pre(text):
    return p(r(text))


US = CompanyProfile(names=["ООО «Альфа Софт»"], inns=["7701234567"])
EXEC = SideConfig(profile=US)


# ---------------------------------------------------------------- разбор преамбулы
def test_parse_standard_preamble():
    ps = parse_parties(STD)
    assert [x.role for x in ps] == ["Исполнитель", "Заказчик"]
    assert ps[0].inn == "7701234567" and ps[0].ogrn == "1027700000001"
    assert ps[1].inn == "7702345678" and ps[1].ogrn == ""
    assert "Альфа Софт" in ps[0].name and "Бета Групп" in ps[1].name


@pytest.mark.parametrize("text,roles", [
    ("ООО «Ромашка» (далее – Подрядчик) с одной стороны и ПАО «Лютик» (далее – Заказчик) с другой стороны заключили договор",
     ["Подрядчик", "Заказчик"]),
    ("Индивидуальный предприниматель Иванов Иван Иванович, ИНН 500100732259, именуемый в дальнейшем «Арендодатель», "
     "с одной стороны, и ООО «Гамма», именуемое в дальнейшем «Арендатор», с другой стороны", ["Арендодатель", "Арендатор"]),
    ("ООО «Альфа», именуемое в дальнейшем «Исполнитель», и ООО «Бета», именуемое в дальнейшем «Заказчик», заключили договор",
     ["Исполнитель", "Заказчик"]),
])
def test_parse_other_formulations(text, roles):
    assert [x.role for x in parse_parties(text)] == roles


def test_inn_is_not_taken_from_neighbouring_party():
    ps = parse_parties(STD)
    assert ps[1].inn == "7702345678" and ps[0].inn != ps[1].inn


def test_garbage_gives_no_parties():
    assert parse_parties("Настоящий договор регулирует отношения сторон.") == []
    assert parse_parties("") == []


def test_numbered_roles_are_not_a_side():
    ps = parse_parties("ООО «А», именуемое в дальнейшем «Сторона 1», и ООО «Б», именуемое «Сторона 2», заключили договор")
    assert len(ps) == 2
    res = check_side("Исполнитель", ps, SideConfig(profile=CompanyProfile(names=["ООО «А»"])))
    assert res.blocked and res.status == "mismatch"


def test_preamble_is_read_up_to_first_clause(tmp_path):
    f = _doc(tmp_path, "a.docx", _pre(STD),
             tail=p(r("1. Предмет договора")) + p(r("1.1. Исполнитель, именуемый в дальнейшем «Заказчик», обязуется")))
    ps = parties_of(read_docx(f), "accepted")
    assert [x.role for x in ps] == ["Исполнитель", "Заказчик"]


def test_role_equivalents():
    assert canon_role("Подрядчик") == canon_role("Исполнитель")
    assert canon_role("Поставщик") == canon_role("Продавец")
    assert canon_role("Заказчик") != canon_role("Исполнитель")
    assert canon_role("«Арендатор»") == "арендатор"


# ---------------------------------------------------------------- профиль компании
def test_profile_matching():
    ps = parse_parties(STD)
    assert US.match(ps[0]) == "inn"
    assert CompanyProfile(names=[ALFA]).match(ps[0]) == "name"
    assert CompanyProfile(names=["Альфа Софт"]).match(ps[0]) == "name_loose"
    assert US.match(ps[1]) == ""
    assert CompanyProfile(names=["ООО «Альфа»"]).match(ps[0]) == ""  # похожее, но другое наименование
    assert CompanyProfile(inns=["7702345678"]).match(ps[0]) == ""


def test_profile_file(tmp_path):
    f = tmp_path / "company.yaml"
    f.write_text("names:\n  - ООО «Альфа Софт»\ninn: [7701234567]\n", encoding="utf-8")
    prof = load_profile(str(f))
    assert prof.inns == ["7701234567"] and prof.names == ["ООО «Альфа Софт»"]
    f.write_text("foo: 1\n", encoding="utf-8")
    with pytest.raises(PartiesError):
        load_profile(str(f))
    with pytest.raises(PartiesError):
        load_profile(str(tmp_path / "нет.yaml"))


# ---------------------------------------------------------------- C9: проверка стороны
def test_side_ok():
    res = check_side("Исполнитель", parse_parties(STD), EXEC)
    assert res.status == "ok" and not res.blocked and res.confidence == "высокая"


def test_side_equivalent_role_name_is_ok():
    ps = parse_parties(STD.replace("«Исполнитель»", "«Подрядчик»"))
    assert check_side("Исполнитель", ps, EXEC).status == "ok"


def test_side_mismatch_blocks():
    """Мы — Заказчик по преамбуле, а выбран плейбук Исполнителя: так выводы меняются местами."""
    other = SideConfig(profile=CompanyProfile(inns=["7702345678"]))
    res = check_side("Исполнитель", parse_parties(STD), other)
    assert res.status == "mismatch" and res.blocked
    assert "Заказчик" in res.message and "--confirm-role" in res.message


def test_side_unknown_without_profile():
    res = check_side("Исполнитель", parse_parties(STD), SideConfig())
    assert res.status == "unknown" and res.blocked and "--our-inn" in res.message


def test_side_unknown_without_preamble():
    res = check_side("Исполнитель", [], EXEC)
    assert res.status == "unknown" and res.blocked


def test_side_unknown_when_company_not_in_contract():
    res = check_side("Исполнитель", parse_parties(STD), SideConfig(profile=CompanyProfile(inns=["1234567890"])))
    assert res.status == "unknown"


def test_side_unknown_when_both_parties_look_like_us():
    both = SideConfig(profile=CompanyProfile(inns=["7701234567", "7702345678"]))
    res = check_side("Исполнитель", parse_parties(STD), both)
    assert res.status == "unknown" and "нескольки" in res.message


def test_confirm_role_unblocks_and_is_marked():
    res = check_side("Исполнитель", parse_parties(STD), SideConfig(confirm_role="Исполнитель"))
    assert res.status == "confirmed" and not res.blocked
    res = check_side("Исполнитель", [], SideConfig(confirm_role="Исполнитель"))
    assert res.status == "confirmed"


def test_confirm_against_detection_is_override_not_silent():
    cfg = SideConfig(profile=CompanyProfile(inns=["7702345678"]), confirm_role="Исполнитель")
    res = check_side("Исполнитель", parse_parties(STD), cfg)
    assert res.status == "override" and not res.blocked and "вопреки" in res.message


def test_confirm_of_other_role_than_playbook_blocks():
    res = check_side("Исполнитель", parse_parties(STD), SideConfig(profile=US, confirm_role="Заказчик"))
    assert res.status == "mismatch" and res.blocked


def test_playbook_without_role_is_skipped():
    res = check_side("", parse_parties(STD), SideConfig())
    assert res.status == "skipped" and not res.blocked


# ---------------------------------------------------------------- C9 в конвейере и командной строке
@pytest.fixture()
def case(tmp_path):
    return generate_case(str(tmp_path / "case"), "services", 7)


def test_pipeline_runs_with_correct_profile(case):
    rv = review_files(case["paths"]["tracked"], case["paths"]["base"], PB, side=side_config(case))
    assert rv.side.status == "ok" and rv.changes
    assert not [c for c in rv.changes if c.topic == PARTY_TOPIC]


def test_pipeline_blocks_by_default(case):
    """Без профиля и подтверждения роли разбор с плейбуком не запускается."""
    with pytest.raises(RoleCheckError) as e:
        review_files(case["paths"]["tracked"], case["paths"]["base"], PB)
    assert e.value.result.status == "unknown"


def test_pipeline_blocks_on_wrong_side(case):
    wrong = SideConfig(profile=CompanyProfile(inns=["7702345678"]))  # ИНН Заказчика
    with pytest.raises(RoleCheckError) as e:
        review_files(case["paths"]["tracked"], case["paths"]["base"], PB, side=wrong)
    assert e.value.result.status == "mismatch"


def test_mirror_playbook_is_blocked_for_executor_contract(case, tmp_path):
    """Тот же договор, плейбук Заказчика, профиль Исполнителя: должно остановиться, а не выдать зеркальные выводы."""
    text = open(PB, encoding="utf-8").read()
    mirror = tmp_path / "mirror.yaml"
    mirror.write_text(re.sub(r"(?m)^our_role:.*$", "our_role: Заказчик", text), encoding="utf-8")
    with pytest.raises(RoleCheckError) as e:
        review_files(case["paths"]["tracked"], case["paths"]["base"], str(mirror), side=side_config(case))
    assert e.value.result.status == "mismatch"


def test_pipeline_without_playbook_is_not_blocked(case):
    rv = review_files(case["paths"]["tracked"], case["paths"]["base"])
    assert rv.side.status == "not_checked"


def test_confirm_role_runs_pipeline_on_documents_without_preamble(tmp_path):
    t = make_docx(tmp_path / "t.docx", p(r("1.1. Срок оплаты "), dele("10"), ins("30"), r(" дней.")))
    rv = review_files(str(t), None, PB, side=SideConfig(confirm_role="Исполнитель"))
    assert rv.side.status == "confirmed" and rv.changes


def test_cli_blocks_with_exit_3_and_no_report(case, tmp_path, capsys):
    out = tmp_path / "out"
    rc = main(["review", case["paths"]["tracked"], "--base", case["paths"]["base"], "--playbook", PB, "--out", str(out)])
    assert rc == 3 and not out.exists()
    err = capsys.readouterr().err
    assert "Сторона договора не подтверждена" in err and "Отчёт не создан" in err


def test_cli_blocks_on_wrong_side(case, tmp_path, capsys):
    out = tmp_path / "out"
    rc = main(["review", case["paths"]["tracked"], "--base", case["paths"]["base"], "--playbook", PB,
               "--our-inn", "7702345678", "--out", str(out)])
    assert rc == 3 and not out.exists()
    assert "Роль не совпала" in capsys.readouterr().err


def test_cli_confirm_role_of_other_side_blocks(case, tmp_path):
    rc = main(["review", case["paths"]["tracked"], "--base", case["paths"]["base"], "--playbook", PB,
               "--confirm-role", "Заказчик", "--out", str(tmp_path / "out")])
    assert rc == 3


def test_cli_company_file_and_report_shows_side(case, tmp_path, capsys):
    prof = tmp_path / "company.yaml"
    prof.write_text("names: [\"ООО «Альфа Софт»\"]\ninn: [7701234567]\n", encoding="utf-8")
    out = tmp_path / "out"
    rc = main(["review", case["paths"]["tracked"], "--base", case["paths"]["base"], "--playbook", PB,
               "--company", str(prof), "--out", str(out)])
    assert rc == 0
    data = json.loads((out / "changes.json").read_text(encoding="utf-8"))
    assert data["side"]["status"] == "ok" and data["side"]["expected_role"] == "Исполнитель"
    assert "Сторона договора" in (out / "report.html").read_text(encoding="utf-8")
    assert "Сторона договора" in capsys.readouterr().out


def test_cli_bad_company_file_is_readable_error(case, tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("foo: 1\n", encoding="utf-8")
    rc = main(["review", case["paths"]["tracked"], "--playbook", PB, "--company", str(bad)])
    assert rc == 2 and "профил" in capsys.readouterr().err


def test_project_remembers_role_and_blocks_switch(case, tmp_path, capsys):
    proj = str(tmp_path / "proj")
    args = ["review", case["paths"]["tracked"], "--base", case["paths"]["base"], "--our-inn", "7701234567", "--project", proj]
    assert main(args + ["--playbook", PB]) == 0
    assert journal.last_role(proj) == "Исполнитель"
    text = open(PB, encoding="utf-8").read()
    other = tmp_path / "other.yaml"
    other.write_text(re.sub(r"(?m)^our_role:.*$", "our_role: Заказчик", text), encoding="utf-8")
    capsys.readouterr()
    rc = main(["review", case["paths"]["tracked"], "--base", case["paths"]["base"], "--our-inn", "7702345678",
               "--project", proj, "--playbook", str(other)])
    assert rc == 3 and "предыдущими раундами" in capsys.readouterr().err
    assert len(journal.load(proj)["rounds"]) == 1


# ---------------------------------------------------------------- C10: стороны между раундами
def _round(tmp_path, ours_text, theirs_text, tracked_xml=None):
    base = _doc(tmp_path, "base.docx", _pre(ours_text))
    theirs = _doc(tmp_path, "theirs.docx", tracked_xml if tracked_xml is not None else _pre(theirs_text))
    return review_files(theirs, base, PB, side=EXEC)


def _party(rv):
    return [c for c in rv.changes if c.topic == PARTY_TOPIC]


def test_same_parties_give_no_party_changes(tmp_path):
    rv = _round(tmp_path, STD, STD)
    assert _party(rv) == [] and rv.side.status == "ok"


def test_representative_change_is_not_a_party_change(tmp_path):
    rv = _round(tmp_path, STD, STD.replace("Петрова Петра Петровича", "Николаева Николая Николаевича"))
    assert _party(rv) == []


def test_role_swap_is_flagged_and_first(tmp_path):
    swapped = STD.replace("«Исполнитель»", "«@»").replace("«Заказчик»", "«Исполнитель»").replace("«@»", "«Заказчик»")
    rv = _round(tmp_path, STD, swapped)
    ps = _party(rv)
    assert ps and rv.changes[0] is ps[0]
    assert "Изменились роли сторон" in ps[0].explanation
    assert ps[0].level == "review" and ps[0].lawyer_decision_needed and ps[0].materiality == "высокая"
    assert ps[0].rule_id == "PARTY" and not ps[0].out_of_playbook


def test_tracked_role_swap_is_flagged_even_if_playbook_ignores_it(tmp_path):
    base = _doc(tmp_path, "b.docx", _pre(f"{ALFA}, именуемое в дальнейшем «Исполнитель», с одной стороны, и {BETA}, "
                                         "именуемое в дальнейшем «Заказчик», с другой стороны"))
    theirs = _doc(tmp_path, "t.docx", p(
        r(f"{ALFA}, именуемое в дальнейшем «"), dele("Исполнитель", 5), ins("Заказчик", 6),
        r(f"», с одной стороны, и {BETA}, именуемое в дальнейшем «"), dele("Заказчик", 7), ins("Исполнитель", 8),
        r("», с другой стороны")))
    rv = review_files(theirs, base, PB, side=EXEC)
    assert _party(rv) and "Изменились роли сторон" in _party(rv)[0].explanation
    assert any(c.topic != PARTY_TOPIC for c in rv.changes)  # сами отмеченные правки тоже остаются в списке


def test_inn_change_is_flagged(tmp_path):
    rv = _round(tmp_path, STD, STD.replace("7702345678", "7799999999"))
    ps = _party(rv)
    assert len(ps) == 1 and "ИНН" in ps[0].explanation and "7799999999" in ps[0].after


def test_name_change_is_flagged(tmp_path):
    rv = _round(tmp_path, STD, STD.replace("Бета Групп", "Бета Холдинг"))
    ps = _party(rv)
    assert len(ps) == 1 and "наименование" in ps[0].explanation


def test_replaced_counterparty_is_flagged(tmp_path):
    rv = _round(tmp_path, STD, STD.replace(BETA, "Общество с ограниченной ответственностью «Омега»").replace("7702345678", "7705550000"))
    assert _party(rv)


def test_role_rename_same_side_is_low_noise_but_flagged(tmp_path):
    rv = _round(tmp_path, STD, STD.replace("«Исполнитель»", "«Подрядчик»"))
    ps = _party(rv)
    assert len(ps) == 1 and "название роли" in ps[0].explanation


def test_unparseable_preamble_in_their_version_is_flagged(tmp_path):
    base = _doc(tmp_path, "b.docx", _pre(STD))
    theirs = _doc(tmp_path, "t.docx", _pre("Стороны заключили настоящий договор."))
    rv = review_files(theirs, base, PB, side=EXEC)
    assert _party(rv) and "не удалось разобрать" in _party(rv)[0].explanation


def test_party_changes_without_base_use_tracked_changes(tmp_path):
    theirs = _doc(tmp_path, "t.docx", p(
        r(f"{ALFA}, ИНН 7701234567, именуемое в дальнейшем «Исполнитель», с одной стороны, и {BETA}, ИНН "),
        dele("7702345678", 9), ins("7799999999", 10), r(", именуемое в дальнейшем «Заказчик», с другой стороны")))
    rv = review_files(theirs, None, PB, side=EXEC)
    assert _party(rv) and "ИНН" in _party(rv)[0].explanation


def test_party_change_blocks_nothing_but_warns_and_reports_first(tmp_path):
    rv = _round(tmp_path, STD, STD.replace("7702345678", "7799999999"))
    assert any("стороны или реквизиты" in w for w in rv.warnings)
    html = render_html(rv)
    first = html.index("Сначала проверьте")
    for later in ("Сначала: возмещение", "Остальные правки", "Технические правки"):
        if later in html:
            assert first < html.index(later)
    write_json(rv, str(tmp_path / "c.json"))
    data = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert data["counts"]["стороны и реквизиты"] == 1 and data["changes"][0]["topic"] == PARTY_TOPIC


def test_party_changes_are_tracked_by_journal_as_repeats(tmp_path):
    proj = str(tmp_path / "proj")
    journal.init_project(proj, "т")
    changed = STD.replace("7702345678", "7799999999")
    journal.add_round(proj, _round(tmp_path, STD, changed))
    rv2 = _round(tmp_path, STD, changed)
    journal.add_round(proj, rv2)
    assert _party(rv2)[0].status == "repeated"


def test_compare_parties_unit():
    a = [Party("Исполнитель", "ООО «А»", "7701234567"), Party("Заказчик", "АО «Б»", "7702345678")]
    assert compare_parties(a, a) == []
    assert compare_parties([], []) == []
    assert compare_parties(a, a[:1])[0][0].startswith("Изменилось число сторон")
    assert compare_parties(a, [])[0][0].startswith("В версии контрагента")
    assert compare_parties([], a)[0][0].startswith("В нашей версии")
    swapped = [Party("Заказчик", "ООО «А»", "7701234567"), Party("Исполнитель", "АО «Б»", "7702345678")]
    assert any("роли" in w for w, _, _ in compare_parties(a, swapped))
