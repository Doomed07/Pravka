"""Зеркальный тест поставки: одна и та же правка под плейбуком Поставщика (SE) и Покупателя (SB).

Если система перепутала сторону, «принять» и «отклонить» меняются местами. Ожидания выведены из интересов сторон
(кому выгодна правка). Правило проекта: «принять» — только после проверки по правилу, иначе review.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from pravki.playbook import load_playbook
from pravki.synth import SUPPLY, SUPPLY_EDITS
from tests.test_mirror import mk, run

PB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playbooks")
SE = load_playbook(os.path.join(PB_DIR, "supply_example.yaml"))
SB = load_playbook(os.path.join(PB_DIR, "supply_customer_example.yaml"))
TEXT = {label: text for _, label, text in SUPPLY}


@dataclass(frozen=True)
class Edit:
    key: str
    clause: str
    before: str
    after: str
    se: str  # уровень под плейбуком Поставщика
    sb: str  # уровень под плейбуком Покупателя
    kind: str = "replace"

    def judge(self, pb):
        return run(pb, mk(self.before, self.after, TEXT[self.clause], kind=self.kind))


ASYMMETRIC = [
    # неустойка Поставщика за просрочку поставки: Поставщику — меньше, Покупателю — больше
    Edit("5.2-rate-up", "5.2", "0,1%", "0,5%", se="reject", sb="accept"),
    Edit("5.2-rate-down", "5.2", "0,1%", "0,02%", se="accept", sb="reject"),
    # неустойка Покупателя за просрочку оплаты
    Edit("5.1-rate-down", "5.1", "0,1%", "0,01%", se="reject", sb="accept"),
    Edit("5.1-rate-up", "5.1", "0,1%", "0,5%", se="accept", sb="reject"),
    # аванс: Поставщику — больше, Покупателю — меньше
    Edit("2.2-adv-down", "2.2", "30%", "10%", se="reject", sb="accept"),
    Edit("2.2-adv-up", "2.2", "30%", "50%", se="accept", sb="reject"),
    # окончательная оплата: Поставщику — быстрее, Покупателю — дольше
    Edit("2.3-pay-long", "2.3", "10 рабочих дней", "45 календарных дней", se="reject", sb="accept"),
    Edit("2.3-pay-short", "2.3", "10 рабочих дней", "5 рабочих дней", se="accept", sb="reject"),
    # срок поставки: Поставщику — дольше, Покупателю — короче
    Edit("3.1-ship-short", "3.1", "30 календарных дней", "10 календарных дней", se="reject", sb="accept"),
    Edit("3.1-ship-long", "3.1", "30 календарных дней", "60 календарных дней", se="accept", sb="reject"),
    # приёмка по качеству: Поставщику — короче, Покупателю — дольше
    Edit("3.3-qual-long", "3.3", "5 рабочих дней", "20 рабочих дней", se="reject", sb="accept"),
    Edit("3.3-qual-short", "3.3", "5 рабочих дней", "2 рабочих дней", se="accept", sb="reject"),
    # гарантия: Поставщику — короче, Покупателю — дольше
    Edit("4.1-warranty-long", "4.1", "12 месяцев", "24 месяцев", se="reject", sb="accept"),
    Edit("4.1-warranty-short", "4.1", "12 месяцев", "3 месяцев", se="accept", sb="reject"),
    # цена: Поставщику — рост, Покупателю — снижение
    Edit("2.1-price-down", "2.1", "2 400 000", "2 000 000", se="reject", sb="accept"),
    Edit("2.1-price-up", "2.1", "2 400 000", "2 600 000", se="accept", sb="reject"),
]


@pytest.mark.parametrize("e", [pytest.param(e, id=e.key) for e in ASYMMETRIC])
def test_supply_mirror_table(e: Edit):
    se, sb = e.judge(SE), e.judge(SB)
    assert (se.level, sb.level) == (e.se, e.sb), (
        f"{e.key}: ожидали SE={e.se}, SB={e.sb}; получили SE={se.level} ({se.rule_id}: {se.explanation}) "
        f"SB={sb.level} ({sb.rule_id}: {sb.explanation})")


@pytest.mark.parametrize("e", [pytest.param(e, id=e.key) for e in ASYMMETRIC])
def test_supply_mirrored_rules_judge_the_same_edit(e: Edit):
    """Одну правку за обе стороны проверяют зеркальные правила (SE-NN ↔ SB-NN)."""
    assert e.judge(SE).rule_id[2:] == e.judge(SB).rule_id[2:]


@pytest.mark.parametrize("spec", [pytest.param(s, id=s.key) for s in SUPPLY_EDITS
                                  if s.op == "replace" and s.important])
def test_supply_catalog_never_accepted_by_both_roles(spec):
    """Каждая существенная правка из учебного договора поставки не получает «принять» сразу за обе стороны."""
    levels = tuple(run(pb, mk(spec.old, spec.new, TEXT[spec.clause])).level for pb in (SE, SB))
    assert levels != ("accept", "accept"), spec.key


def test_table_is_two_sided():
    assert any(e.se == "reject" and e.sb == "accept" for e in ASYMMETRIC)
    assert any(e.se == "accept" and e.sb == "reject" for e in ASYMMETRIC)
