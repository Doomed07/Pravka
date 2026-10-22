"""Единая версия договора: текст версии контрагента, в котором видны все правки по сравнению с нашей редакцией.

Отмеченные в рецензировании правки контрагента берутся из самого файла (ins / del), наши правки показываются
обычным текстом. Правки без отметки находятся сравнением с отправленной нами версией (как в `find_untracked`)
и помечаются отдельно (silent_ins / silent_del), чтобы юрист их не спутал с отмеченными.
"""
from __future__ import annotations

import re

from .compare import _align
from .docx_reader import view_paragraphs
from .extract import _net_zero
from .model import ANNOTATOR, Change, DocxDoc, Paragraph
from .textdiff import diff_ops, normalize


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _push(segs: list[dict], kind: str, text: str, author: str = "") -> None:
    if not text:
        return
    if segs and segs[-1]["k"] == kind and segs[-1]["a"] == author:
        segs[-1]["t"] += text
    else:
        segs.append({"k": kind, "t": text, "a": author})


def _tracked_segments(para: Paragraph, ours) -> list[dict]:
    """Текст абзаца с чужими правками: наши правки приняты, чужие видны как ins / del."""
    segs: list[dict] = []
    for s in para.segments:
        if _net_zero(s, ours) or s.author == ANNOTATOR and s.kind == "ins":
            continue  # чужая вставка, удалённая внутри файла: текста не было и нет
        if s.kind == "equal":
            _push(segs, "equal", s.text)
        elif s.author in ours:
            if s.kind == "ins":
                _push(segs, "equal", s.text)
            # наше удаление уже принято: текста нет
        else:
            _push(segs, s.kind, s.text, s.author)
    return segs


def _overlay(before: str, segs: list[dict]) -> list[dict]:
    """Наложить на абзац неотмеченные отличия от нашей редакции, не трогая отмеченные правки.

    Текст абзаца без правок контрагента (обычный + удалённый им) сравнивается с нашей редакцией: отличия — правки
    без отметки. Отмеченные вставки контрагента в это сравнение не входят и остаются на своих местах.
    """
    rejected = "".join(s["t"] for s in segs if s["k"] in ("equal", "del"))
    marks: list[str] = []  # для каждого символа rejected: equal или silent_ins
    gaps: dict[int, str] = {}  # позиция в rejected → текст нашей редакции, удалённый перед ней без отметки
    pos = 0
    for tag, x, y in diff_ops(before, rejected):
        same = tag == "equal" or normalize(x) == normalize(y)  # пробелы, кавычки, тире — не правка
        if not same and x:
            gaps[pos] = gaps.get(pos, "") + x
        marks += ["equal" if same else "silent_ins"] * len(y)
        pos += len(y)
    out: list[dict] = []
    pos = 0
    for s in segs:
        if s["k"] == "ins":
            _push(out, "ins", s["t"], s["a"])
            continue
        for ch in s["t"]:
            if pos in gaps:
                _push(out, "silent_del", gaps.pop(pos))
            if s["k"] == "del":
                _push(out, "del", ch, s["a"])
            else:
                _push(out, marks[pos], ch)
            pos += 1
    for rest in gaps.values():
        _push(out, "silent_del", rest)
    return out


def _auto_label(para: Paragraph) -> str:
    """Номер пункта из автонумерации Word: в тексте абзаца его нет, показываем отдельно."""
    return "" if para.label_in_text else para.label


def build_unified(base: DocxDoc | None, theirs: DocxDoc, ours, changes: list[Change]) -> list[dict]:
    """Список абзацев единой версии: {index, clause, label, style, segments, changes}.

    label — номер пункта из автонумерации Word (его нет в тексте абзаца); пусто, если номер напечатан в тексте.

    index — номер абзаца в версии контрагента (-1 у абзаца, который есть только в нашей версии);
    changes — номера правок (Change.id), относящихся к абзацу.
    """
    ours = set(ours)
    paras: dict[int, dict] = {}
    for para in theirs.paragraphs:
        segs = _tracked_segments(para, ours)
        if not "".join(s["t"] for s in segs).strip():
            continue
        paras[para.index] = {"index": para.index, "clause": para.clause, "label": _auto_label(para), "style": para.style,
                             "segments": segs, "changes": []}

    removed: list[tuple[int, dict]] = []  # абзацы, удалённые без отметки: (после какого абзаца, абзац)
    if base is not None:
        base_view = [(p, t) for p, t in view_paragraphs(base, "rejected", ours) if normalize(t)]
        their_view = [(p, t) for p, t in view_paragraphs(theirs, "rejected", ours) if normalize(t)]
        last = -1
        for i, j in _align([t for _, t in base_view], [t for _, t in their_view]):
            if j is not None:
                tp, ttext = their_view[j]
                last = tp.index
                target = paras.get(tp.index)
                if target is None:
                    continue
                if i is not None and normalize(base_view[i][1]) == normalize(ttext):
                    continue
                target["segments"] = _overlay(base_view[i][1] if i is not None else "", target["segments"])
            else:
                bp, btext = base_view[i]
                removed.append((last, {"index": -1, "clause": bp.clause, "label": _auto_label(bp), "style": bp.style,
                                       "segments": [{"k": "silent_del", "t": _squash(btext), "a": ""}],
                                       "changes": []}))

    out: list[dict] = []
    pending = sorted(removed, key=lambda x: x[0])
    k = 0
    while k < len(pending) and pending[k][0] < 0:
        out.append(pending[k][1])
        k += 1
    for idx in sorted(paras):
        out.append(paras[idx])
        while k < len(pending) and pending[k][0] <= idx:
            out.append(pending[k][1])
            k += 1
    out.extend(p for _, p in pending[k:])

    by_index = {p["index"]: p for p in out if p["index"] >= 0}
    for c in changes:
        target = by_index.get(c.paragraph_index)
        if target is None and c.paragraph_index < 0 and c.before:
            key = normalize(c.before)
            target = next((p for p in out if p["index"] < 0 and key in normalize(p["segments"][0]["t"])), None)
        if target is not None and c.id:
            target["changes"].append(c.id)
    return out
