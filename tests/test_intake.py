"""Первая версия договора: контрагент, название и плейбук по преамбуле; положения проверяются по плейбуку."""
import json
import os

import pytest

from pravki import engine_api
from pravki.docx_reader import read_docx
from pravki.intake import clause_changes, contract_title, contract_type_hint, detect_intake, parties_by_model
from pravki.parties import CompanyProfile, Party
from pravki.pipeline import review_files
from pravki.playbook import load_playbook
from pravki.synth import generate_case, side_config
from tests.helpers import make_docx, p, r
from tests.test_parties import ALFA, BETA, STD

ROOT = os.path.dirname(os.path.dirname(__file__))


def _doc(tmp_path, *paragraphs, name="d.docx"):
    return read_docx(str(make_docx(tmp_path / name, "".join(p(r(t)) for t in paragraphs))))


class FakeClient:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def complete(self, system, user):
        self.calls += 1
        return self.answer


# ---------- название и тип ----------

def test_title_stops_before_city_date_and_preamble(tmp_path):
    doc = _doc(tmp_path, "ДОГОВОР ПОСТАВКИ № 15", "г. Москва «03» апреля 2026 г.", STD)
    assert contract_title(doc) == "Договор поставки № 15"


def test_title_can_span_two_lines_and_skips_text_before_it(tmp_path):
    doc = _doc(tmp_path, "УТВЕРЖДАЮ", "Договор № 7", "оказания услуг", "г. Тула", STD)
    assert contract_title(doc) == "Договор № 7 оказания услуг"


def test_title_is_empty_for_a_letter(tmp_path):
    assert contract_title(_doc(tmp_path, "Уважаемые коллеги, направляем вам проект.", STD)) == ""


@pytest.mark.parametrize("title,roles,want", [
    ("Договор поставки № 1", [], "supply"),
    ("Договор оказания услуг", [], "services"),
    ("Договор", ["Продавец", "Покупатель"], "supply"),
    ("Договор", ["Заказчик", "Исполнитель"], "services"),
    ("Договор", ["Арендатор", "Арендодатель"], ""),
])
def test_contract_type_hint(title, roles, want):
    assert contract_type_hint(title, [Party(role=x) for x in roles]) == want


# ---------- стороны ----------

def test_rules_find_counterparty_and_title(tmp_path):
    doc = _doc(tmp_path, "ДОГОВОР ОКАЗАНИЯ УСЛУГ № 1", STD)
    found = detect_intake(doc, CompanyProfile(inns=["7701234567"]))
    assert found["source"] == "rules" and found["ours"].role == "Исполнитель" and found["counterparty"].inn == "7702345678"
    assert found["title"] == "Договор оказания услуг № 1" and found["contract_type"] == "services"


HARD = (f"Между {ALFA} (ИНН 7701234567) и {BETA} (ИНН 7702345678) заключён настоящий договор о нижеследующем. "
        "Первая сторона — исполнитель, вторая — заказчик.")


def test_model_helps_when_the_preamble_has_no_known_pattern(tmp_path):
    doc = _doc(tmp_path, "Договор оказания услуг", HARD)
    answer = json.dumps({"стороны": [{"роль": "Исполнитель", "наименование": ALFA, "инн": "7701234567"},
                                     {"роль": "Заказчик", "наименование": BETA, "инн": "7702345678"}],
                         "название": "Договор оказания услуг"}, ensure_ascii=False)
    client = FakeClient(answer)
    found = detect_intake(doc, CompanyProfile(inns=["7701234567"]), client)
    assert client.calls == 1 and found["source"] == "model"
    assert found["counterparty"].name == BETA and found["counterparty"].inn == "7702345678"


def test_model_is_not_asked_when_rules_are_enough(tmp_path):
    client = FakeClient("{}")
    detect_intake(_doc(tmp_path, "Договор", STD), CompanyProfile(inns=["7701234567"]), client)
    assert client.calls == 0


def test_model_answer_is_accepted_only_if_it_is_in_the_text(tmp_path):
    head = f"Договор. {HARD}"
    invented = json.dumps({"стороны": [
        {"роль": "Исполнитель", "наименование": ALFA, "инн": "1111111111"},      # ИНН нет в тексте: пустой
        {"роль": "Заказчик", "наименование": "ООО «Вымышленная»", "инн": ""},   # названия нет в тексте: отброшена
        ], "название": "Договор мены"}, ensure_ascii=False)
    parties, title = parties_by_model(FakeClient(invented), head)
    assert [(x.name, x.inn) for x in parties] == [(ALFA, "")] and title == ""


def test_broken_model_answer_changes_nothing():
    for answer in ("не json", "[1, 2]", '{"стороны": "нет"}', ""):
        assert parties_by_model(FakeClient(answer), "текст") == ([], "")


def test_one_model_party_is_not_enough_to_name_a_counterparty(tmp_path):
    doc = _doc(tmp_path, "Договор", HARD)
    answer = json.dumps({"стороны": [{"роль": "Исполнитель", "наименование": ALFA, "инн": "7701234567"}]}, ensure_ascii=False)
    found = detect_intake(doc, CompanyProfile(inns=["7701234567"]), FakeClient(answer))
    assert found["source"] == "rules" and found["counterparty"] is None


# ---------- профиль компании и плейбук ----------

def test_company_profile_takes_inn_and_name_together():
    prof = engine_api.company_profile("123456789012, ИП Иванов И.И.")
    assert prof.inns == ["123456789012"] and prof.names == ["ИП Иванов И.И."]
    only_inn = engine_api.company_profile("ИНН 7701234567")
    assert only_inn.inns == ["7701234567"] and only_inn.names == []
    only_name = engine_api.company_profile("ООО «Альфа Софт»")
    assert only_name.inns == [] and only_name.names == ["ООО «Альфа Софт»"]
    assert engine_api.company_profile("") is None


def test_playbook_is_chosen_by_type_and_our_role(tmp_path):
    root = tmp_path / "playbooks"  # только учебные плейбуки: личные плейбуки владельца в тесте не участвуют
    root.mkdir()
    for name in ("services_example.yaml", "services_customer_example.yaml", "supply_example.yaml", "rent_example.yaml"):
        (root / name).write_bytes(open(os.path.join(ROOT, "playbooks", name), "rb").read())
    pick = lambda t, role: engine_api.suggest_playbook(t, role, str(root))  # noqa: E731
    assert pick("services", "Исполнитель") == "services_example.yaml"
    assert pick("services", "Подрядчик") == "services_example.yaml"
    assert pick("services", "Заказчик") == "services_customer_example.yaml"
    assert pick("supply", "Поставщик") == "supply_example.yaml"
    assert pick("supply", "Покупатель") == ""  # плейбука покупателя нет — не угадываем
    assert pick("", "Заказчик") == "" and pick("services", "") == "" and pick("rent", "Исполнитель") == ""


def _examples(tmp_path):
    root = tmp_path / "pb"
    root.mkdir()
    for name in ("services_example.yaml", "services_customer_example.yaml"):
        (root / name).write_bytes(open(os.path.join(ROOT, "playbooks", name), "rb").read())
    return root


def test_detect_endpoint_returns_everything_the_form_needs(tmp_path, monkeypatch):
    monkeypatch.delenv("PRAVKI_LLM_URL", raising=False)
    path = make_docx(tmp_path / "x.docx", p(r("ДОГОВОР ОКАЗАНИЯ УСЛУГ № 1")) + p(r(STD)))
    status, data = engine_api.detect_parties({"company": "7701234567"}, {"theirs": open(path, "rb").read()},
                                             playbooks_root=str(_examples(tmp_path)))
    assert status == 200
    assert data["ours"]["inn"] == "7701234567" and data["counterparty"]["inn"] == "7702345678"
    assert data["title"] == "Договор оказания услуг № 1" and data["playbook"] == "services_example.yaml"


# ---------- проверка положений по плейбуку ----------

@pytest.fixture(scope="module")
def case(tmp_path_factory):
    return generate_case(str(tmp_path_factory.mktemp("case")), "services", 5)


def test_clauses_skip_headings_and_short_lines(case):
    clauses = clause_changes(read_docx(case["paths"]["clean"]))
    assert clauses and all(c.source == "clause" and c.kind == "para_insert" and len(c.after) >= 25 for c in clauses)
    assert not any(c.after.isupper() for c in clauses)
    assert [c.id for c in clauses] == [f"E{n:03d}" for n in range(1, len(clauses) + 1)]


def test_first_version_is_checked_by_playbook_and_flags_only_fired_rules(case):
    pb = load_playbook(os.path.join(ROOT, "playbooks", "services_example.yaml"))
    rv = review_files(case["paths"]["clean"], None, pb, side=side_config(case), first_version=True)
    assert rv.mode == "first" and rv.changes
    assert all(c.source == "clause" and c.rule_id and c.level in ("reject", "fallback", "review") for c in rv.changes)
    assert [c.id for c in rv.changes] == [f"E{n:03d}" for n in range(1, len(rv.changes) + 1)]
    assert any("Первая версия договора" in w for w in rv.warnings)
    # единая версия — обычный текст без вставок и удалений; к абзацам привязаны только замечания
    kinds = {s["k"] for para in rv.document for s in para["segments"]}
    assert kinds == {"equal"}
    assert {i for para in rv.document for i in para["changes"]} == {c.id for c in rv.changes}


def _clause(text):
    from pravki.classify import classify
    from pravki.model import Change
    from pravki.textdiff import flags_for_change

    c = Change(source="clause", kind="para_insert", after=text, context_after=text, flags=flags_for_change("", text))
    return classify(c)


PENALTY_OK = ("4.2. За нарушение срока оказания Услуг Исполнитель уплачивает Заказчику неустойку в размере 0,1% от стоимости Услуг "
              "за каждый день просрочки, но не более 10% от суммы договора.")
PENALTY_BAD = PENALTY_OK.replace("0,1%", "1%")


def test_numeric_rules_check_every_number_of_a_clause():
    from pravki.playbook import analyze

    pb = load_playbook(os.path.join(ROOT, "playbooks", "services_example.yaml"))
    ok, bad = _clause(PENALTY_OK), _clause(PENALTY_BAD)
    analyze([ok, bad], pb)
    assert bad.level == "reject" and bad.detail["rule_applied"] and "1 %" in bad.explanation
    # «не более» в тексте положения — не отрицание-признак правки: приемлемое положение остаётся «принять», а не «решает юрист»
    assert ok.level == "accept"


def test_first_version_never_says_accept(case):
    pb = load_playbook(os.path.join(ROOT, "playbooks", "services_example.yaml"))
    rv = review_files(case["paths"]["clean"], None, pb, side=side_config(case), first_version=True)
    assert not any(c.level == "accept" for c in rv.changes)


def test_without_flag_a_clean_file_is_not_checked_clause_by_clause(case):
    pb = load_playbook(os.path.join(ROOT, "playbooks", "services_example.yaml"))
    rv = review_files(case["paths"]["clean"], None, pb, side=side_config(case))
    assert rv.mode != "first" and not any(c.source == "clause" for c in rv.changes)


def test_first_version_without_playbook_only_warns(case):
    rv = review_files(case["paths"]["clean"], None, None, first_version=True)
    assert rv.mode == "first" and rv.changes == [] and any("Плейбук не указан" in w for w in rv.warnings)


def test_first_version_with_tracked_changes_is_a_normal_review(case):
    pb = load_playbook(os.path.join(ROOT, "playbooks", "services_example.yaml"))
    rv = review_files(case["paths"]["tracked"], None, pb, side=side_config(case), first_version=True)
    assert rv.mode == "tracked" and not any(c.source == "clause" for c in rv.changes)
