"""Согласие контрагента в комментарии (решение юриста от 2026-10-22: согласие в переписке = условие согласовано)."""
import pytest

from pravki.classify import AGREED, AGREED_IF, agreement, classify
from pravki.model import Change


@pytest.mark.parametrize("text", ["+", "ок", "Ок.", "ok", "Совершенно верно, либо через форму аккредитации", "не возражаем",
                                  "Согласны", "Принимается"])
def test_plain_agreement(text):
    assert agreement(text) == AGREED


@pytest.mark.parametrize("text", ["Ок. потребуется зафиксировать дату оплаты не позднее 8 апреля", "Ок с корректировкой", "Ок с  коррекимпрвкой", "В целом не возражаю, можем рассмотреть вашу редакцию",
                                  "не возражаю, при нашей формулировке 4.12", "Согласны, но срок 10 дней"])
def test_conditional_agreement(text):
    assert agreement(text) == AGREED_IF


@pytest.mark.parametrize("text", ["Настаиваем на сохранении данного пункта", "Инструктаж по ОТ проводится перед мероприятием",
                                  "Прошу исключить", "", "Окончательный срок — 5 дней"])
def test_not_agreement(text):
    assert agreement(text) == ""


def test_classify_marks_comment_and_lowers_materiality():
    c = classify(Change(kind="comment", before="Датой оплаты считается дата поступления средств на корреспондентский счёт", after="+"))
    assert AGREED in c.flags and c.materiality == "низкая" and any("согласовано" in n for n in c.notes)
    c2 = classify(Change(kind="comment", before="Оплата не позднее 12 апреля", after="Ок, но не позднее 8 апреля"))
    assert AGREED_IF in c2.flags and c2.materiality != "низкая"
    c3 = classify(Change(kind="insert", before="", after="ок"))
    assert AGREED not in c3.flags


def test_agreed_comment_needs_no_decision_conditional_does():
    from pravki.playbook import Playbook, analyze

    pb = Playbook(name="t")
    a = classify(Change(kind="comment", before="Датой оплаты считается дата поступления средств", after="+"))
    b = classify(Change(kind="comment", before="Оплата не позднее 12 апреля", after="Ок, но не позднее 8 апреля"))
    analyze([a, b], pb)
    assert a.level == "accept" and not a.lawyer_decision_needed and "Согласовано" in a.action
    assert b.level == "review" and b.lawyer_decision_needed
