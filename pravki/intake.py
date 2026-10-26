"""Первая версия договора: контрагент, название и плейбук по преамбуле; положения договора для проверки по плейбуку.

Две задачи на первом шаге работы с договором, когда правок в нём ещё нет:

  1. «Приём» (detect_intake): найти стороны и контрагента (сторона, не совпавшая с нашей компанией), название договора
     из заголовка и подходящий плейбук. Стороны ищет `parties.py` по образцам преамбулы; если образца нет, помогает
     модель — но её ответ принимается, только если названия и ИНН дословно есть в тексте начала договора.
  2. «Положения» (clause_changes): каждое положение договора выглядит как «предложено контрагентом» и проверяется
     правилами плейбука. Замечание появляется только там, где правило сработало; решение принимает плейбук, модель
     лишь поясняет (см. llm.Explainer.apply).
"""
from __future__ import annotations

import json
import re

from .docx_reader import view_paragraphs
from .model import Change, DocxDoc, Paragraph
from .parties import CompanyProfile, Party, canon_role, detect_our_party, head_indices, parse_parties
from .textdiff import flags_for_change, normalize

MAX_CLAUSES = 400  # положений на проверку: длиннее договоры проверяются по первым
MIN_CLAUSE_CHARS = 25  # короче — заголовок или обрывок, правил к нему нет
MAX_MODEL_CLAUSES = 30  # пояснений от модели на одну первую версию

_CONTRACT_WORD = re.compile(r"\b(?:договор|соглашение|контракт)\b", re.IGNORECASE)
_PREAMBLE_HINT = re.compile(r"именуем|в\s+дальнейшем|\bв\s+лице\b|^\s*г\.\s|^\s*город\s", re.IGNORECASE)

EXTRACT_SYSTEM = (
    "Ты помощник юриста. Из начала договора выпиши стороны. Ответ — только JSON без пояснений: "
    '{"стороны": [{"роль": "...", "наименование": "...", "инн": "..."}], "название": "..."}. '
    "Роль — как в договоре (Поставщик, Заказчик, Исполнитель…). Наименование и ИНН — дословно из текста; "
    "нет ИНН — пустая строка. Название — заголовок договора («Договор поставки № 5»). Ничего не придумывай."
)


def contract_title(doc: DocxDoc) -> str:
    """Название договора из заголовка: от первой строки со словом «договор» до города, даты или преамбулы."""
    lines: list[str] = []
    for _, text in view_paragraphs(doc, "rejected")[:8]:
        text = " ".join(text.split())
        if not text:
            continue
        if _PREAMBLE_HINT.search(text) or len(text) > 140 or text.endswith((".", ":", ";")) or re.match(r"\d+[.)]\s", text):
            break
        if not lines and not _CONTRACT_WORD.search(text):
            continue
        lines.append(text)
        if len(lines) == 3:
            break
    title = " ".join(lines).strip()
    if title.isupper():
        title = title[:1] + title[1:].lower()  # «ДОГОВОР ПОСТАВКИ» → «Договор поставки»
    return title


def contract_type_hint(title: str, parties: list[Party]) -> str:
    """Тип договора для выбора плейбука: supply, services или пусто (не уверены)."""
    low = title.casefold()
    if "поставк" in low:
        return "supply"
    if re.search(r"услуг|оказани", low):
        return "services"
    roles = {canon_role(p.role) for p in parties}
    if roles & {"продавец", "покупатель"}:
        return "supply"
    if roles & {"исполнитель", "заказчик"}:
        return "services"
    return ""


def _head_text(doc: DocxDoc) -> str:
    from .parties import head_text

    return head_text(doc, "rejected")


def _json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parties_by_model(client, head: str) -> tuple[list[Party], str]:
    """Стороны и название по тексту начала договора, найденные моделью. Принимается только то, что есть в тексте:
    наименование и ИНН — дословно (без учёта пробелов и регистра). Остальное отбрасывается."""
    try:
        data = _json_object(client.complete(EXTRACT_SYSTEM, head[:4000]))
    except Exception:  # noqa: BLE001 — сбой модели не должен ронять приём договора
        return [], ""
    flat = re.sub(r"\s+", "", normalize(head)).casefold()  # normalize приводит кавычки и тире к одному виду

    def present(value: str) -> bool:
        v = re.sub(r"\s+", "", normalize(str(value or ""))).casefold()
        return bool(v) and v in flat

    parties = []
    for item in data.get("стороны") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("наименование") or "").strip()
        inn = re.sub(r"\D", "", str(item.get("инн") or ""))
        if not present(name):
            continue
        parties.append(Party(role=str(item.get("роль") or "").strip(), name=name, inn=inn if present(inn) else ""))
    title = str(data.get("название") or "").strip()
    return parties, title if present(title) else ""


def detect_intake(doc: DocxDoc, profile: CompanyProfile | None, client=None) -> dict:
    """Стороны, контрагент, наша сторона, название и тип договора. Модель (client) — только если разбор по образцам
    не нашёл двух сторон. Контрагент определён, только если наша сторона найдена среди сторон."""
    head = _head_text(doc)
    parties = parse_parties(head)
    title = contract_title(doc)
    source = "rules"
    if len(parties) < 2 and client is not None:
        found, model_title = parties_by_model(client, head)
        if len(found) >= 2:
            parties, source = found, "model"
        title = title or model_title
    ours, _, _ = detect_our_party(parties, profile)
    other = [p for p in parties if p is not ours]
    counterparty = other[0] if ours is not None and len(other) == 1 else None
    return {"parties": parties, "ours": ours, "counterparty": counterparty, "title": title,
            "contract_type": contract_type_hint(title, parties), "source": source}


def clause_changes(theirs: DocxDoc) -> list[Change]:
    """Положения первой версии как «предложенные контрагентом»: абзац за абзацем, кроме начала (стороны, реквизиты),
    заголовков и обрывков. Проверка по плейбуку отсеет те, к которым правил нет."""
    skip = head_indices(theirs)
    out: list[Change] = []
    for para, text in view_paragraphs(theirs, "accepted"):
        text = " ".join(text.split())
        if len(text) < MIN_CLAUSE_CHARS or para.index in skip or _is_heading(para, text):
            continue
        out.append(Change(source="clause", kind="para_insert", clause=para.clause, heading=para.heading,
                          paragraph_index=para.index, order=float(para.index), after=text, context_after=text,
                          flags=flags_for_change("", text)))  # числа, проценты, суммы — для числовых проверок плейбука
        if len(out) >= MAX_CLAUSES:
            break
    for n, c in enumerate(out, 1):
        c.id = f"E{n:03d}"
    return out


def _is_heading(para: Paragraph, text: str) -> bool:
    """Заголовок: ПРОПИСНЫЕ буквы целиком. Короткие заголовки отсекает MIN_CLAUSE_CHARS."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)
