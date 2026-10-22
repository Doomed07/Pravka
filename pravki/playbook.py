"""Плейбук: правила юриста и проверка правок по этим правилам.

Принципы:
  * решение по правке принимают правила плейбука, а не модель;
  * если правило не нашлось или автоматическая проверка не применима — режим «нужно решение юриста»;
  * «принять» ставится только когда число/условие проверено и укладывается в позицию плейбука.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from .model import Change
from .textdiff import normalize, numbers

LEVEL_ORDER = {"accept": 1, "fallback": 2, "review": 2.5, "reject": 3}

UNIT_PATTERNS = {
    "percent": r"(\d+(?:[.,]\d+)?)\s*(?:%|процент\w*)",
    "days": r"(\d+)\s*(?:\([^)]*\)\s*)?(?:(?:календарн|рабоч|банковск)\w*\s+)?(?:дн\w*|сутк\w*)",
    "months": r"(\d+)\s*(?:\([^)]*\)\s*)?месяц(?!н)\w*",
    "years": r"(\d+)\s*(?:\([^)]*\)\s*)?(?:лет|год\w*)",
    "monthly_payments": r"(\d+)\s*(?:\([^)]*\)\s*)?месячн\w*",
    "multiple": r"(\d+(?:[.,]\d+)?)\s*(?:-?\s*кратн\w*|раз\b)",
    "money": r"(\d[\d  ]*(?:[.,]\d+)?)\s*(?:\([^)]*\)\s*)?(?:руб\w*|₽|евро|usd|долл\w*)",
    "any": r"(\d+(?:[.,]\d+)?)",
}

UNIT_RU = {
    "percent": "%", "days": "дн.", "months": "мес.", "years": "лет", "monthly_payments": "мес. платежей",
    "multiple": "× стоимости", "money": "руб.", "any": "",
}


class PlaybookError(Exception):
    pass


@dataclass
class Rule:
    id: str
    title: str
    topic: str = ""
    match: list[str] = field(default_factory=list)
    preferred: str = ""
    fallback: str = ""
    red_line: str = ""
    checks: list[dict] = field(default_factory=list)
    escalate_to: str = ""
    norms: list[str] = field(default_factory=list)
    note: str = ""

    def __post_init__(self):
        self._match = [re.compile(p, re.IGNORECASE) for p in self.match]

    def hits(self, text: str) -> bool:
        return any(r.search(text) for r in self._match)


@dataclass
class Playbook:
    name: str
    contract_type: str = ""
    our_role: str = ""
    rules: list[Rule] = field(default_factory=list)
    priority_topics: list[str] = field(default_factory=list)
    path: str = ""


@dataclass
class Result:
    level: str = ""  # accept | fallback | reject | review
    applied: bool = False
    reasons: list[str] = field(default_factory=list)


def _num(s: str) -> float:
    return float(re.sub(r"[  ]", "", s).replace(",", "."))


def _fmt(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def load_playbook(path: str) -> Playbook:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise PlaybookError(f"не удалось прочитать плейбук {path}: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise PlaybookError("плейбук должен быть словарём с ключом rules (список правил)")
    rules, seen = [], set()
    for i, r in enumerate(data["rules"], 1):
        if not isinstance(r, dict) or "id" not in r or "title" not in r:
            raise PlaybookError(f"правило №{i}: обязательны поля id и title")
        if r["id"] in seen:
            raise PlaybookError(f"правило {r['id']}: повторяется id")
        seen.add(r["id"])
        for c in r.get("checks") or []:
            t = c.get("type")
            if t not in ("number", "change", "forbid", "require", "deletion_redline"):
                raise PlaybookError(f"правило {r['id']}: неизвестный тип проверки {t!r}")
            if t in ("number", "change") and c.get("unit", "any") not in UNIT_PATTERNS:
                raise PlaybookError(f"правило {r['id']}: неизвестная единица {c.get('unit')!r}")
            if t in ("forbid", "require") and not c.get("patterns"):
                raise PlaybookError(f"правило {r['id']}: для проверки {t} нужен список patterns")
        try:
            rules.append(
                Rule(
                    id=str(r["id"]), title=r["title"], topic=r.get("topic", ""), match=r.get("match") or [],
                    preferred=r.get("preferred", ""), fallback=r.get("fallback", ""), red_line=r.get("red_line", ""),
                    checks=r.get("checks") or [], escalate_to=r.get("escalate_to", ""), norms=r.get("norms") or [],
                    note=r.get("note", ""),
                )
            )
        except re.error as e:
            raise PlaybookError(f"правило {r['id']}: ошибка в регулярном выражении: {e}")
    return Playbook(
        name=data.get("name", path), contract_type=data.get("contract_type", ""), our_role=data.get("our_role", ""),
        rules=rules, priority_topics=data.get("priority_topics") or [], path=path,
    )


# --------------------------------------------------------------------------------------
# Проверки
# --------------------------------------------------------------------------------------
def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+(?=[А-ЯA-Z«\"(])", text)
    return [p for p in parts if p]


def _after_spans(text: str, after: str) -> list[tuple[int, int]]:
    """Где в тексте стоит вставленный фрагмент. Число не должно быть частью другого числа: «5%» не найдётся в «0,5%»."""
    pat = re.escape(after)
    if after[0].isdigit():
        pat = r"(?<!\d)(?<!\d[,.])" + pat
    if after[-1].isdigit():
        pat += r"(?!\d)(?![,.]\d)"
    return [(m.start(), m.end()) for m in re.finditer(pat, text)]


def _find_numbers(ch: Change, unit: str, check: dict) -> list[float]:
    """Числа с единицей из итогового текста, которых касается правка."""
    text = ch.context_after or ch.after
    if not text:
        return []
    sel = check.get("context")
    if sel:
        # ограничение по предложению: если ни одно предложение не подходит, правило к правке не относится
        sents = [s for s in _sentences(text) if re.search(sel, s, re.IGNORECASE)]
        if not sents:
            return []
        text_scope = " ".join(sents)
    else:
        text_scope = text
    spans: list[tuple[int, int]] = []
    if ch.after:
        spans = _after_spans(text_scope, ch.after)
        if not spans:  # изменённое место не в выбранных предложениях или оно часть другого числа («5%» внутри «0,5%»)
            return []
    rx = re.compile(UNIT_PATTERNS[unit], re.IGNORECASE)
    lead = re.compile(check["lead"], re.IGNORECASE) if check.get("lead") else None
    not_lead = re.compile(check["not_lead"], re.IGNORECASE) if check.get("not_lead") else None
    found = []
    for m in rx.finditer(text_scope):
        before = text_scope[max(0, m.start() - 30): m.start()]
        if lead and not lead.search(before):
            continue
        if not_lead and not_lead.search(before):
            continue
        touches = not spans or any(m.start() < e and m.end() > b for b, e in spans)
        if touches:
            try:
                found.append(_num(m.group(1)))
            except ValueError:
                pass
    return found


def _check_number(ch: Change, c: dict, res: Result):
    if "число" not in ch.flags and "процент" not in ch.flags:
        return
    unit = c.get("unit", "any")
    vals = _find_numbers(ch, unit, c)
    if not vals:
        return
    v = vals[0]
    pref, fb = c.get("preferred"), c.get("fallback")
    direction = c.get("direction", "max")
    u = UNIT_RU.get(unit, "")
    label = c.get("label", "значение")
    res.applied = True
    if direction == "eq":
        # значение фиксировано («всегда 10%»): любое отклонение в любую сторону — решение юриста
        if pref is not None and abs(v - pref) < 1e-9:
            res.reasons.append(f"{label}: {_fmt(v)} {u}".rstrip() + " — как в позиции плейбука")
            _upgrade(res, "accept")
        else:
            res.reasons.append(f"{label}: {_fmt(v)} {u}".rstrip() + f" — отличается от позиции плейбука ({_fmt(pref)} {u}".rstrip()
                               + "), отклонение согласует юрист")
            _upgrade(res, "review")
        return
    if direction == "max":
        ok_pref = pref is None or v <= pref
        ok_fb = fb is not None and v <= fb
    else:
        ok_pref = pref is None or v >= pref
        ok_fb = fb is not None and v >= fb
    sign = "не более" if direction == "max" else "не менее"
    if not ok_pref and fb is None:
        # граница уступки не задана: «хуже предпочтительного» — не уступка по умолчанию, а вопрос юристу
        res.reasons.append(f"{label}: {_fmt(v)} {u}".rstrip() + f" — хуже позиции плейбука ({sign} {_fmt(pref)} {u}".rstrip()
                           + "), граница уступки в плейбуке не задана — решает юрист")
        _upgrade(res, "review")
        return
    if ok_pref:
        res.reasons.append(f"{label}: {_fmt(v)} {u}".rstrip() + f" — в пределах предпочтительной позиции ({sign} {_fmt(pref)} {u}".rstrip() + ")")
        _upgrade(res, "accept")
    elif ok_fb:
        res.reasons.append(
            f"{label}: {_fmt(v)} {u}".rstrip() + f" — хуже предпочтительной ({sign} {_fmt(pref)} {u}".rstrip()
            + f"), но в пределах допустимой уступки ({sign} {_fmt(fb)} {u}".rstrip() + ")"
        )
        _upgrade(res, "fallback")
    else:
        lim = fb if fb is not None else pref
        res.reasons.append(
            f"{label}: {_fmt(v)} {u}".rstrip() + f" — за пределами допустимого ({sign} {_fmt(lim)} {u}".rstrip() + ")"
        )
        _upgrade(res, "reject")


def _check_change(ch: Change, c: dict, res: Result):
    """Относительное изменение числа (цена, арендная плата): допустимое отклонение в процентах.

    Применяется, только если изменённое число действительно имеет нужную единицу (деньги, проценты и т.д.):
    иначе срок в днях можно было бы принять за арендную плату.
    """
    unit = c.get("unit", "any")
    nb, na = numbers(ch.before), numbers(ch.after)
    if not nb or not na:
        return
    if unit != "any":
        if not _find_numbers(ch, unit, c):
            return
    try:
        old, new = float(nb[0]), float(na[0])
    except ValueError:
        return
    if old == 0:
        return
    pct = (new - old) / old * 100
    unfav = c.get("unfavorable", "down")
    bad = -pct if unfav == "down" else pct
    pref, fb = c.get("preferred_pct", 0), c.get("fallback_pct", 0)
    res.applied = True
    label = c.get("label", "значение")
    desc = f"{label}: {_fmt(old)} → {_fmt(new)} ({'+' if pct >= 0 else ''}{_fmt(round(pct, 1))}%)"
    if bad <= pref:
        res.reasons.append(desc + " — не в ущерб нам")
        _upgrade(res, "accept")
    elif bad <= fb:
        res.reasons.append(desc + f" — в ущерб нам, но в пределах допустимой уступки ({_fmt(fb)}%)")
        _upgrade(res, "fallback")
    else:
        res.reasons.append(desc + f" — в ущерб нам сильнее допустимого ({_fmt(fb)}%)")
        _upgrade(res, "reject")


def _check_forbid(ch: Change, c: dict, res: Result):
    if ch.kind in ("delete", "para_delete"):
        return
    scope = c.get("scope", "after")
    text = ch.after if scope == "after" else (ch.context_after or ch.after)
    for p in c["patterns"]:
        if re.search(p, text, re.IGNORECASE):
            res.applied = True
            res.reasons.append(c.get("message") or "Появилось условие, запрещённое плейбуком")
            _upgrade(res, "reject")
            return


def _check_require(ch: Change, c: dict, res: Result):
    ctx_before = ch.context or ch.before
    ctx_after = ch.context_after
    for p in c["patterns"]:
        rx = re.compile(p, re.IGNORECASE)
        if rx.search(ctx_before) and not rx.search(ctx_after):
            res.applied = True
            res.reasons.append(c.get("message") or "Удалено условие, которое плейбук требует сохранить")
            _upgrade(res, "reject")
            return


def _check_deletion(ch: Change, c: dict, res: Result):
    if ch.kind in ("delete", "para_delete"):
        res.applied = True
        res.reasons.append(c.get("message") or "Удаление условия, защищённого плейбуком")
        _upgrade(res, "reject")


def _upgrade(res: Result, level: str):
    if LEVEL_ORDER.get(level, 0) > LEVEL_ORDER.get(res.level, 0):
        res.level = level


CHECKS = {
    "number": _check_number,
    "change": _check_change,
    "forbid": _check_forbid,
    "require": _check_require,
    "deletion_redline": _check_deletion,
}


def evaluate(rule: Rule, ch: Change) -> Result:
    res = Result()
    for c in rule.checks:
        CHECKS[c["type"]](ch, c, res)
    return res


def _number_in_rule_context(rule: Rule, ch: Change) -> bool:
    """Правка меняет только число («1» → «5»), а тема определилась неточно: правило всё равно подходит, если изменённое
    число стоит в предложении, о котором его числовая проверка (`context`), и правило совпало с абзацем."""
    if not ("число" in ch.flags or "сумма" in ch.flags) or not ch.after or not rule.hits(f"{ch.context} {ch.context_after}"):
        return False
    text = ch.context_after or ""
    for c in rule.checks:
        sel = c.get("context") if c.get("type") in ("number", "change") else None
        if not sel:
            continue
        for sent in _sentences(text):
            if ch.after in sent and re.search(sel, sent, re.IGNORECASE):
                return True
    return False


def _candidates(pb: Playbook, ch: Change) -> list[tuple[int, Rule]]:
    changed = f"{ch.before} {ch.after}"
    ctx = f"{ch.context} {ch.context_after}"
    out = []
    for r in pb.rules:
        score = 0
        if r.hits(changed):
            score += 4
        if r.topic and r.topic == ch.topic:
            score += 3
        if r.hits(ctx):
            score += 1
        if score < 3 and _number_in_rule_context(r, ch):
            score += 3
        if score >= 3:
            out.append((score, r))
    out.sort(key=lambda x: -x[0])
    return out


ACTIONS = {
    "accept": "Принять",
    "fallback": "Принять как уступку",
    "reject": "Отклонить или предложить встречную редакцию",
    "review": "Нужно решение юриста",
}


def analyze(changes: list[Change], pb: Playbook) -> list[Change]:
    for ch in changes:
        _analyze_one(ch, pb)
    return changes


def _analyze_one(ch: Change, pb: Playbook) -> None:
    if ch.materiality == "техническая" and ch.kind != "comment":
        ch.level = "accept"
        ch.action = "Принять (техническая правка: опечатка, знаки, регистр, пробелы)"
        if ch.source != "tracked":
            ch.action = "Принять после беглой проверки (техническая правка, но не отмечена в рецензировании)"
        ch.explanation = "Смысл условия не меняется."
        return

    if ch.kind == "comment" and "согласие в комментарии" in ch.flags:
        # решение юриста 2026-10-22: согласие контрагента в переписке — условие согласовано
        ch.level = "accept"
        ch.action = "Согласовано в переписке: нашу правку можно принять"
        ch.explanation = "Контрагент согласился в комментарии без условий."
        return

    if ch.kind == "comment":
        ch.level = "review"
        ch.lawyer_decision_needed = True
        ch.action = "Нужно решение юриста: комментарий контрагента"
        ch.explanation = "Комментарий требует ответа; автоматической позиции нет."
        cands = _candidates(pb, Change(before=ch.before, after=ch.after, context=ch.context, topic=ch.topic))
        if cands:
            rule = cands[0][1]
            ch.rule_id, ch.rule_title = rule.id, rule.title
            ch.suggested = rule.preferred
        return

    cands = _candidates(pb, ch)
    chosen: tuple[Rule, Result] | None = None
    first_review: tuple[Rule, Result] | None = None
    for _, rule in cands:
        res = evaluate(rule, ch)
        if res.applied and res.level:
            chosen = (rule, res)
            break
        if first_review is None:
            first_review = (rule, res)

    if chosen is None and first_review is None:
        ch.out_of_playbook = True
        ch.level = "review"
        ch.lawyer_decision_needed = True
        ch.action = "Вне плейбука — нужно решение юриста"
        ch.explanation = "Подходящего правила в плейбуке нет."
        _notes_for_areas(ch)
        return

    rule, res = chosen if chosen else first_review  # type: ignore[misc]
    ch.rule_id, ch.rule_title = rule.id, rule.title
    ch.suggested = rule.preferred
    if chosen:
        level = res.level
        reason = "; ".join(res.reasons)
    else:
        level = "review"
        reason = "Автоматическая проверка по правилу не применима к этой правке."

    # страховки: сомнительное — всегда юристу
    if level == "accept":
        if "отрицание" in ch.flags:
            level = "review"
            reason += " Меняется отрицание — смысл мог измениться, проверьте вручную."
        elif ch.source != "tracked":
            level = "review"
            reason += " Правка не отмечена в рецензировании — не принимайте без проверки."

    ch.level = level
    ch.action = ACTIONS[level]
    if level == "review":
        ch.lawyer_decision_needed = True
        ch.action = "Нужно решение юриста"
    if level in ("reject", "review") and rule.escalate_to:
        ch.escalate_to = rule.escalate_to
    expl = [rule.title, reason]
    if level in ("reject", "fallback", "review") and rule.preferred:
        expl.append(f"Позиция по плейбуку: {rule.preferred}")
    if level == "reject" and rule.red_line:
        expl.append(f"Красная линия: {rule.red_line}")
    if level == "fallback" and rule.fallback:
        expl.append(f"Допустимая уступка: {rule.fallback}")
    if rule.note:
        expl.append(rule.note)
    ch.explanation = " ".join(_sentence(e) for e in expl if e)
    ch.detail["norms"] = list(rule.norms)
    _notes_for_areas(ch)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?)" else text + "."


def _notes_for_areas(ch: Change) -> None:
    extra = [a for a in ch.areas if a != "юридическая"]
    if extra and ch.materiality in ("высокая", "средняя"):
        ch.notes.append("Затрагивает области: " + ", ".join(extra) + " — подумайте, кого подключить")


PRIORITY_DEFAULT = [
    "возмещение убытков", "ограничение ответственности", "расторжение и отказ от договора",
]


def sort_key(ch: Change, pb: Playbook | None = None):
    """Порядок показа: сначала возмещение убытков, ограничение ответственности и расторжение (как в домашнем плейбуке)."""
    prio = (pb.priority_topics if pb and pb.priority_topics else PRIORITY_DEFAULT)
    rank = -1 if ch.rule_id == "PARTY" else (prio.index(ch.topic) if ch.topic in prio else len(prio))
    mat = {"высокая": 0, "средняя": 1, "низкая": 2, "техническая": 3}.get(ch.materiality, 2)
    return (rank, mat, ch.order)
