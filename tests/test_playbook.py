import os

import pytest

from pravki.classify import classify
from pravki.model import Change
from pravki.playbook import PlaybookError, analyze, load_playbook
from pravki.textdiff import flags_for_change

PB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playbooks")
SV = load_playbook(os.path.join(PB_DIR, "services_example.yaml"))
RN = load_playbook(os.path.join(PB_DIR, "rent_example.yaml"))


def mk(before, after, ctx, source="tracked", kind="replace"):
    ctx_after = ctx.replace(before, after, 1) if before else ctx + " " + after
    ch = Change(source=source, kind=kind, before=before, after=after, context=ctx, context_after=ctx_after,
                clause="1.1")
    ch.flags = flags_for_change(before, after)
    return ch


def run(pb, ch):
    classify(ch)
    analyze([ch], pb)
    return ch


def test_penalty_rate_thresholds():
    ctx = "За нарушение срока оказания Услуг Исполнитель уплачивает Заказчику неустойку в размере 0,1% за каждый день, но не более 10% от суммы договора."
    assert run(SV, mk("0,1%", "0,05%", ctx)).level == "accept"
    assert run(SV, mk("0,1%", "0,3%", ctx)).level == "fallback"
    assert run(SV, mk("0,1%", "0,5%", ctx)).level == "reject"


def test_cap_and_rate_are_distinguished_in_same_sentence():
    ctx = "За нарушение срока оказания Услуг Исполнитель уплачивает Заказчику неустойку в размере 0,1% за каждый день, но не более 10% от суммы договора."
    ch = run(SV, mk("10%", "50%", ctx))
    assert ch.rule_id == "SV-02" and ch.level == "reject"


def test_removal_of_liability_cap_is_redline():
    ctx = "Совокупная ответственность Исполнителя по договору ограничена суммой, равной стоимости Услуг. Исполнитель не возмещает упущенную выгоду."
    ch = run(SV, mk("Совокупная ответственность Исполнителя по договору ограничена суммой, равной стоимости Услуг.", "", ctx, kind="delete"))
    assert ch.level == "reject" and ch.escalate_to


def test_unit_guard_days_are_not_rent_money():
    # регрессия: срок в днях не должен проверяться как арендная плата и «приниматься»
    ctx = "Арендодатель вправе расторгнуть договор в одностороннем порядке при просрочке внесения арендной платы более чем на 10 календарных дней."
    ch = run(RN, mk("10", "3", ctx))
    assert ch.level != "accept"
    assert ch.level == "reject"


def test_unit_guard_at_rule_level():
    # правило про арендную плату (деньги) не должно применяться к числу дней, даже если его выбрали по ошибке
    from pravki.playbook import evaluate
    rule = next(r for r in RN.rules if r.id == "RN-01")
    ctx = "Арендодатель вправе расторгнуть договор при просрочке более чем на 10 календарных дней."
    ch = mk("10", "3", ctx)
    res = evaluate(rule, ch)
    assert not res.applied and res.level == ""


def test_price_drop_beyond_tolerance():
    ctx = "Стоимость Услуг составляет 1 200 000 (один миллион двести тысяч) рублей, в том числе НДС 20%."
    assert run(SV, mk("1 200 000", "1 000 000", ctx)).level == "reject"
    assert run(SV, mk("1 200 000", "1 160 000", ctx)).level == "fallback"
    assert run(SV, mk("1 200 000", "1 300 000", ctx)).level == "accept"


def test_negation_downgrades_accept_to_review():
    ctx = "Заказчик оплачивает Услуги в течение 10 рабочих дней с даты подписания Акта."
    ch = mk("в течение 10 рабочих дней", "не позднее 7 рабочих дней", ctx)
    ch.flags.append("отрицание")
    ch = run(SV, ch)
    assert ch.level == "review"


def test_silent_accept_is_downgraded():
    ctx = "Заказчик оплачивает Услуги в течение 10 рабочих дней с даты подписания Акта."
    ch = run(SV, mk("10", "7", ctx, source="silent"))
    assert ch.level == "review" and "не отмечена" in ch.explanation


def test_out_of_playbook_is_marked():
    ch = run(SV, mk("город Москва", "город Тверь", "Стороны находятся в городе Москва."))
    assert ch.out_of_playbook and ch.lawyer_decision_needed and ch.level == "review"


def test_technical_edit_accepted_but_not_silently():
    ch = run(SV, mk("разработке", "разработки", "услуги по разработке программного обеспечения"))
    assert ch.materiality == "техническая" and ch.level == "accept"
    s = run(SV, mk("разработке", "разработки", "услуги по разработке программного обеспечения", source="silent"))
    assert "не отмечена" in s.action


def test_comment_always_needs_lawyer():
    ch = Change(kind="comment", source="tracked", before="фраза", after="Просим убрать", context="фраза")
    ch = run(SV, ch)
    assert ch.level == "review" and ch.lawyer_decision_needed


def test_forbid_admin_access_redline():
    ch = run(SV, mk("", "Исполнитель предоставляет Заказчику доступ к системе с правами администратора.",
                    "", kind="para_insert"))
    assert ch.level == "reject" and ch.escalate_to == "Руководитель информационной безопасности"


def test_sublease_ban_is_redline():
    ctx = "Арендатор вправе сдавать Помещение в субаренду с уведомлением Арендодателя."
    ch = run(RN, mk("вправе сдавать", "не вправе сдавать", ctx))
    assert ch.level == "reject"


def test_bad_playbook_errors(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("rules:\n  - id: X\n    title: t\n    checks: [{type: magic}]\n", encoding="utf-8")
    with pytest.raises(PlaybookError):
        load_playbook(str(f))
    f.write_text("rules:\n  - id: X\n    title: t\n    match: ['(']\n", encoding="utf-8")
    with pytest.raises(PlaybookError):
        load_playbook(str(f))
    f.write_text("не словарь", encoding="utf-8")
    with pytest.raises(PlaybookError):
        load_playbook(str(f))


def test_number_without_fallback_goes_to_lawyer_not_concession(tmp_path):
    """Нет границы уступки — значит, уступка не задана: правка хуже позиции уходит юристу, а не «принять как уступку»."""
    from pravki.pipeline import review_files
    from tests.helpers import dele, ins, make_docx, p, r

    pb = tmp_path / "pb.yaml"
    pb.write_text(
        "name: t\nrules:\n  - id: T-1\n    title: Срок оплаты\n    topic: порядок и сроки оплаты\n"
        "    match: ['оплат']\n    checks:\n      - {type: number, unit: days, direction: max, preferred: 5, context: 'оплат'}\n",
        encoding="utf-8")
    doc = make_docx(tmp_path / "t.docx", p(r("4.2. Оплата производится в течение "), dele("5 (пяти)"), ins("30 (тридцати)"),
                                           r(" рабочих дней с момента подписания Акта.")))
    ch = [c for c in review_files(str(doc), None, str(pb)).changes if c.rule_id == "T-1"][0]
    assert ch.level == "review" and ch.lawyer_decision_needed
    assert "граница уступки" in ch.explanation


def test_number_edit_matched_by_rule_context_when_topic_is_off(tmp_path):
    """Правка меняет только число, классификатор ошибся темой («уведомление» → обмен документами): правило о сроке приёмки
    всё равно применяется, потому что число стоит в предложении о приёмке."""
    from pravki.pipeline import review_files
    from tests.helpers import dele, ins, make_docx, p, r

    pb = tmp_path / "pb.yaml"
    pb.write_text(
        "name: t\nrules:\n  - id: T-2\n    title: Срок приёмки\n    topic: приёмка и качество\n"
        "    match: ['приня\\w+\\s+выполненн\\w+\\s+Работ']\n"
        "    checks:\n      - {type: number, unit: days, direction: max, preferred: 1, fallback: 3, context: 'приня'}\n",
        encoding="utf-8")
    doc = make_docx(tmp_path / "t.docx", p(r("4.1.6. Заказчик обязан в течение "), dele("1 (одного)"), ins("5 (пяти)"),
                                           r(" календарного дня с момента получения уведомления осмотреть и принять выполненные Работы.")))
    ch = [c for c in review_files(str(doc), None, str(pb)).changes if c.kind == "replace"][0]
    assert ch.rule_id == "T-2" and ch.level == "reject"
