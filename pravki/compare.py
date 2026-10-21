"""Сравнение версии, которую отправили мы, с версией контрагента.

Находит:
  * правки, отмеченные в рецензировании (source = 'tracked');
  * «тихие» правки — изменения текста без отметки в рецензировании (source = 'silent');
  * все отличия, если контрагент вернул чистую версию без рецензирования (source = 'diff').
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .docx_reader import view_paragraphs
from .extract import _short, extract_tracked
from .model import Change, DocxDoc
from .textdiff import diff_changes, flags_for_change, normalize, strip_label

PAIR_THRESHOLD = 0.5


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def _align(base: list[str], theirs: list[str]) -> list[tuple[int | None, int | None]]:
    """Сопоставить абзацы двух версий. Возвращает пары индексов (в base, в theirs); None — нет пары."""
    a = [normalize(t) for t in base]
    b = [normalize(t) for t in theirs]
    pairs: list[tuple[int | None, int | None]] = []
    sm = SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            pairs.extend((i, j) for i, j in zip(range(i1, i2), range(j1, j2)))
        elif tag == "delete":
            pairs.extend((i, None) for i in range(i1, i2))
        elif tag == "insert":
            pairs.extend((None, j) for j in range(j1, j2))
        else:
            pairs.extend(_pair_block(a, b, i1, i2, j1, j2))
    return pairs


def _pair_block(a, b, i1, i2, j1, j2):
    out: list[tuple[int | None, int | None]] = []
    j_cursor = j1
    for i in range(i1, i2):
        best_j, best = None, PAIR_THRESHOLD
        for j in range(j_cursor, j2):
            r = _ratio(a[i], b[j])
            if r > best:
                best_j, best = j, r
        if best_j is None:
            out.append((i, None))
            continue
        out.extend((None, j) for j in range(j_cursor, best_j))
        out.append((i, best_j))
        j_cursor = best_j + 1
    out.extend((None, j) for j in range(j_cursor, j2))
    return out


def find_untracked(base: DocxDoc, theirs: DocxDoc, ours: set[str], label: str) -> list[Change]:
    """Отличия текста, не отмеченные в рецензировании.

    Сравнивается наша отправленная версия (все правки приняты) с версией контрагента, в которой
    все его отмеченные правки отклонены. Если ничего не менялось втихую, тексты совпадают.
    """
    base_view = [(p, t) for p, t in view_paragraphs(base, "accepted", ours) if normalize(t)]
    their_view = [(p, t) for p, t in view_paragraphs(theirs, "rejected", ours) if normalize(t)]
    pairs = _align([t for _, t in base_view], [t for _, t in their_view])
    changes: list[Change] = []
    last_order = -1.0
    for i, j in pairs:
        if j is not None:
            tp, ttext = their_view[j]
            last_order = float(tp.index)
        if i is not None and j is not None:
            bp, btext = base_view[i]
            if normalize(btext) == normalize(ttext):
                continue
            for before, after in diff_changes(normalize(btext), normalize(ttext)):
                kind = "replace" if before and after else ("insert" if after else "delete")
                ch = Change(
                    source=label, kind=kind, clause=tp.clause, heading=tp.heading,
                    paragraph_index=tp.index, order=float(tp.index) + 0.1, before=before, after=after,
                    context=_short(btext), context_after=_short(ttext),
                )
                ch.flags = flags_for_change(before, after)
                changes.append(ch)
        elif i is not None:
            bp, btext = base_view[i]
            if bp.label_in_text:
                btext = strip_label(btext, bp.label)
            ch = Change(
                source=label, kind="para_delete", clause=bp.clause, heading=bp.heading,
                paragraph_index=-1, order=last_order + 0.2, before=normalize(btext),
                context=_short(btext), context_after="",
            )
            ch.flags = flags_for_change(btext, "")
            changes.append(ch)
        else:
            tp, ttext = their_view[j]
            if tp.label_in_text:
                ttext = strip_label(ttext, tp.label)
            ch = Change(
                source=label, kind="para_insert", clause=tp.clause, heading=tp.heading,
                paragraph_index=tp.index, order=float(tp.index) + 0.1, after=normalize(ttext),
                context="", context_after=_short(ttext),
            )
            ch.flags = flags_for_change("", ttext)
            changes.append(ch)
    return changes


def compare_versions(base: DocxDoc | None, theirs: DocxDoc, our_authors: list[str] | None = None) -> list[Change]:
    """Все правки контрагента. base — версия, которую отправили мы (может отсутствовать)."""
    ours = set(our_authors or [])
    if base is not None:
        ours |= set(base.authors)
    ours = {a for a in ours if a}
    changes = extract_tracked(theirs, ours)
    if base is not None:
        label = "silent" if theirs.has_tracked else "diff"
        changes.extend(find_untracked(base, theirs, ours, label))
    changes.sort(key=lambda c: (c.order, c.source != "tracked"))
    for n, c in enumerate(changes, 1):
        c.id = f"E{n:03d}"
        if c.source == "silent":
            c.notes.append("Правка не отмечена в рецензировании (найдена сравнением с отправленной версией)")
        if c.source == "diff":
            c.notes.append("Версия без рецензирования: правка найдена сравнением с отправленной версией")
    return changes
