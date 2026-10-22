"""Классификатор правок: тема, области компетенции, существенность.

v0 — на правилах (ключевые слова). Модель подключается отдельным шагом (см. llm.py) и в v0 только
объясняет; решение по правке принимают правила плейбука.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .model import Change
from .textdiff import normalize, tokens

LEGAL = "юридическая"
FIN = "финансовая"
ACC = "бухгалтерская и налоговая"
COM = "коммерческая"
SEC = "ИБ"


@dataclass(frozen=True)
class Topic:
    name: str
    patterns: tuple[str, ...]
    areas: tuple[str, ...]
    base: str  # высокая | средняя | низкая


TOPICS: list[Topic] = [
    Topic("ограничение ответственности",
          (r"ограничен\w*\s+(?:\w+\s+){0,3}ответственност", r"совокупн\w+\s+ответственност", r"упущенн\w+\s+выгод",
           r"реальн\w+\s+ущерб", r"ограничен\w*\s+(?:сумм|стоимост)", r"ответственност\w+\s+(?:\w+\s+){0,6}ограничен", r"лимит\w*\s+ответственност", r"не\s+(?:несет|несёт|отвечает|возмещает)",
           r"не\s+превыша\w+\s+(?:стоимост|цен|сумм)"),
          (LEGAL, FIN), "высокая"),
    Topic("возмещение убытков",
          (r"возмещ\w+\s+(?:\w+\s+){0,2}убытк", r"полност\w+\s+возмещ", r"освобод\w+\s+от\s+ответственност",
           r"возмещени\w+\s+(?:потер|расход)"),
          (LEGAL, FIN), "высокая"),
    Topic("неустойка и штрафы",
          (r"неустойк", r"\bпен[иь]\b", r"штраф", r"просрочк", r"процент\w*\s+за\s+пользовани"),
          (LEGAL, FIN), "высокая"),
    Topic("расторжение и отказ от договора",
          (r"расторг|расторж", r"отказ\w*\s+от\s+(?:исполнени\w+\s+)?договор", r"отказаться\s+от", r"односторонн\w+\s+(?:порядк|отказ)",
           r"уведомив\w*\s+(?:другую\s+)?сторон", r"досрочн\w+\s+(?:прекращ|расторж)"),
          (LEGAL,), "высокая"),
    Topic("односторонние изменения условий",
          (r"в\s+одностороннем\s+порядке\s+(?:измен|пересмотр|корректир)", r"вправе\s+(?:\w+\s+){0,3}измен\w+\s+(?:услов|объ[её]м|цен|тариф)",
           r"измен\w+\s+(?:\w+\s+){0,2}по\s+своему\s+усмотрению"),
          (LEGAL, COM), "высокая"),
    Topic("цена и сумма договора",
          (r"стоимост", r"\bцен[аыеу]\b", r"общая\s+сумм", r"сумм\w+\s+договор", r"вознаграждени"),
          (COM, FIN), "высокая"),
    Topic("порядок и сроки оплаты",
          (r"оплат|оплач", r"платеж|платёж", r"аванс", r"предоплат", r"расч[её]т", r"рабоч\w+\s+дн\w+\s+с\s+(?:даты|момента)",
           r"отсрочк", r"обеспечительн"),
          (FIN, COM), "высокая"),
    Topic("налоги",
          (r"\bндс\b", r"налог", r"облага\w+", r"\bусн\b", r"вычет", r"счет-фактур|счёт-фактур", r"налогов"),
          (ACC, FIN), "высокая"),
    Topic("первичные документы и ЭДО",
          (r"\bакт(?:а|у|ом|е|ы|ов)?\b", r"\bупд\b", r"накладн", r"\bэдо\b", r"электронн\w+\s+документооборот", r"первичн\w+\s+документ"),
          (ACC,), "средняя"),
    Topic("сроки исполнения",
          (r"срок\w*\s+(?:оказани|выполнени|поставк|исполнени)", r"(?:оказыва|выполня|исполня|поставля)\w*\s+(?:\w+\s+){0,3}до\s+\d{1,2}\.\d{1,2}\.\d{2,4}", r"этап", r"график"),
          (COM,), "средняя"),
    Topic("приёмка и качество",
          (r"приемк|приёмк", r"считаю?т\w*\s+принят", r"подписыва\w+\s+акт", r"недостатк", r"качеств", r"гаранти", r"мотивированн\w+\s+отказ"),
          (COM, LEGAL), "высокая"),
    Topic("конфиденциальность",
          (r"конфиденциальн", r"разглаш", r"коммерческ\w+\s+тайн", r"\bnda\b"),
          (LEGAL, SEC), "высокая"),
    Topic("персональные данные и ИБ",
          (r"персональн\w+\s+данн", r"152-фз", r"информационн\w+\s+безопасн", r"защит\w+\s+информац", r"доступ\w*\s+к\s+(?:систем|данн|информац)",
           r"администратор", r"парол", r"шифрован", r"инцидент"),
          (SEC, LEGAL), "высокая"),
    Topic("срок действия договора",
          (r"срок\w*\s+(?:действия|аренды|договора)", r"вступает\s+в\s+силу", r"пролонг", r"действует\s+до", r"автоматическ\w+\s+продл"),
          (LEGAL,), "средняя"),
    Topic("разрешение споров",
          (r"арбитражн", r"подсудн", r"\bсуд[ае]?\b", r"претензи", r"применим\w+\s+прав", r"разрешени\w+\s+спор"),
          (LEGAL,), "средняя"),
    Topic("форс-мажор",
          (r"форс-?мажор", r"обстоятельств\w+\s+непреодолим"),
          (LEGAL,), "средняя"),
    Topic("интеллектуальная собственность",
          (r"исключительн\w+\s+прав", r"интеллектуальн", r"лицензи", r"\bпо\b\s+принадлеж"),
          (LEGAL, COM), "высокая"),
    Topic("субподряд, субаренда, передача прав",
          (r"субподряд", r"субаренд", r"уступк", r"перевод\w*\s+долг", r"привлеч\w+\s+(?:\w+\s+){0,2}третьих"),
          (LEGAL, COM), "средняя"),
    Topic("арендная плата и индексация",
          (r"арендн\w+\s+плат", r"индексац", r"коммунальн", r"эксплуатационн"),
          (FIN, COM), "высокая"),
    Topic("содержание и ремонт имущества",
          (r"текущ\w+\s+ремонт", r"капитальн\w+\s+ремонт", r"содержани\w+\s+(?:помещени|имуществ)", r"неотделимы\w+\s+улучшени"),
          (COM, LEGAL), "средняя"),
    Topic("предмет договора",
          (r"предмет\w*\s+договор", r"обязуется\s+(?:\w+\s+){0,6}(?:оказать|выполнить|передать|поставить|предоставить)",
           r"помещени", r"приложени\w+\s*(?:№|n)"),
          (COM, LEGAL), "средняя"),
    Topic("порядок обмена и изменения договора",
          (r"изменени\w+\s+(?:и\s+дополнени\w+\s+)?договор", r"дополнительн\w+\s+соглашени", r"уведомлени", r"юридическ\w+\s+значим"),
          (LEGAL,), "низкая"),
]

OTHER = "прочее"

_COMPILED = [(t, [re.compile(p, re.IGNORECASE) for p in t.patterns]) for t in TOPICS]
_LEVELS = ["техническая", "низкая", "средняя", "высокая"]


# Множители темы. «Управляющие» темы определяют, о чём пункт (расторжение, ответственность, конфиденциальность),
# а цена, сроки и НДС — его признаки. «Общие» темы нужны, только если ничего конкретнее не нашлось.
GOVERNING = 1.5
GENERIC = 0.7
WEIGHTS = {
    "ограничение ответственности": GOVERNING,
    "возмещение убытков": GOVERNING,
    "неустойка и штрафы": GOVERNING,
    "расторжение и отказ от договора": GOVERNING,
    "односторонние изменения условий": GOVERNING,
    "конфиденциальность": GOVERNING,
    "персональные данные и ИБ": GOVERNING,
    "разрешение споров": GOVERNING,
    "форс-мажор": GOVERNING,
    "субподряд, субаренда, передача прав": GOVERNING,
    "интеллектуальная собственность": GOVERNING,
    "первичные документы и ЭДО": 0.6,
    "предмет договора": GENERIC,
    "порядок обмена и изменения договора": 0.6,
    "срок действия договора": GENERIC,
}


def _focus(change: Change) -> str:
    """Предложения, в которых лежит правка (смысл правки определяет ближайшее предложение)."""
    out = []
    for text, frag in ((change.context_after, change.after), (change.context, change.before)):
        if text and frag:
            for s in re.split(r"(?<=[.;!?])\s+", text):
                if frag in s:
                    out.append(s)
    return " ".join(out)


# Организационно-правовая форма в наименовании («общество с ограниченной ответственностью») — не тема договора:
# иначе правка в преамбуле или реквизитах попадала в «ограничение ответственности».
_LEGAL_FORM = re.compile(r"\bс\s+ограниченн\w*\s+ответственност\w*", re.IGNORECASE)


def _no_form(text: str) -> str:
    return _LEGAL_FORM.sub(" ", text) if text else text


def topic_scores(change: Change) -> list[tuple[float, Topic]]:
    changed = _no_form(f"{change.before} {change.after}")
    ctx = _no_form(change.context or change.context_after)
    focus = _no_form(_focus(change))
    first_pos: dict[str, int] = {}
    parts_by_topic: dict[str, list[float]] = {}
    for topic, regs in _COMPILED:
        parts = []
        for r in regs:
            p = 0.0
            if r.search(changed):
                p += 5
            m = r.search(focus) if focus else None
            if m:
                p += 2
                first_pos[topic.name] = min(first_pos.get(topic.name, 10**9), m.start())
            if ctx and r.search(ctx):
                p += 1
            if p:
                parts.append(p)
        if parts:
            parts_by_topic[topic.name] = parts
    # в главной части предложения стоит то, о чём пункт; признаки (цена, срок, НДС) идут следом
    bonus: dict[str, float] = {}
    for rank, (name, _) in enumerate(sorted(first_pos.items(), key=lambda kv: kv[1])[:2]):
        bonus[name] = (2.5, 1.0)[rank]
    out = []
    for topic, _ in _COMPILED:
        parts = parts_by_topic.get(topic.name)
        if not parts:
            continue
        top = max(parts)
        score = (top + 0.25 * (sum(parts) - top) + bonus.get(topic.name, 0.0)) * WEIGHTS.get(topic.name, 1.0)
        out.append((score, topic))
    out.sort(key=lambda x: -x[0])
    return out


def _is_technical(change: Change) -> bool:
    """Исправление опечатки, пунктуации, регистра, пробелов — без смысловых флагов."""
    if change.kind in ("comment", "move"):
        return False
    b, a = normalize(change.before), normalize(change.after)
    if change.kind in ("insert", "delete", "replace") and not (b and a):
        # вставка/удаление: техническое, только если это знаки препинания
        only = b or a
        return bool(only) and not re.search(r"\w", only)
    if b.lower() == a.lower():
        return True
    if re.sub(r"[\W_]+", "", b.lower()) == re.sub(r"[\W_]+", "", a.lower()):
        return True
    if change.flags:
        return False
    tb, ta = [t for t in tokens(b) if t.strip()], [t for t in tokens(a) if t.strip()]
    if len(tb) != len(ta) or len(tb) > 3:
        return False
    for x, y in zip(tb, ta):
        if x == y:
            continue
        if any(ch.isdigit() for ch in x + y):
            return False
        if SequenceMatcher(None, x.lower(), y.lower()).ratio() < 0.8:
            return False
    return True


def _raise(level: str, steps: int = 1) -> str:
    return _LEVELS[min(len(_LEVELS) - 1, _LEVELS.index(level) + steps)]


_AGREE = re.compile(
    r"^\s*(?:в\s+целом\s+)?(?:\+|ок|ok|окей|да|согласн\w*|согласовано|принято|принимается|принимаем|не\s+возража\w*|совершенно\s+верно|верно|"
    r"хорошо|поддерживаем|устраивает|нам\s+ок)\b",
    re.IGNORECASE)
_CONDITION = re.compile(r"\b(?:но|при\s+условии|при\s+нашей|если|с\s+коррек\w*|в\s+целом|с\s+уточнени\w*|потребуется|только|кроме)\b",
                        re.IGNORECASE)
AGREED = "согласие в комментарии"
AGREED_IF = "согласие с условием"


def agreement(text: str) -> str:
    """Комментарий контрагента — согласие? «+», «ок», «не возражаю» → согласие; «ок, но…», «ок с корректировкой» →
    согласие с условием; остальное — не согласие. Согласие в переписке означает, что условие согласовано и правку
    можно принимать (решение юриста, 2026-10-22); условие юрист проверяет сам."""
    t = (text or "").strip()
    if not t:
        return ""
    if t in ("+", "++", "+1"):
        return AGREED
    if not _AGREE.search(t):
        return ""
    return AGREED_IF if _CONDITION.search(t) else AGREED


def classify(change: Change) -> Change:
    scores = topic_scores(change)
    if change.kind == "comment":
        text = f"{change.before} {change.after}"
        tmp = Change(before=text, after="", context=change.context)
        scores = topic_scores(tmp)
    if scores:
        topic = scores[0][1]
        change.topic = topic.name
        change.areas = list(topic.areas)
        base = topic.base
    else:
        change.topic = OTHER
        change.areas = [LEGAL]
        base = "низкая"
    # дополнительные области по признакам изменения
    if "сумма" in change.flags or "процент" in change.flags:
        for a in (FIN,):
            if a not in change.areas:
                change.areas.append(a)
    if _is_technical(change):
        change.materiality = "техническая"
        return change
    level = base
    sig = set(change.flags) & {"сумма", "процент", "срок", "отрицание", "дата", "число"}
    if sig and level in ("низкая", "средняя"):
        level = _raise(level)
    if change.kind in ("para_insert", "para_delete") and change.topic == OTHER:
        level = "средняя"
    if change.kind == "comment":
        level = "средняя" if base != "низкая" else "низкая"
        agreed = agreement(change.after)
        if agreed and agreed not in change.flags:
            change.flags.append(agreed)
            change.notes.append("Контрагент согласился в комментарии: условие согласовано, правку можно принимать."
                                if agreed == AGREED else
                                "Контрагент согласен с условием: проверьте условие, прежде чем принимать правку.")
            if agreed == AGREED:
                level = "низкая"
    change.materiality = level
    return change
