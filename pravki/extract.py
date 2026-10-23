"""Извлечение правок из docx с отслеживанием изменений (w:ins / w:del / w:moveFrom / w:moveTo) и комментариев."""
from __future__ import annotations

from dataclasses import replace

from .model import Change, DocxDoc, Paragraph, Segment
from .textdiff import flags_for_change, normalize, strip_label

CONTEXT_LIMIT = 1200


def _short(text: str, limit: int = CONTEXT_LIMIT) -> str:
    text = normalize(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _net_zero(s: Segment, ours) -> bool:
    """Чужая вставка, удалённая внутри самого документа: в итоге текста нет и в исходной версии его не было."""
    return s.kind == "del" and s.ins_author is not None and s.ins_author not in ours


def _groups(segs: list[Segment]) -> list[list[Segment]]:
    """Собрать подряд идущие правки одного автора в группы.

    Пробельный кусок обычного текста между двумя правками одного автора не разрывает группу.
    """
    groups: list[list[Segment]] = []
    cur: list[Segment] | None = None
    n = len(segs)
    for i, s in enumerate(segs):
        if s.kind == "equal":
            if (
                cur is not None
                and not s.text.strip()
                and i + 1 < n
                and segs[i + 1].kind != "equal"
                and segs[i + 1].author == cur[0].author
            ):
                cur.append(s)
            else:
                cur = None
            continue
        if cur is not None and cur[0].author == s.author:
            cur.append(s)
        else:
            cur = [s]
            groups.append(cur)
    return groups


def _group_change(para: Paragraph, group: list[Segment]) -> Change | None:
    before = "".join(s.text for s in group if s.kind in ("del", "equal"))
    after = "".join(s.text for s in group if s.kind in ("ins", "equal"))
    if not before.strip() and not after.strip():
        return None
    moved = all(s.move for s in group if s.kind != "equal")
    if before.strip() and after.strip():
        kind = "replace"
    elif after.strip():
        kind = "insert"
    else:
        kind = "delete"
    first = next(s for s in group if s.kind != "equal")
    ch = Change(
        source="tracked",
        kind=kind,
        clause=para.clause,
        heading=para.heading,
        paragraph_index=para.index,
        order=float(para.index),
        before=before.strip(),
        after=after.strip(),
        author=first.author,
        date=first.date,
        context=_short("".join(s.text for s in para.segments if s.kind in ("equal", "del"))),
        context_after=_short("".join(s.text for s in para.segments if s.kind in ("equal", "ins"))),
    )
    if moved:
        ch.detail["move"] = "out" if kind == "delete" else "in"
    ch.flags = flags_for_change(ch.before, ch.after)
    if normalize(ch.before) == normalize(ch.after):
        ch.flags.append("только форматирование/пробелы")
    return ch


def extract_tracked(doc: DocxDoc, ours: set[str] | frozenset[str] = frozenset()) -> list[Change]:
    """Все отслеживаемые правки и комментарии документа.

    ours — авторы, чьи правки считаем своими (их не показываем как правки контрагента).
    """
    changes: list[Change] = []
    for para in doc.paragraphs:
        if any(_net_zero(s, ours) for s in para.segments):
            para = replace(para, segments=[s for s in para.segments if not _net_zero(s, ours)])
        state = para.state()
        if state == "inserted":
            author, date = para.first_author("ins")
            if author in ours:
                continue
            text = "".join(s.text for s in para.segments if s.kind == "ins").strip()
            if para.label_in_text:
                text = strip_label(text, para.label)
            ch = Change(
                source="tracked", kind="para_insert", clause=para.clause, heading=para.heading,
                paragraph_index=para.index, order=float(para.index), after=text, author=author, date=date,
                context="", context_after=_short(text),
            )
            ch.flags = flags_for_change("", text)
            if para.label:
                ch.detail["labeled"] = True
            if all(s.move for s in para.segments if s.kind == "ins"):
                ch.detail["move"] = "in"
            changes.append(ch)
            continue
        if state == "deleted":
            author, date = para.first_author("del")
            if author in ours:
                continue
            text = "".join(s.text for s in para.segments if s.kind == "del").strip()
            if para.label_in_text:
                text = strip_label(text, para.label)
            ch = Change(
                source="tracked", kind="para_delete", clause=para.clause, heading=para.heading,
                paragraph_index=para.index, order=float(para.index), before=text, author=author, date=date,
                context=_short(text), context_after="",
            )
            ch.flags = flags_for_change(text, "")
            if para.label:
                ch.detail["labeled"] = True
            if all(s.move for s in para.segments if s.kind == "del"):
                ch.detail["move"] = "out"
            changes.append(ch)
            continue
        for group in _groups(para.segments):
            if group[0].author in ours:
                continue
            ch = _group_change(para, group)
            if ch is not None:
                changes.append(ch)
        if para.mark == "del" and para.mark_author not in ours and para.state() == "":
            ch = Change(
                source="tracked", kind="delete", clause=para.clause, heading=para.heading,
                paragraph_index=para.index, order=para.index + 0.5, before="[разрыв абзаца]",
                author=para.mark_author, context=_short("".join(x.text for x in para.segments)),
            )
            ch.flags = ["склейка абзацев"]
            changes.append(ch)

    for cid, c in doc.comments.items():
        if c.author in ours:
            continue
        para = doc.paragraphs[c.paragraph_index] if 0 <= c.paragraph_index < len(doc.paragraphs) else None
        changes.append(
            Change(
                source="tracked", kind="comment", clause=para.clause if para else "",
                heading=para.heading if para else "", paragraph_index=c.paragraph_index,
                order=(c.paragraph_index if c.paragraph_index >= 0 else 10**6) + 0.25,
                before=c.anchor, after=c.text, author=c.author, date=c.date,
                context=_short("".join(s.text for s in para.segments)) if para else "",
                detail={"comment_id": cid},
            )
        )
    _pair_moves(changes)
    changes.sort(key=lambda c: c.order)
    return changes


def _pair_moves(changes: list[Change]) -> None:
    """Перемещения Word: пара «вырезано / вставлено» с одинаковым текстом превращается в одну правку."""
    outs = [c for c in changes if c.detail.get("move") == "out"]
    ins = [c for c in changes if c.detail.get("move") == "in"]
    used: set[int] = set()
    drop: set[int] = set()
    for o in outs:
        key = normalize(o.before).lower()
        for i in ins:
            if id(i) in used:
                continue
            if normalize(i.after).lower() == key:
                used.add(id(i))
                drop.add(id(i))
                o.kind = "move"
                o.after = o.before
                o.detail["move_to"] = i.clause or i.paragraph_index
                o.detail["move_from"] = o.clause
                o.notes.append(
                    f"перемещено из п. {o.clause or '?'} в п. {i.clause or '?'}: текст прежний, меняется только место"
                )
                break
    if drop:
        changes[:] = [c for c in changes if id(c) not in drop]
