"""Зеркальный тест: одна и та же правка под плейбуком Исполнителя (SV) и плейбуком Заказчика (SC).

Если система приняла не ту сторону, выводы «принять» и «отклонить» меняются местами. Ожидаемые уровни ниже
выведены из интересов сторон (кому выгодна правка) и правил проекта: «принять» — только после проверки
по правилу, иначе «нужно решение юриста» (review). У движка нет «положительных» текстовых проверок
(forbid/require/deletion_redline умеют только отклонять), поэтому выгодное нам удаление или вставка текста
ожидается как review, а не accept.

Известные дефекты (если появятся) помечаются xfail(strict=True) со ссылкой на DEFECTS: тест хранит правильное
ожидание и упадёт (XPASS), когда дефект исправят, — тогда пометку нужно снять.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

import pytest
import yaml

from pravki.classify import TOPICS, classify
from pravki.model import Change
from pravki.playbook import LEVEL_ORDER, analyze, load_playbook
from pravki.textdiff import flags_for_change

PB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playbooks")
SV_PATH = os.path.join(PB_DIR, "services_example.yaml")
SC_PATH = os.path.join(PB_DIR, "services_customer_example.yaml")
SV = load_playbook(SV_PATH)
SC = load_playbook(SC_PATH)
ROLES = {"SV": SV, "SC": SC}


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


# --------------------------------------------------------------------------------------
# Текст договора (как в шаблоне services из pravki/synth.py)
# --------------------------------------------------------------------------------------
P21 = "Стоимость Услуг составляет 1 200 000 (один миллион двести тысяч) рублей, в том числе НДС 20%."
P22 = "Заказчик оплачивает Услуги в течение 10 рабочих дней с даты подписания Акта оказанных услуг."
P31 = "Исполнитель приступает к оказанию Услуг в течение 5 рабочих дней с даты подписания договора."
P32 = ("По завершении оказания Услуг Исполнитель направляет Заказчику Акт оказанных услуг. "
       "Заказчик в течение 5 рабочих дней подписывает Акт либо направляет мотивированный отказ.")
P33 = "При отсутствии мотивированного отказа в указанный срок Услуги считаются принятыми."
P41 = ("За нарушение срока оплаты Заказчик уплачивает Исполнителю неустойку в размере 0,1% от неоплаченной суммы "
       "за каждый день просрочки, но не более 10% от суммы договора.")
P42 = ("За нарушение срока оказания Услуг Исполнитель уплачивает Заказчику неустойку в размере 0,1% от стоимости "
       "Услуг за каждый день просрочки, но не более 10% от суммы договора.")
CAP = "Совокупная ответственность Исполнителя по договору ограничена суммой, равной стоимости Услуг."
LP = "Исполнитель не возмещает Заказчику упущенную выгоду."
P43 = CAP + " " + LP
FULL = "Исполнитель возмещает Заказчику убытки в полном объёме, включая упущенную выгоду."
NO_LIAB = "Исполнитель не несёт ответственности за перерывы в работе программного обеспечения."
P51 = ("Стороны обязуются не разглашать конфиденциальную информацию в течение срока действия договора "
       "и 3 лет после его прекращения.")
ADMIN = "Исполнитель предоставляет Заказчику доступ к своей информационной системе с правами администратора."
P62 = "Каждая из сторон вправе отказаться от договора, уведомив другую сторону не менее чем за 30 календарных дней."
P71 = ("Споры разрешаются в Арбитражном суде города Москвы после соблюдения претензионного порядка. "
       "Срок ответа на претензию – 10 календарных дней.")
UNI_C = ("Заказчик вправе в одностороннем порядке изменять объём Услуг и сроки их оказания, "
         "уведомив Исполнителя за 3 рабочих дня.")
UNI_E = "Исполнитель вправе в одностороннем порядке изменять стоимость Услуг, уведомив Заказчика."

# --------------------------------------------------------------------------------------
# Известные дефекты: ключ -> описание. Тест хранит правильное ожидание, а дефект помечен xfail(strict=True):
# когда его исправят, прогон упадёт (XPASS) и пометку нужно снять. Сейчас дефектов нет: всё, что нашёл этот тест
# (две ошибки движка pravki/playbook.py и четыре ошибки правил SV-02, SV-03, SV-05, SV-11), исправлено,
# а соответствующие правки остались в таблице как регрессионные.
# --------------------------------------------------------------------------------------
DEFECTS: dict[str, str] = {}


def xfail(defect: str):
    return pytest.mark.xfail(strict=True, reason=f"{defect}: {DEFECTS[defect]}")


@dataclass(frozen=True)
class Edit:
    key: str
    before: str
    after: str
    ctx: str
    kind: str = "replace"
    sv: str = ""                 # ожидаемый уровень под плейбуком Исполнителя
    sc: str = ""                 # ожидаемый уровень под плейбуком Заказчика
    gains: str = ""              # кому выгодна правка по интересам: SV, SC или "" (неоднозначно)
    red: tuple[str, ...] = ()    # чью красную линию (поле red_line) пересекает правка
    defect: str = ""             # ключ DEFECTS
    breaks: tuple[str, ...] = ()  # какие проверки нарушает дефект: table, double, red

    def judge(self, role: str) -> Change:
        return run(ROLES[role], mk(self.before, self.after, self.ctx, kind=self.kind))


def params(items, prop):
    return [pytest.param(e, id=e.key, marks=[xfail(e.defect)] if prop in e.breaks else []) for e in items]


# --------------------------------------------------------------------------------------
# (а) Таблица асимметричных правок: (уровень под SV, уровень под SC)
# --------------------------------------------------------------------------------------
ASYMMETRIC = [
    # неустойка Исполнителя за просрочку оказания (п. 4.2): Исполнителю — меньше, Заказчику — больше
    Edit("4.2-rate-0.1-to-0.5", "0,1%", "0,5%", P42, sv="reject", sc="accept", gains="SC", red=("SV",)),
    Edit("4.2-rate-0.1-to-0.05", "0,1%", "0,05%", P42, sv="accept", sc="reject", gains="SV", red=("SC",)),
    Edit("4.2-rate-0.1-to-0.2-zopa", "0,1%", "0,2%", P42, sv="fallback", sc="fallback", gains="SC"),
    Edit("4.2-cap-10-to-50", "10%", "50%", P42, sv="reject", sc="accept", gains="SC", red=("SV",)),
    Edit("4.2-cap-10-to-5", "10%", "5%", P42, sv="accept", sc="reject", gains="SV", red=("SC",)),
    Edit("4.2-delete", P42, "", P42, kind="para_delete", sv="review", sc="reject", gains="SV", red=("SC",)),
    # наша (Заказчика) неустойка за просрочку оплаты (п. 4.1): Исполнителю — больше, Заказчику — меньше
    Edit("4.1-rate-0.1-to-0.01", "0,1%", "0,01%", P41, sv="reject", sc="accept", gains="SC", red=("SV",)),
    Edit("4.1-rate-0.1-to-0.3", "0,1%", "0,3%", P41, sv="accept", sc="reject", gains="SV", red=("SC",)),
    Edit("4.1-cap-10-to-50", "10%", "50%", P41, sv="accept", sc="reject", gains="SV", red=("SC",)),
    Edit("4.1-cap-10-to-5", "10%", "5%", P41, sv="reject", sc="accept", gains="SC"),
    Edit("4.1-delete", P41, "", P41, kind="para_delete", sv="reject", sc="review", gains="SC", red=("SV",)),
    # срок оплаты (п. 2.2): Исполнителю — короче, Заказчику — дольше
    Edit("2.2-pay-10-to-60", "10 рабочих дней", "60 календарных дней", P22, sv="reject", sc="accept", gains="SC",
         red=("SV",)),
    Edit("2.2-pay-10-to-7", "10 рабочих дней", "7 рабочих дней", P22, sv="accept", sc="reject", gains="SV",
         red=("SC",)),
    Edit("2.2-pay-10-to-30", "10 рабочих дней", "30 календарных дней", P22, sv="fallback", sc="accept", gains="SC"),
    Edit("2.2-pay-10-to-20-zopa", "10 рабочих дней", "20 рабочих дней", P22, sv="fallback", sc="fallback",
         gains="SC"),
    # цена (п. 2.1): Исполнителю — рост, Заказчику — снижение
    Edit("2.1-price-up-8pct", "1 200 000", "1 300 000", P21, sv="accept", sc="reject", gains="SV", red=("SC",)),
    Edit("2.1-price-down-17pct", "1 200 000", "1 000 000", P21, sv="reject", sc="accept", gains="SC", red=("SV",)),
    Edit("2.1-price-down-3pct", "1 200 000", "1 160 000", P21, sv="fallback", sc="accept", gains="SC"),
    Edit("2.1-price-up-3pct", "1 200 000", "1 240 000", P21, sv="accept", sc="fallback", gains="SV"),
    # предел ответственности Исполнителя (п. 4.3): Исполнителю — ниже, Заказчику — выше
    Edit("4.3-cap-1x-to-3x", "суммой, равной стоимости Услуг", "суммой, равной 3-кратной стоимости Услуг", P43,
         sv="reject", sc="accept", gains="SC", red=("SV",)),
    Edit("4.3-cap-1x-to-2x", "суммой, равной стоимости Услуг", "суммой, равной 2-кратной стоимости Услуг", P43,
         sv="fallback", sc="accept", gains="SC"),
    Edit("4.3-cap-1x-to-0.5x", "суммой, равной стоимости Услуг", "суммой, равной 0,5-кратной стоимости Услуг", P43,
         sv="accept", sc="reject", gains="SV", red=("SC",)),
    Edit("4.3-cap-delete", CAP, "", P43, kind="delete", sv="reject", sc="review", gains="SC", red=("SV",)),
    Edit("4.3-exclusion-insert", "", NO_LIAB, CAP, kind="insert", sv="review", sc="reject", gains="SV", red=("SC",)),
    # упущенная выгода: Исполнителю — исключить, Заказчику — возмещать
    Edit("4.3-lost-profit-excl-delete", " " + LP, "", P43, kind="delete", sv="reject", sc="review", gains="SC",
         red=("SV",)),
    Edit("4.3-lost-profit-negation-removed", "не возмещает", "возмещает", P43, sv="reject", sc="review", gains="SC",
         red=("SV",)),
    Edit("4.3-lost-profit-excl-insert", "", LP, CAP, kind="insert", sv="review", sc="reject", gains="SV",
         red=("SC",)),
    Edit("4.3-real-damage-only", "в полном объёме, включая упущенную выгоду", "в размере реального ущерба", FULL,
         sv="review", sc="reject", gains="SV", red=("SC",)),
    # приёмка (пп. 3.2, 3.3): Исполнителю — быстро и молчание = приёмка, Заказчику — дольше и без приёмки по умолчанию
    Edit("3.2-accept-5-to-15", "5 рабочих дней", "15 рабочих дней", P32, sv="reject", sc="accept", gains="SC"),
    Edit("3.2-accept-5-to-3", "5 рабочих дней", "3 рабочих дня", P32, sv="accept", sc="reject", gains="SV",
         red=("SC",)),
    Edit("3.2-accept-5-to-7-zopa", "5 рабочих дней", "7 рабочих дней", P32, sv="fallback", sc="fallback", gains="SC"),
    Edit("3.3-deemed-delete", P33, "", P33, kind="para_delete", sv="reject", sc="review", gains="SC", red=("SV",)),
    Edit("3.3-deemed-insert", "", P33, "", kind="para_insert", sv="review", sc="reject", gains="SV", red=("SC",)),
    # односторонние изменения: каждой стороне вредно чужое одностороннее право
    Edit("8.x-unilateral-customer", "", UNI_C, "", kind="para_insert", sv="reject", sc="review", gains="SC",
         red=("SV",)),
    Edit("8.x-unilateral-executor", "", UNI_E, "", kind="para_insert", sv="review", sc="reject", gains="SV",
         red=("SC",)),
    # отказ от договора (п. 6.2): у Заказчика правило «решает юрист» — срок взаимный, интерес неоднозначен
    Edit("6.2-notice-30-to-5", "30 календарных дней", "5 календарных дней", P62, sv="reject", sc="review",
         red=("SV",)),
    Edit("6.2-notice-30-to-45", "30 календарных дней", "45 календарных дней", P62, sv="accept", sc="review"),
    # ловушки движка
    Edit("4.2-cap-10-to-5-rate-0.5", "10%", "5%", P42.replace("0,1%", "0,5%"), sv="accept", sc="reject", gains="SV",
         red=("SC",)),
    Edit("3.1-start-5-to-3-not-payment", "5 рабочих дней", "3 рабочих дня", P31, sv="review", sc="review",
         gains="SC"),
]


@pytest.mark.parametrize("e", params(ASYMMETRIC, "table"))
def test_mirror_table(e: Edit):
    sv, sc = e.judge("SV"), e.judge("SC")
    assert (sv.level, sc.level) == (e.sv, e.sc), (
        f"{e.key}: ожидали SV={e.sv}, SC={e.sc}; получили SV={sv.level} ({sv.rule_id}: {sv.explanation}) "
        f"SC={sc.level} ({sc.rule_id}: {sc.explanation})")


@pytest.mark.parametrize("e", [pytest.param(e, id=e.key) for e in ASYMMETRIC
                               if not e.defect and "review" not in (e.sv, e.sc)])
def test_mirrored_rules_judge_the_same_edit(e: Edit):
    """Правку, которую обе роли проверяют автоматически, проверяют зеркальные правила (SV-NN ↔ SC-NN)."""
    sv, sc = e.judge("SV"), e.judge("SC")
    assert sv.rule_id[2:] == sc.rule_id[2:], (sv.rule_id, sc.rule_id)


def test_table_is_big_enough_and_two_sided():
    assert len(ASYMMETRIC) >= 12
    assert {e.gains for e in ASYMMETRIC} >= {"SV", "SC"}
    # в таблице есть правки, где одна роль отклоняет, а другая принимает, — в обе стороны
    assert any(e.sv == "reject" and e.sc == "accept" for e in ASYMMETRIC)
    assert any(e.sv == "accept" and e.sc == "reject" for e in ASYMMETRIC)


# --------------------------------------------------------------------------------------
# (б) Обратимость: правка A→B и обратная B→A под одной ролью дают противоположные направления
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Pair:
    key: str
    ctx_a: str       # текст со значением A
    a: str
    b: str
    gains: str       # кому выгоден переход A → B
    defect: str = ""
    breaks: tuple[str, ...] = ()  # dir-SV, dir-SC, double

    def forward(self) -> Change:
        return mk(self.a, self.b, self.ctx_a)

    def inverse(self) -> Change:
        return mk(self.b, self.a, self.ctx_a.replace(self.a, self.b, 1))


PAIRS = [
    Pair("4.2-rate", P42.replace("0,1%", "0,05%"), "0,05%", "0,5%", gains="SC"),
    Pair("4.2-cap", P42.replace("10%", "5%"), "5%", "50%", gains="SC"),
    Pair("4.1-rate", P41.replace("0,1%", "0,01%"), "0,01%", "0,3%", gains="SV"),
    Pair("4.1-cap", P41.replace("10%", "5%"), "5%", "50%", gains="SV"),
    Pair("2.2-pay", P22.replace("10 рабочих дней", "7 рабочих дней"), "7 рабочих дней", "60 календарных дней",
         gains="SC"),
    Pair("2.1-price", P21.replace("1 200 000", "1 000 000"), "1 000 000", "1 300 000", gains="SV"),
    Pair("4.3-cap", P43.replace("равной стоимости", "равной 0,5-кратной стоимости"), "0,5-кратной", "3-кратной",
         gains="SC"),
    Pair("3.2-accept", P32.replace("5 рабочих дней", "3 рабочих дня"), "3 рабочих дня", "15 рабочих дней",
         gains="SC"),
]


@pytest.mark.parametrize("p,role", [
    pytest.param(p, role, id=f"{p.key}-{role}", marks=[xfail(p.defect)] if f"dir-{role}" in p.breaks else [])
    for p in PAIRS for role in ("SV", "SC")
])
def test_inverse_edit_flips_direction(p: Pair, role: str):
    pb = ROLES[role]
    fwd, inv = run(pb, p.forward()), run(pb, p.inverse())
    # обе правки проверены автоматически и одним и тем же правилом
    assert fwd.level != "review" and inv.level != "review", (fwd.explanation, inv.explanation)
    assert fwd.rule_id == inv.rule_id
    # направление: выгодная роли правка оценена строго лучше обратной, невыгодная — строго хуже
    f, i = LEVEL_ORDER[fwd.level], LEVEL_ORDER[inv.level]
    if p.gains == role:
        assert f < i, f"{p.key} {role}: {p.a}→{p.b} выгодна, но {fwd.level} не лучше обратной {inv.level}"
    else:
        assert f > i, f"{p.key} {role}: {p.a}→{p.b} невыгодна, но {fwd.level} не хуже обратной {inv.level}"


@pytest.mark.parametrize("p", [pytest.param(p, id=p.key, marks=[xfail(p.defect)] if "double" in p.breaks else [])
                               for p in PAIRS])
def test_inverse_pair_never_accepted_by_both_roles(p: Pair):
    for make in (p.forward, p.inverse):
        levels = (run(SV, make()).level, run(SC, make()).level)
        assert levels != ("accept", "accept"), f"{p.key}: {make.__name__} принята обеими ролями"


@pytest.mark.parametrize("e", params(ASYMMETRIC, "double"))
def test_asymmetric_edit_never_accepted_by_both_roles(e: Edit):
    levels = (e.judge("SV").level, e.judge("SC").level)
    assert levels != ("accept", "accept"), f"{e.key}: асимметричная правка принята обеими ролями"


# Шкалы зеркальных числовых условий: правка базового значения на каждое значение шкалы.
# Красные линии взяты из текста red_line плейбуков (а не из проверок): None — у роли нет красной линии.
def _num(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def _pct(v: float) -> str:
    return _num(v) + "%"


def _money(v: int) -> str:
    return f"{v:,}".replace(",", " ")


@dataclass
class Scale:
    key: str
    ctx: str
    base: str
    points: tuple[tuple[str, float], ...]  # (новый текст, значение для красной линии)
    sv_red: Callable[[float], bool] | None
    sc_red: Callable[[float], bool] | None
    known: dict = field(default_factory=dict)  # значение -> (дефект, нарушаемые проверки)


SCALES = [
    # SV-01: больше 0,3% в день; SC-01: ниже 0,1% в день
    Scale("4.2-rate", P42, "0,1%", tuple((_pct(v), v) for v in (0.01, 0.03, 0.05, 0.08, 0.15, 0.2, 0.25, 0.4, 0.5, 0.7)),
          sv_red=lambda v: v > 0.3, sc_red=lambda v: v < 0.1),
    # SV-03: ниже 0,05% в день; SC-03: больше 0,1% в день
    Scale("4.1-rate", P41, "0,1%", tuple((_pct(v), v) for v in (0.01, 0.03, 0.05, 0.08, 0.15, 0.2, 0.3, 0.5)),
          sv_red=lambda v: v < 0.05, sc_red=lambda v: v > 0.1),
    # SV-02: выше 20%; SC-02: ниже 10%
    Scale("4.2-cap", P42, "10%", tuple((_pct(v), v) for v in (3, 5, 8, 15, 20, 25, 30, 50)),
          sv_red=lambda v: v > 20, sc_red=lambda v: v < 10),
    # предел неустойки Заказчика. SV-16: ниже 8%; SC-16: выше 20%
    Scale("4.1-cap", P41, "10%", tuple((_pct(v), v) for v in (5, 15, 50)),
          sv_red=lambda v: v < 8, sc_red=lambda v: v > 20),
    # SV-06: больше 30 дней; SC-06: меньше 10 дней
    Scale("2.2-pay", P22, "10 рабочих дней",
          (("3 рабочих дня", 3), ("5 рабочих дней", 5), ("7 рабочих дней", 7), ("15 календарных дней", 15),
           ("20 календарных дней", 20), ("30 календарных дней", 30), ("45 календарных дней", 45),
           ("60 календарных дней", 60), ("90 календарных дней", 90)),
          sv_red=lambda v: v > 30, sc_red=lambda v: v < 10),
    # SV-09: красная линия только про удаление приёмки по умолчанию; SC-09: меньше 5 рабочих дней
    Scale("3.2-accept", P32, "5 рабочих дней",
          (("2 рабочих дня", 2), ("3 рабочих дня", 3), ("4 рабочих дня", 4), ("7 рабочих дней", 7),
           ("10 рабочих дней", 10), ("15 рабочих дней", 15), ("20 рабочих дней", 20), ("30 рабочих дней", 30)),
          sv_red=None, sc_red=lambda v: v < 5),
    # SV-04: выше 2× стоимости; SC-04: ниже стоимости услуг
    Scale("4.3-cap", P43, "суммой, равной стоимости Услуг",
          tuple((f"суммой, равной {_num(v)}-кратной стоимости Услуг", v) for v in (0.5, 1.5, 2, 3, 5)),
          sv_red=lambda v: v > 2, sc_red=lambda v: v < 1),
    # значение — изменение цены в процентах. SV-07: снижение больше 5%; SC-07: рост больше 5%
    Scale("2.1-price", P21, "1 200 000",
          tuple((_money(v), (v - 1_200_000) / 1_200_000 * 100)
                for v in (1_000_000, 1_100_000, 1_150_000, 1_250_000, 1_300_000, 1_500_000)),
          sv_red=lambda d: d < -5, sc_red=lambda d: d > 5),
]


def _scale_params(prop: str, only_red: bool = False):
    out = []
    for s in SCALES:
        for text, v in s.points:
            red = tuple(r for r, f in (("SV", s.sv_red), ("SC", s.sc_red)) if f and f(v))
            if only_red and not red:
                continue
            defect, breaks = s.known.get(v, ("", ()))
            marks = [xfail(defect)] if prop in breaks else []
            out.append(pytest.param(s, text, red, id=f"{s.key}->{text}", marks=marks))
    return out


@pytest.mark.parametrize("s,text,red", _scale_params("double"))
def test_scale_never_accepted_by_both_roles(s: Scale, text: str, red: tuple):
    """Сдвиг числа от базового значения выгоден одной стороне и невыгоден другой: «принять» для обеих — ошибка."""
    levels = tuple(run(ROLES[r], mk(s.base, text, s.ctx)).level for r in ("SV", "SC"))
    assert levels != ("accept", "accept"), f"{s.key}: {s.base} → {text} принята обеими ролями"


# --------------------------------------------------------------------------------------
# (в) Красная линия по асимметричной правке не получает accept под обеими ролями,
#     а роль, чью красную линию правка пересекает, её отклоняет
# --------------------------------------------------------------------------------------
def _assert_red_line(levels: dict, red: tuple, what: str):
    assert (levels["SV"], levels["SC"]) != ("accept", "accept"), f"{what}: красная линия принята обеими ролями"
    for role in red:
        assert levels[role] == "reject", f"{what}: красная линия {role} получила {levels[role]}"


@pytest.mark.parametrize("e", params([e for e in ASYMMETRIC if e.red], "red"))
def test_red_line_edit_is_not_accepted_by_both(e: Edit):
    _assert_red_line({r: e.judge(r).level for r in ROLES}, e.red, e.key)


@pytest.mark.parametrize("s,text,red", _scale_params("red", only_red=True))
def test_red_line_on_scale_is_not_accepted_by_both(s: Scale, text: str, red: tuple):
    _assert_red_line({r: run(ROLES[r], mk(s.base, text, s.ctx)).level for r in ROLES}, red, f"{s.key} → {text}")


# --------------------------------------------------------------------------------------
# Симметричные правила: интересы совпадают — уровень одинаковый, правило зеркальное
# --------------------------------------------------------------------------------------
SYMMETRIC = [
    Edit("5.1-conf-3-to-10", "3 лет", "10 лет", P51, sv="reject", sc="reject"),
    Edit("5.1-conf-3-to-5", "3 лет", "5 лет", P51, sv="fallback", sc="fallback"),
    Edit("5.1-conf-3-to-2", "3 лет", "2 лет", P51, sv="accept", sc="accept"),
    Edit("7.1-claim-10-to-30", "10 календарных дней", "30 календарных дней", P71, sv="fallback", sc="fallback"),
    Edit("7.1-claim-10-to-45", "10 календарных дней", "45 календарных дней", P71, sv="reject", sc="reject"),
    Edit("7.1-court", "Арбитражном суде города Москвы", "Арбитражном суде города Казани", P71,
         sv="review", sc="review"),
    Edit("5.2-admin-access", "", ADMIN, "", kind="para_insert", sv="reject", sc="reject"),
    Edit("2.1-vat", "НДС 20%", "НДС не облагается", P21, sv="review", sc="review"),
]


@pytest.mark.parametrize("e", [pytest.param(e, id=e.key) for e in SYMMETRIC])
def test_symmetric_rules_give_same_level(e: Edit):
    sv, sc = e.judge("SV"), e.judge("SC")
    assert sv.level == sc.level == e.sv == e.sc, (sv.level, sc.level, e.sv)
    assert sv.rule_id[2:] == sc.rule_id[2:], (sv.rule_id, sc.rule_id)


# --------------------------------------------------------------------------------------
# (г) Плейбук Заказчика загружается без ошибок, у каждого правила есть id и title
# --------------------------------------------------------------------------------------
FIELDS = {"id", "title", "topic", "match", "preferred", "fallback", "red_line", "escalate_to", "norms", "checks", "note"}
LAWYER_ONLY = ["SC-08", "SC-10", "SC-14"]  # правила без проверок: «нужно решение юриста»


def test_customer_playbook_loads_and_rules_are_complete():
    pb = load_playbook(SC_PATH)  # PlaybookError при любой ошибке формата, типов проверок, единиц и regex
    assert pb.our_role == "Заказчик" and SV.our_role == "Исполнитель"
    assert pb.contract_type == SV.contract_type
    assert pb.priority_topics == SV.priority_topics
    ids = [r.id for r in pb.rules]
    assert ids == [f"SC-{i:02d}" for i in range(1, len(ids) + 1)]
    for r in pb.rules:
        assert r.id.strip() and r.title.strip(), r

    with open(SC_PATH, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("# ПРИМЕР плейбука для отладки. Это не юридическая позиция: замените значения своими.")
    for path in (SV_PATH, SC_PATH):
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        for r in raw["rules"]:
            assert isinstance(r.get("id"), str) and r["id"].strip(), r
            assert isinstance(r.get("title"), str) and r["title"].strip(), r
            assert set(r) <= FIELDS, f"{r['id']}: лишние поля {set(r) - FIELDS}"

    # те же темы, что у Исполнителя; SC-NN стоит на теме SV-NN; все темы известны классификатору
    assert {r.topic for r in pb.rules} == {r.topic for r in SV.rules}
    assert {r.topic for r in pb.rules} <= {t.name for t in TOPICS}
    by_id = {r.id: r for r in pb.rules}
    for sv_rule in SV.rules:
        assert by_id["SC" + sv_rule.id[2:]].topic == sv_rule.topic, sv_rule.id

    # правила без автоматической проверки — режим «решает юрист», и у каждого есть пояснение
    assert [r.id for r in pb.rules if not r.checks] == LAWYER_ONLY
    assert all(r.note for r in pb.rules if not r.checks)
