"""Модель данных: абзацы документа с отслеживаемыми правками и найденные изменения."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .textdiff import normalize

# Автор примечаний и дисклеймера в единой версии Word (annotate.py). Всегда считается нашим.
ANNOTATOR = "Правки (черновик)"


@dataclass
class Segment:
    """Кусок текста абзаца: обычный, вставленный или удалённый."""

    kind: str  # 'equal' | 'ins' | 'del'
    text: str
    author: str = ""
    date: str = ""
    move: bool = False  # True для перемещений (moveFrom / moveTo)
    # Для удаления внутри чужой или своей вставки (w:ins > w:del): автор вставки; иначе None.
    # Текст вставил один автор, а удалил другой: при «отклонить все» он вернётся, только если
    # вставка наша, а удаление чужое.
    ins_author: str | None = None
    bold: bool = False
    italic: bool = False
    rev: str = ""  # w:id правки Word (w:ins / w:del / w:moveFrom / w:moveTo), к которой относится кусок


@dataclass
class Paragraph:
    index: int
    label: str = ""  # номер пункта, как он показан (автонумерация или номер в тексте)
    label_in_text: bool = False  # номер напечатан в самом тексте абзаца
    near: str = ""  # ближайший выше номер пункта (для абзацев без номера)
    heading: str = ""  # ближайший выше заголовок раздела
    style: str = ""
    in_table: bool = False
    table: tuple = ()  # (номер таблицы, строка, столбец, ширина в столбцах) — для абзацев внутри таблицы
    list_kind: str = ""  # пусто, bullet (маркированный список) или number (нумерованный)
    level: int = 0  # уровень вложенности списка (ilvl)
    indent: int = 0  # отступ слева в твипах (1/20 пункта), из w:ind
    align: str = ""  # пусто, center, right или both (по ширине)
    mark: str = ""  # '', 'ins', 'del': отслеживаемая правка знака абзаца
    mark_author: str = ""
    mark_rev: str = ""  # w:id правки знака абзаца
    segments: list[Segment] = field(default_factory=list)
    comment_ids: list[str] = field(default_factory=list)

    @property
    def clause(self) -> str:
        return self.label or self.near

    def content_kinds(self) -> set[str]:
        return {s.kind for s in self.segments if s.text.strip()}

    def state(self) -> str:
        """'inserted' / 'deleted', если весь текст абзаца добавлен/удалён правками."""
        kinds = self.content_kinds()
        if kinds == {"ins"}:
            return "inserted"
        if kinds == {"del"}:
            return "deleted"
        return ""

    def first_author(self, kind: str) -> tuple[str, str]:
        for s in self.segments:
            if s.kind == kind and s.text.strip():
                return s.author, s.date
        return "", ""

    def has_tracked(self) -> bool:
        return bool(self.mark) or any(s.kind != "equal" for s in self.segments)


@dataclass
class Comment:
    id: str
    author: str = ""
    date: str = ""
    text: str = ""
    anchor: str = ""
    paragraph_index: int = -1


@dataclass
class DocxDoc:
    path: str
    paragraphs: list[Paragraph]
    comments: dict[str, Comment]
    authors: list[str]
    format: str = "docx"  # docx | odt | pdf
    notes: list[str] = field(default_factory=list)  # что юристу надо знать о том, как прочитан файл (попадает в предупреждения)

    @property
    def has_tracked(self) -> bool:
        return any(p.has_tracked() for p in self.paragraphs)


@dataclass
class Change:
    """Одна найденная правка с разбором."""

    id: str = ""
    source: str = "tracked"  # tracked | silent | diff
    kind: str = "replace"  # insert | delete | replace | move | para_insert | para_delete | comment
    clause: str = ""
    heading: str = ""
    paragraph_index: int = -1
    order: float = 0.0
    before: str = ""
    after: str = ""
    context: str = ""  # абзац до правки
    context_after: str = ""  # абзац после правки
    author: str = ""
    date: str = ""
    flags: list[str] = field(default_factory=list)
    topic: str = ""
    areas: list[str] = field(default_factory=list)
    materiality: str = ""  # высокая | средняя | низкая | техническая
    # разбор по плейбуку
    rule_id: str = ""
    rule_title: str = ""
    level: str = ""  # accept | fallback | reject | review
    action: str = ""
    explanation: str = ""
    suggested: str = ""
    escalate_to: str = ""
    lawyer_decision_needed: bool = False
    out_of_playbook: bool = False
    # журнал
    status: str = "new"  # new | repeated | accepted | rejected | counter
    repeat_note: str = ""
    notes: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    @property
    def area(self) -> str:
        return ", ".join(self.areas)

    def fingerprint(self) -> str:
        raw = f"{normalize(self.before).lower()}|{normalize(self.after).lower()}|{self.kind}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "kind": self.kind,
            "clause": self.clause,
            "heading": self.heading,
            "paragraph_index": self.paragraph_index,
            "before": self.before,
            "after": self.after,
            "context": self.context,
            "context_after": self.context_after,
            "author": self.author,
            "date": self.date,
            "flags": list(self.flags),
            "topic": self.topic,
            "areas": list(self.areas),
            "materiality": self.materiality,
            "rule_id": self.rule_id,
            "rule_title": self.rule_title,
            "level": self.level,
            "action": self.action,
            "explanation": self.explanation,
            "ai_explained": "template_explanation" in self.detail,  # пояснение написала модель
            "accepted_from_base": list(self.detail.get("accepted_from_base", [])),  # авторы принятой правки из нашей версии
            "replaced_para": self.detail.get("replaced_para", ""),
            "revs": list(self.detail.get("revs", [])),
            "comment_id": self.detail.get("comment_id", ""),  # w:id комментария Word (для ответа в ветке)  # w:id правок Word: по ним собирается ответ (answer.py)  # пункт заменён целиком: clause (по номеру) или model
            "suggested": self.suggested,
            "escalate_to": self.escalate_to,
            "lawyer_decision_needed": self.lawyer_decision_needed,
            "out_of_playbook": self.out_of_playbook,
            "status": self.status,
            "repeat_note": self.repeat_note,
            "notes": list(self.notes),
            "fingerprint": self.fingerprint(),
        }
