"""Стороны договора: определение нашей стороны (C9) и сверка сторон между версиями (C10).

Зачем. Одна и та же правка по-разному оценивается для сторон: рост неустойки за просрочку оплаты выгоден
Исполнителю и неприемлем для Заказчика. Если система приняла не ту сторону, выводы «принять» и «отклонить»
меняются местами, и юрист этого не замечает. Поэтому:

  C9   — находим в преамбуле стороны и их роли, определяем по профилю компании, кто из них мы, и сверяем с ролью
         плейбука. Не совпало или не удалось определить — анализ не запускается, пока юрист не подтвердит роль.
  C10  — в каждом раунде сверяем стороны версии контрагента с нашей версией: смена стороны, названия роли,
         наименования, реквизитов или обмен ролями выводится отдельной правкой высшего приоритета.

Ограничения (честно):
  * разбираются стороны, описанные в начале договора (до первого пункта) по образцу «…, именуемое в дальнейшем
    «Роль»», «…в дальнейшем Роль» (без кавычек) или «(далее – Роль)»; обозначения «Стороны» и «Договор» ролями не
    считаются; раздел с реквизитами в конце договора (чаще таблицей) не разбирается;
  * иностранные наименования распознаются по форме (Ltd, LLC, Inc, GmbH, AG, Corp и т. п.) и по слову «Фирма»,
    «Компания» с названием в кавычках; если наименование не разобрано в обеих версиях, оно изменением не считается;
  * ИНН и ОГРН учитываются, только если указаны в преамбуле;
  * «Сторона 1» и «Сторона 2» роль не определяют: такие договоры всегда идут на подтверждение юристу.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from .docx_reader import view_paragraphs
from .model import Change, DocxDoc
from .textdiff import normalize

PARTY_TOPIC = "стороны и реквизиты"
MAX_HEAD_PARAS = 40
MAX_HEAD_CHARS = 6000

# Роли → сторона. Исполнитель и Подрядчик, Продавец и Поставщик — одна сторона сделки; остальные роли своя сторона.
_SIDE = {
    "заказчик": "заказчик", "исполнитель": "исполнитель", "подрядчик": "исполнитель",
    "продавец": "продавец", "поставщик": "продавец", "покупатель": "покупатель",
    "арендодатель": "арендодатель", "арендатор": "арендатор", "субарендатор": "субарендатор",
    "лицензиар": "лицензиар", "лицензиат": "лицензиат",
    "раскрывающая сторона": "раскрывающая сторона", "получающая сторона": "получающая сторона",
    "заимодавец": "заимодавец", "займодавец": "заимодавец", "заёмщик": "заёмщик", "заемщик": "заёмщик",
    "кредитор": "кредитор", "должник": "должник", "принципал": "принципал", "агент": "агент",
    "комитент": "комитент", "комиссионер": "комиссионер", "доверитель": "доверитель", "поверенный": "поверенный",
    "ссудодатель": "ссудодатель", "ссудополучатель": "ссудополучатель", "хранитель": "хранитель",
    "поклажедатель": "поклажедатель", "перевозчик": "перевозчик", "грузоотправитель": "грузоотправитель",
    "грузополучатель": "грузополучатель", "наймодатель": "наймодатель", "наниматель": "наниматель",
}
# Обозначения, которые не роли: «…, именуемые в дальнейшем Стороны», «(далее – Договор)».
_COLLECTIVE = {"стороны", "договор", "соглашение", "контракт", "сторонами", "сторонам", "участники"}
_NUMBERED = re.compile(r"^(?:сторона|участник)\s*(?:№\s*)?\d*$")

_LEGAL = (r"(?:Общество\s+с\s+ограниченной\s+ответственностью|Публичное\s+акционерное\s+общество|"
          r"Непубличное\s+акционерное\s+общество|Акционерное\s+общество|Закрытое\s+акционерное\s+общество|"
          r"Открытое\s+акционерное\s+общество|Индивидуальный\s+предприниматель|Некоммерческая\s+организация|"
          r"ООО|ПАО|НАО|АО|ЗАО|ОАО|ИП|НКО|АНО|ФГУП|МУП|ГУП|ГБУ|ФГБУ|ФГБОУ|ГК)")
_NAME_QUOTED = re.compile(_LEGAL + r"[^«\"“,;]{0,40}?[«\"“][^»\"”]{1,80}[»\"”]")
_NAME_IP = re.compile(r"(?:Индивидуальный\s+предприниматель|ИП)\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё\.]+){1,2}")
_NAME_PERSON = re.compile(r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:ич|вна|чна|ична|оглы|кызы)\b")
# Иностранные наименования: «Huawei Technologies Co., Ltd.», «Siemens AG», «Acme Trading LLC».
_FOREIGN_SUFFIX = (r"(?:Co\.?,?\s*Ltd\.?|Ltd\.?|Limited|LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|GmbH|AG|S\.A\.?|SA|"
                   r"B\.V\.?|BV|PLC|LLP|SRL|S\.r\.l\.?|Pte\.?(?:\s*Ltd\.?)?|Pty(?:\s*Ltd\.?)?|OY|AB|NV|SAS|SARL|KG|Kft|FZE|FZCO|DMCC|OOO)")
_NAME_FOREIGN = re.compile(r"(?:[A-Z][\w&'\-]*\.?,?\s+){1,6}" + _FOREIGN_SUFFIX + r"(?![\w])")
_NAME_COMPANY_WORD = re.compile(r"(?:Компания|Фирма|Корпорация|Фонд|Ассоциация|Банк)\s+[«\"“][^»\"”]{1,80}[»\"”]")
_LEGAL_WORD = re.compile(r"\b" + _LEGAL + r"\b")

_BY_TEXT = r"(?:по\s+тексту\s*)?"
_DEF_QUOTED = re.compile(r"(?i:именуем\w+|далее)\s*(?i:в\s+дальнейшем\s*)?" + _BY_TEXT + r"(?:[-–—]\s*)?[«\"“]([^»\"”]{2,40})[»\"”]")
_DEF_PAREN = re.compile(r"\(\s*(?i:далее|в\s+дальнейшем)\s*" + _BY_TEXT + r"(?:[-–—]\s*)?([А-ЯЁ][а-яё]+(?:\s+[а-яё]+)?)\s*\)")
# Роль без кавычек: «…, именуемое в дальнейшем Продавец, в лице…». Название роли с заглавной буквы, дальше запятая и т. п.
_DEF_BARE = re.compile(
    r"(?i:именуем\w+\s+в\s+дальнейшем|именуем\w+|далее)\s*" + _BY_TEXT + r"(?:[-–—]\s*)?([А-ЯЁ][а-яё]+(?:\s+[а-яё]+)?)"
    r"(?=\s*(?:,|;|\.|\(|$|(?i:в\s+лице|действующ|на\s+основании|с\s+(?:одной|другой)|и\s+[А-ЯЁ])))")
_SIDE_SPLIT = re.compile(r"\bс\s+(?:одной|другой)\s+стороны\s*,?", re.IGNORECASE)
_INN = re.compile(r"ИНН\s*[:№]?\s*(\d{10}|\d{12})\b")
_OGRN = re.compile(r"ОГРН(?:ИП)?\s*[:№]?\s*(\d{13}|\d{15})\b")
_FIRST_CLAUSE = re.compile(r"^\s*(?:\d+[.)]?\s*)?предмет\s+договора", re.IGNORECASE)

_FORMS = [
    ("общество с ограниченной ответственностью", "ооо"), ("публичное акционерное общество", "пао"),
    ("непубличное акционерное общество", "нао"), ("закрытое акционерное общество", "зао"),
    ("открытое акционерное общество", "оао"), ("акционерное общество", "ао"),
    ("индивидуальный предприниматель", "ип"), ("некоммерческая организация", "нко"),
]
_FORM_TOKENS = {"ооо", "пао", "нао", "зао", "оао", "ао", "ип", "нко", "ано", "фгуп", "муп", "гуп", "гбу", "фгбу", "фгбоу", "гк",
                "ltd", "llc", "inc", "gmbh", "ag", "corp", "plc", "limited", "co", "sa", "bv"}


class PartiesError(Exception):
    pass


def canon_role(role: str) -> str:
    r = re.sub(r"[«»\"“”]", "", role or "").strip().casefold().replace("ё", "е")
    r = re.sub(r"\s+", " ", r)
    for key, val in _SIDE.items():
        if r == key.replace("ё", "е"):
            return val
    return r


def is_known_role(role: str) -> bool:
    r = re.sub(r"[«»\"“”]", "", role or "").strip().casefold().replace("ё", "е")
    return r in {k.replace("ё", "е") for k in _SIDE}


def is_numbered_role(role: str) -> bool:
    return bool(_NUMBERED.match(re.sub(r"[«»\"“”]", "", role or "").strip().casefold()))


def norm_name(name: str) -> str:
    """Наименование для сравнения: регистр, кавычки, организационно-правовая форма."""
    s = (name or "").casefold().replace("ё", "е")
    for full, short in _FORMS:
        s = s.replace(full, short)
    s = re.sub(r"[«»\"“”'.,;:()]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_form(s: str) -> str:
    return " ".join(t for t in s.split() if t not in _FORM_TOKENS)


@dataclass
class Party:
    role: str  # как написано в договоре, например «Исполнитель»
    name: str = ""
    inn: str = ""
    ogrn: str = ""

    @property
    def side(self) -> str:
        return canon_role(self.role)

    def label(self) -> str:
        bits = [self.role + (f" — {self.name}" if self.name else "")]
        if self.inn:
            bits.append(f"ИНН {self.inn}")
        if self.ogrn:
            bits.append(f"ОГРН {self.ogrn}")
        return ", ".join(bits)


@dataclass
class CompanyProfile:
    """Как называется наша компания в договорах."""

    names: list[str] = field(default_factory=list)
    inns: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not self.names and not self.inns

    def match(self, party: Party) -> str:
        """'' — не наша; 'inn' / 'name' / 'name_loose' — по какому признаку совпала."""
        if party.inn and party.inn in self.inns:
            return "inn"
        pn = norm_name(party.name)
        if not pn:
            return ""
        loose = ""
        for n in self.names:
            nn = norm_name(n)
            if not nn:
                continue
            if nn == pn:
                return "name"
            has_form = any(t in _FORM_TOKENS for t in nn.split())
            if not has_form and _strip_form(pn) == nn:
                loose = "name_loose"
        return loose


def load_profile(path: str) -> CompanyProfile:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise PartiesError(f"не удалось прочитать профиль компании {path}: {e}")
    if not isinstance(data, dict):
        raise PartiesError("профиль компании должен быть словарём с ключами names и inn")
    names = [str(x) for x in (data.get("names") or [])]
    inns = [re.sub(r"\D", "", str(x)) for x in (data.get("inn") or data.get("inns") or [])]
    if not names and not inns:
        raise PartiesError("в профиле компании нужен хотя бы один ключ: names (наименования) или inn")
    return CompanyProfile(names=names, inns=inns)


def profile_from_args(names: list[str] | None, inns: list[str] | None, path: str | None = None) -> CompanyProfile | None:
    prof = load_profile(path) if path else CompanyProfile()
    prof.names += [n for n in (names or []) if n.strip()]
    prof.inns += [re.sub(r"\D", "", i) for i in (inns or []) if re.sub(r"\D", "", i)]
    return None if prof.empty() else prof


# --------------------------------------------------------------------------------------
# Разбор преамбулы
# --------------------------------------------------------------------------------------
def head_text(doc: DocxDoc, mode: str, ours: set[str] | frozenset[str] = frozenset()) -> str:
    """Начало договора до первого пункта: название, преамбула со сторонами."""
    parts: list[str] = []
    for i, (para, text) in enumerate(view_paragraphs(doc, mode, ours)):
        if i >= MAX_HEAD_PARAS:
            break
        if para.label or _FIRST_CLAUSE.match(text or ""):
            break
        if text.strip():
            parts.append(normalize(text))
    return " ".join(parts)[:MAX_HEAD_CHARS]


def head_indices(doc: DocxDoc) -> set[int]:
    """Номера абзацев начала договора (название, город и дата, преамбула со сторонами) — до первого пункта."""
    out: set[int] = set()
    for i, para in enumerate(doc.paragraphs):
        if i >= MAX_HEAD_PARAS:
            break
        text = "".join(s.text for s in para.segments)
        if para.label or _FIRST_CLAUSE.match(text):
            break
        out.add(para.index)
    return out


def mark_head_changes(changes: list[Change], head: set[int]) -> None:
    """Правки в преамбуле — стороны и реквизиты: решает юрист, правила плейбука к ним не применяются."""
    for ch in changes:
        if ch.topic == PARTY_TOPIC or ch.kind == "comment" or ch.paragraph_index not in head:
            continue
        ch.topic, ch.areas, ch.materiality = PARTY_TOPIC, ["юридическая"], "высокая"
        ch.rule_id, ch.rule_title, ch.level = "PARTY", "Стороны и реквизиты", "review"
        ch.action = "Нужно решение юриста: правка в преамбуле (стороны и реквизиты)"
        ch.explanation = "Правка в начале договора: наименования, реквизиты, город или дата. Сверьте с данными сторон."
        ch.lawyer_decision_needed = True


def _find_name(block: str) -> str:
    for rx in (_NAME_QUOTED, _NAME_COMPANY_WORD, _NAME_IP, _NAME_FOREIGN, _NAME_PERSON):
        found = list(rx.finditer(block))
        if found:
            return normalize(found[-1].group(0))
    return ""


def parse_parties(text: str) -> list[Party]:
    """Стороны из текста преамбулы. Пустой список, если разобрать не удалось."""
    defs: list[tuple[int, int, str]] = []
    for m in _DEF_QUOTED.finditer(text):
        defs.append((m.start(), m.end(), m.group(1)))
    for rx in (_DEF_PAREN, _DEF_BARE):
        for m in rx.finditer(text):
            if not any(a <= m.start() < b or m.start() <= a < m.end() for a, b, _ in defs):
                defs.append((m.start(), m.end(), m.group(1)))
    defs.sort()
    parties: list[Party] = []
    lo = 0  # начало участка текста, относящегося к текущей стороне
    for i, (_start, end, role) in enumerate(defs):
        gap_end = defs[i + 1][0] if i + 1 < len(defs) else min(len(text), end + 400)
        m = _SIDE_SPLIT.search(text, end, gap_end)
        if m:
            hi, next_lo = m.start(), m.end()
        else:  # без «с одной стороны» берём короткий хвост до следующего наименования
            tail = text[end:min(gap_end, end + 120)]
            starts = [x.start() for x in (_LEGAL_WORD.search(tail), _NAME_FOREIGN.search(tail)) if x]
            hi = end + (min(starts) if starts else len(tail))
            next_lo = hi
        before_def = text[lo:end]
        span = text[lo:hi]
        lo = next_lo
        has_legal = bool(_LEGAL_WORD.search(before_def) or _NAME_PERSON.search(before_def)
                         or _NAME_FOREIGN.search(before_def) or _NAME_COMPANY_WORD.search(before_def))
        if re.sub(r"[«»\"“”]", "", role).strip().casefold().replace("ё", "е") in _COLLECTIVE:
            continue
        if not (is_known_role(role) or is_numbered_role(role) or has_legal):
            continue
        inn = _INN.search(span)
        ogrn = _OGRN.search(span)
        parties.append(Party(role=normalize(role), name=_find_name(before_def), inn=inn.group(1) if inn else "",
                             ogrn=ogrn.group(1) if ogrn else ""))
    return parties


def parties_of(doc: DocxDoc, mode: str, ours: set[str] | frozenset[str] = frozenset()) -> list[Party]:
    return parse_parties(head_text(doc, mode, ours))


# --------------------------------------------------------------------------------------
# C9: наша сторона
# --------------------------------------------------------------------------------------
@dataclass
class SideConfig:
    profile: CompanyProfile | None = None
    confirm_role: str = ""  # роль, которую подтвердил юрист: «Мы — Исполнитель»


@dataclass
class SideResult:
    status: str  # ok | confirmed | override | mismatch | unknown | skipped | not_checked
    expected_role: str = ""  # роль плейбука
    detected_role: str = ""  # роль нашей компании по преамбуле, как написано в договоре
    confidence: str = ""  # высокая | средняя
    evidence: str = ""
    message: str = ""
    parties: list[Party] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.status in ("mismatch", "unknown")

    def to_dict(self) -> dict:
        return {
            "status": self.status, "expected_role": self.expected_role, "detected_role": self.detected_role,
            "confidence": self.confidence, "evidence": self.evidence, "message": self.message,
            "parties": [p.label() for p in self.parties],
        }


class RoleCheckError(Exception):
    """Анализ не запущен: сторона договора не подтверждена."""

    def __init__(self, result: SideResult):
        super().__init__(result.message)
        self.result = result


def _parties_text(parties: list[Party]) -> str:
    return "; ".join(p.label() for p in parties) if parties else "стороны не найдены"


def detect_our_party(parties: list[Party], profile: CompanyProfile | None) -> tuple[Party | None, str, str]:
    """(наша сторона, уверенность, причина неудачи)."""
    if profile is None or profile.empty():
        return None, "", "не задан профиль компании (наименование или ИНН)"
    if len(parties) < 2:
        return None, "", "в начале договора не удалось разобрать стороны"
    hits = [(p, profile.match(p)) for p in parties]
    hits = [(p, how) for p, how in hits if how]
    if not hits:
        return None, "", "наша компания в преамбуле не найдена"
    if len(hits) > 1:
        return None, "", "наша компания в преамбуле указана с несколькими ролями"
    party, how = hits[0]
    return party, ("высокая" if how in ("inn", "name") else "средняя"), ""


def check_side(playbook_role: str, parties: list[Party], cfg: SideConfig) -> SideResult:
    if not playbook_role:
        return SideResult("skipped", message="В плейбуке не указана наша роль: сторона договора не проверялась.", parties=parties)
    expected = canon_role(playbook_role)
    ours, conf, why = detect_our_party(parties, cfg.profile)
    det_role = ours.role if ours else ""
    det_side = ours.side if ours else ""
    seen = _parties_text(parties)
    res = SideResult("", expected_role=playbook_role, detected_role=det_role, confidence=conf, parties=parties)
    if ours:
        res.evidence = f"в преамбуле: {ours.label()} (уверенность: {conf})"

    if cfg.confirm_role:
        if canon_role(cfg.confirm_role) != expected:
            res.status = "mismatch"
            res.message = (f"Вы подтвердили роль «{cfg.confirm_role}», а выбранный плейбук рассчитан на роль «{playbook_role}». "
                           "Выберите плейбук нужной роли.")
            return res
        if ours and det_side != expected:
            res.status = "override"
            res.message = (f"Роль «{playbook_role}» подтверждена юристом вопреки автоопределению: в преамбуле наша компания "
                           f"названа «{det_role}». Проверьте, что подтверждение верное.")
        else:
            res.status = "confirmed"
            res.message = f"Роль «{playbook_role}» подтверждена юристом."
        return res

    if ours is None:
        res.status = "unknown"
        res.message = (f"Не удалось определить нашу сторону: {why}. Найдено: {seen}. Анализ не запущен, потому что при неверной "
                       f"стороне выводы «принять» и «отклонить» меняются местами. Если мы — «{playbook_role}», подтвердите роль "
                       "явно (параметр --confirm-role) или задайте профиль компании (--company, --our-name, --our-inn).")
        return res
    if det_side != expected:
        res.status = "mismatch"
        res.message = (f"Роль не совпала: плейбук рассчитан на роль «{playbook_role}», а в преамбуле наша компания названа "
                       f"«{det_role}». Анализ не запущен. Выберите плейбук роли «{det_role}» или, если определение ошибочно, "
                       f"подтвердите роль явно (--confirm-role {playbook_role}).")
        return res
    res.status = "ok"
    res.message = f"Роль «{playbook_role}» подтверждена преамбулой договора (уверенность: {conf})."
    return res


# --------------------------------------------------------------------------------------
# C10: стороны в каждом раунде
# --------------------------------------------------------------------------------------
def _short(s: str, n: int = 400) -> str:
    s = normalize(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def compare_parties(ours: list[Party], theirs: list[Party]) -> list[tuple[str, str, str]]:
    """Расхождения сторон: список (что произошло, было, стало). Пусто — стороны совпадают."""
    out: list[tuple[str, str, str]] = []
    if not ours and not theirs:
        return out
    if ours and not theirs:
        return [("В версии контрагента не удалось разобрать стороны в начале договора: проверьте преамбулу вручную.",
                 _parties_text(ours), "стороны не найдены")]
    if theirs and not ours:
        return [("В нашей версии стороны разобрать не удалось, а в версии контрагента удалось: преамбула переписана, "
                 "проверьте её вручную.", "стороны не найдены", _parties_text(theirs))]
    if len(ours) != len(theirs):
        return [(f"Изменилось число сторон: было {len(ours)}, стало {len(theirs)}.", _parties_text(ours), _parties_text(theirs))]
    used: set[int] = set()
    matched: set[int] = set()
    for oi, o in enumerate(ours):
        on = norm_name(o.name)
        j = next((k for k, t in enumerate(theirs) if k not in used and on and norm_name(t.name) == on), None)
        if j is not None:  # та же организация: проверяем роль и реквизиты
            used.add(j)
            matched.add(oi)
            _same_party_checks(o, theirs[j], out)
    for oi, o in enumerate(ours):
        if oi in matched:
            continue
        j = next((k for k, t in enumerate(theirs) if k not in used and t.side == o.side), None)
        if j is None:
            out.append((f"Сторона «{o.role}» заменена: {o.label()} отсутствует в версии контрагента.", o.label(),
                        _parties_text(theirs)))
            continue
        used.add(j)
        t = theirs[j]
        if norm_name(o.name) == norm_name(t.name):
            # наименование не разобрано в обеих версиях (оба пусты): различить стороны по названию нельзя,
            # сверяем роль и реквизиты, а пустое наименование изменением не считаем
            _same_party_checks(o, t, out)
        else:  # та же роль, другая организация (или наименование пропало)
            out.append((f"Изменено наименование стороны «{o.role}»: {o.name or 'не указано'} → {t.name or 'не указано'}.",
                        o.label(), t.label()))
    return out


def _same_party_checks(o: Party, t: Party, out: list[tuple[str, str, str]]) -> None:
    """Одна и та же организация в двух версиях: роль, название роли, ИНН и ОГРН."""
    if o.side != t.side:
        out.append((f"Изменились роли сторон: «{o.name or o.role}» была «{o.role}», стала «{t.role}». "
                    "Это меняет смысл всех условий договора.", o.label(), t.label()))
    elif normalize(o.role).casefold() != normalize(t.role).casefold():
        out.append((f"Изменено название роли: «{o.role}» → «{t.role}».", o.label(), t.label()))
    for what, a, b in (("ИНН", o.inn, t.inn), ("ОГРН", o.ogrn, t.ogrn)):
        if a and b and a != b:
            out.append((f"Изменён {what} стороны «{t.role}»: {a} → {b}.", o.label(), t.label()))


def party_changes(base: DocxDoc | None, theirs: DocxDoc, ours_authors: set[str], start: int = 1) -> list[Change]:
    """Правки сторон высшего приоритета (C10). Сравнивает нашу версию с принятой версией контрагента."""
    if base is not None:
        our_view = head_text(base, "accepted", ours_authors)
    else:
        our_view = head_text(theirs, "rejected", ours_authors)
    their_view = head_text(theirs, "accepted", ours_authors)
    found = compare_parties(parse_parties(our_view), parse_parties(their_view))
    out: list[Change] = []
    for n, (what, before, after) in enumerate(found, start):
        ch = Change(
            id=f"S{n:03d}", source="diff", kind="replace", clause="Преамбула", heading="Стороны", order=-1.0 + n / 1000,
            before=before, after=after, context=_short(our_view), context_after=_short(their_view),
            topic=PARTY_TOPIC, areas=["юридическая"], materiality="высокая", rule_id="PARTY", rule_title="Стороны и реквизиты",
            level="review", action="Нужно решение юриста: изменились стороны или реквизиты", explanation=what,
            suggested="Проверьте преамбулу и реквизиты вручную до рассмотрения остальных правок.",
            lawyer_decision_needed=True, flags=["стороны"],
        )
        ch.notes.append("Сверка сторон между версиями (C10)")
        out.append(ch)
    return out
