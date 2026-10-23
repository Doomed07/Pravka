"""Сравнение с разметкой юриста — на учебных файлах (данные владельца в тесты не попадают)."""
import json

from pravki.evaluate import clause_matches, compare_decision, lawyer_decision, print_golden, run_golden
from pravki.model import Change
from tests.helpers import dele, ins, make_docx, p, r

PRE = p(r("ООО «Альфа», именуемое в дальнейшем «Исполнитель», и ООО «Бета», именуемое в дальнейшем «Заказчик».")) + \
    p(r("1. Предмет договора"))


def _setup(tmp_path):
    anon = tmp_path / "anon"
    anon.mkdir()
    base = PRE + p(r("2.2. Оплата в течение 10 дней.")) + p(r("4.3. Неустойка 0,1% в день."))
    theirs = PRE + p(r("2.2. Оплата в течение "), dele("10"), ins("60"), r(" дней.")) + p(r("4.3. Неустойка 0,1% в день."))
    make_docx(anon / "b.docx", base)
    make_docx(anon / "t.docx", theirs)
    # договор, где правки внёс наш коллега
    make_docx(anon / "c.docx", PRE + p(r("3.1. Срок "), ins("5", author="Коллега"), r(" дней.")))
    rows = [
        {"n": 1, "base": "b.docx", "theirs": "t.docx", "clause": "2.2", "topic": "порядок и сроки оплаты",
         "decision": "Принять с изменениями / встречное предложение", "author_side": "контрагент"},
        {"n": 2, "base": "b.docx", "theirs": "t.docx", "clause": "4.3", "topic": "неустойка и штрафы",
         "decision": "", "author_side": "контрагент"},
        {"n": 4, "base": "b.docx", "theirs": "t.docx", "clause": "2.2", "topic": "налоги", "decision": "",
         "author_side": "контрагент"},  # правка найдена, но тема у юриста другая
        {"n": 3, "base": None, "theirs": "c.docx", "clause": "3.1", "topic": "", "decision": "", "author_side": "мы (коллега)"},
    ]
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    config = {"playbooks_dir": "playbooks", "pairs": {
        "t.docx": {"playbook": "services_example.yaml", "role": "Исполнитель"},
        "c.docx": {"playbook": "services_example.yaml", "role": "Исполнитель", "our_authors": ["Мы", "Коллега"]},
    }}
    return str(labels), str(anon), config


def test_golden_metrics_on_small_set(tmp_path):
    res = run_golden(*_setup(tmp_path))
    m = res["metrics"]
    assert m["строк с правками контрагента"] == 3
    assert m["правка найдена в этом пункте, %"] == 66.7  # в п. 4.3 правки нет
    assert m["тема совпала с юристом, %"] == 33.3  # строка 4: правка есть, тема другая
    assert m["строк с решением юриста"] == 1 and m["решение: совпало"] == 1  # 60 дней — красная линия, «отклонить»
    assert m["наши правки не выданы за чужие"] == "1 из 1"


def test_colleague_edit_counts_as_foreign_without_our_authors(tmp_path):
    labels, anon, config = _setup(tmp_path)
    config["pairs"]["c.docx"]["our_authors"] = ["Мы"]
    assert run_golden(labels, anon, config)["metrics"]["наши правки не выданы за чужие"] == "0 из 1"


def test_decision_categories():
    assert lawyer_decision("Принять с изменениями / встречное предложение") == "counter"
    assert lawyer_decision("Решение не нужно") == "none" and lawyer_decision("Принять") == "accept"
    assert compare_decision("counter", ["accept"]) == "опасно"
    assert compare_decision("counter", ["fallback", "reject"]) == "опасно"
    assert compare_decision("counter", ["reject"]) == "совпало"
    assert compare_decision("counter", ["review"]) == "осторожнее"
    assert compare_decision("none", ["accept"]) == "совпало"
    assert compare_decision("accept", ["reject"]) == "строже"
    assert compare_decision("accept", ["fallback"]) == "совпало"


def test_clause_forms():
    assert clause_matches("4.12 и 6.1", Change(clause="6.1"))
    assert clause_matches("10 (реквизиты)", Change(clause="10.3"))
    assert not clause_matches("10 (реквизиты)", Change(clause="1.10"))
    assert clause_matches("Приложение 1", Change(clause="1.2", heading="Приложение № 1 к договору"))
    assert not clause_matches("Приложение 1", Change(clause="1.2", heading="Предмет договора"))


def test_report_has_no_contract_text(tmp_path):
    out = print_golden(run_golden(*_setup(tmp_path)))
    assert "Оплата в течение" not in out and "60" not in out.replace("60.0", "")
