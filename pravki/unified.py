"""Единая версия договора: текст версии контрагента, в котором видны все правки по сравнению с нашей редакцией.

Отмеченные в рецензировании правки контрагента берутся из самого файла (ins / del), наши правки показываются
обычным текстом. Правки без отметки находятся сравнением с отправленной нами версией (как в `find_untracked`)
и помечаются отдельно (silent_ins / silent_del), чтобы юрист их не спутал с отмеченными.
"""
from __future__ import annotations

import re
from collections import Counter

from .classify import _known
from .compare import _align, label_policy, paired_views
from .docx_reader import view_paragraphs
from .extract import _net_zero
from .model import ANNOTATOR, Change, DocxDoc, Paragraph
from .textdiff import diff_ops, normalize, strip_label


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _push(segs: list[dict], kind: str, text: str, author: str = "", font: tuple = (False, False)) -> None:
    """Добавить кусок текста; b / i (жирный, курсив) ставятся, только если включены."""
    if not text:
        return
    b, i = font
    if segs and segs[-1]["k"] == kind and segs[-1]["a"] == author and _font(segs[-1]) == (b, i):
        segs[-1]["t"] += text
        return
    seg = {"k": kind, "t": text, "a": author}
    if b:
        seg["b"] = True
    if i:
        seg["i"] = True
    segs.append(seg)


def _font(seg: dict) -> tuple[bool, bool]:
    return bool(seg.get("b")), bool(seg.get("i"))


def _tracked_segments(para: Paragraph, ours) -> list[dict]:
    """Текст абзаца с чужими правками: наши правки приняты, чужие видны как ins / del."""
    segs: list[dict] = []
    for s in para.segments:
        if _net_zero(s, ours) or s.author == ANNOTATOR and s.kind == "ins":
            continue  # чужая вставка, удалённая внутри файла: текста не было и нет
        font = (s.bold, s.italic)
        if s.kind == "equal":
            _push(segs, "equal", s.text, font=font)
        elif s.author in ours:
            if s.kind == "ins":
                _push(segs, "equal", s.text, font=font)
            # наше удаление уже принято: текста нет
        else:
            _push(segs, s.kind, s.text, s.author, font)
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
        font = _font(s)
        if s["k"] == "ins":
            _push(out, "ins", s["t"], s["a"], font)
            continue
        for ch in s["t"]:
            if pos in gaps:
                _push(out, "silent_del", gaps.pop(pos))
            if s["k"] == "del":
                _push(out, "del", ch, s["a"], font)
            else:
                _push(out, marks[pos], ch, font=font)
            pos += 1
    for rest in gaps.values():
        _push(out, "silent_del", rest)
    return out


def _layout(para: Paragraph) -> dict:
    """Вид абзаца из Word: список (bullet / number), уровень, отступ слева в твипах, выравнивание."""
    return {"list": para.list_kind, "level": para.level, "indent": para.indent, "align": para.align}


def _auto_label(para: Paragraph) -> str:
    """Номер пункта из автонумерации Word: в тексте абзаца его нет, показываем отдельно."""
    return "" if para.label_in_text else para.label


def _removed_cell(bp: Paragraph, prev: dict | None):
    """Ячейка для абзаца, удалённого без отметки из таблицы: в той же таблице версии контрагента, что и абзац перед ним.

    Так короткое значение ячейки («475 000» → «500 000») показывается в своей ячейке, а не отдельной строкой,
    разрывающей таблицу. Номер таблицы берём у соседнего абзаца: в двух версиях таблицы могут нумероваться по-разному.
    """
    if not bp.table:
        return None
    if prev is not None and prev.get("table"):
        return [prev["table"][0], bp.table[1], bp.table[2], bp.table[3]]
    return list(bp.table)


def build_unified(base: DocxDoc | None, theirs: DocxDoc, ours, changes: list[Change]) -> list[dict]:
    """Список абзацев единой версии: {index, clause, label, style, segments, changes, table}.

    table — [номер таблицы, строка, столбец, ширина] для абзаца в ячейке таблицы (None вне таблицы): по нему таблица
    собирается обратно целиком, а не рассыпается на отдельные абзацы.

    label — номер пункта из автонумерации Word (его нет в тексте абзаца); пусто, если номер напечатан в тексте.

    index — номер абзаца в версии контрагента (-1 у абзаца, который есть только в нашей версии);
    changes — номера правок (Change.id), относящихся к абзацу; comments — комментарии сторон к абзацу целиком
    ({author, date, text, ours, anchor}).
    """
    ours = set(ours)
    paras: dict[int, dict] = {}
    for para in theirs.paragraphs:
        segs = _tracked_segments(para, ours)
        if not "".join(s["t"] for s in segs).strip() and not para.table:
            continue  # пустой абзац; пустую ячейку таблицы оставляем, иначе таблица «съезжает»
        paras[para.index] = {"index": para.index, "clause": para.clause, "label": _auto_label(para), "style": para.style,
                             **_layout(para),
                             "segments": segs, "changes": [], "table": list(para.table) if para.table else None}

    removed: list[tuple[int, dict]] = []  # абзацы, удалённые без отметки: (после какого абзаца, абзац)
    if base is not None:
        base_view, their_view = paired_views(base, theirs, ours)
        base_view = [(p, t) for p, t in base_view if normalize(t)]
        their_view = [(p, t) for p, t in their_view if normalize(t)]
        _, strip_theirs = label_policy(base, theirs)
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
                before = base_view[i][1] if i is not None else ""
                if strip_theirs and i is not None and tp.label_in_text:
                    # номер пункта в тексте контрагента напечатан, у нас — нет: добавляем его к нашему тексту, иначе он «вставка»
                    shown = "".join(sg["t"] for sg in target["segments"])
                    before = shown[:len(shown) - len(strip_label(shown, tp.label))] + before
                target["segments"] = _overlay(before, target["segments"])
            else:
                bp, btext = base_view[i]
                removed.append((last, {"index": -1, "clause": bp.clause, "label": _auto_label(bp), "style": bp.style,
                                       **_layout(bp),
                                       "segments": [{"k": "silent_del", "t": _squash(btext), "a": ""}],
                                       "changes": [], "table": _removed_cell(bp, paras.get(last))}))

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

    def removed_with(text: str):
        key = normalize(text)
        return next((p for p in out if p["index"] < 0 and key and key in normalize(p["segments"][0]["t"])), None)

    for c in changes:
        if not c.id:
            continue
        targets = [by_index.get(c.paragraph_index)]
        if c.paragraph_index < 0 and c.before:
            targets = [removed_with(c.before)]
        if c.detail.get("replaced_para"):  # пункт заменён: правка относится и к прежней редакции абзаца
            targets.append(by_index.get(c.detail.get("replaced_index", -1)) or removed_with(c.before))
        for target in targets:
            if target is not None and c.id not in target["changes"]:
                target["changes"].append(c.id)

    # комментарии сторон — целиком, для контекста (наши тоже: на них часто отвечает контрагент)
    for p in out:
        p["comments"] = []
    for cm in sorted(theirs.comments.values(), key=lambda x: (x.date, x.id)):
        target = by_index.get(cm.paragraph_index)
        if target is None or cm.author == ANNOTATOR or not cm.text.strip():
            continue
        target["comments"].append({"author": cm.author, "date": cm.date, "text": cm.text, "ours": cm.author in ours,
                                   "anchor": cm.anchor})
    mark_broken_paragraphs(out)
    mark_extra_spaces(out)
    mark_stray_dots(out)
    return out



_END = ".;:!?…"
_NUMBERED = re.compile(r"^\s*(\d+(\.\d+)*[.)]?|[а-яa-z][.)])\s")
MAX_TAIL = 40  # короткий обрывок из следующего абзаца — не длиннее (символов)


def _plain(p: dict) -> str:
    return "".join(s["t"] for s in p["segments"]).strip()


_WORD = re.compile(r"[^\W\d_]+")


def _mid_word(a: str, b: str, vocab: Counter) -> bool:
    """Разрыв посреди слова («Орг» / «анизатор имеет…»): перенос по дефису либо целое слово есть в этом же договоре,
    а его половин как отдельных слов нет. Слова «на» / «основании» так не склеиваются: обе половины — слова договора."""
    if a.endswith("-") and b[:1].islower():
        return True
    left, right = _WORD.findall(a.lower()), _WORD.findall(b.lower())
    if not left or not right or a[-1:].isalpha() is False:
        return False
    first, last = left[-1], right[0]
    if vocab[first + last] > 0 and (vocab[first] <= 1 or vocab[last] <= 1):  # 1 — сам обрывок на этом месте
        return True
    # слова нет в договоре — решает словарь русского языка (pymorphy3, локально): целое слово словарю знакомо, а
    # обе половины настоящие слова не все сразу («Организ» / «атор»), либо словарь не знает ни одной половины («Орг» / «анизатор»)
    k1, k2, kj = _known(first), _known(last), _known(first + last)
    return (kj and not (k1 and k2)) or (not k1 and not k2)


def _heading(p: dict) -> bool:
    style = (p.get("style") or "").lower()
    return style.startswith("heading") or style.startswith("заголовок") or style == "title"


def mark_broken_paragraphs(out: list[dict]) -> int:
    """Предложение, разорванное границей абзаца: абзацу, который надо склеить со следующим, ставится join_next.
    Осторожно: оба абзаца без правок в тексте и вне таблиц, следующий идёт сразу за первым, не пронумерован и не список,
    а первый до конца предложения не дошёл. Признак продолжения — одно из двух: следующий абзац начинается со строчной
    буквы («…5 (пяти)» / «рабочих дней…») либо он короткий и заканчивается знаком конца предложения («…гл. 26.2-1» /
    «НК РФ.»). Склейка — исправление вёрстки, не смысла: на сайте она подсвечена, юрист может её отклонить."""
    n = 0
    vocab = Counter(w for para in out for w in _WORD.findall(_plain(para).lower()))
    for p, q in zip(out, out[1:]):
        if p["index"] < 0 or q["index"] != p["index"] + 1 or p.get("table") or q.get("table"):
            continue
        if any(x["k"] != "equal" for x in p["segments"] + q["segments"]) or _heading(p) or _heading(q):
            continue
        if p.get("comments") or q.get("comments") or q.get("label") or q.get("list") or p.get("list") == "bullet":
            continue
        a, b = _plain(p), _plain(q)
        if not a or not b or a[-1] in _END or _NUMBERED.match(b):
            continue
        lower = b[0].islower()
        same_kind = p["style"] == q["style"] or (p["style"] or "").lower().startswith("list")
        short = len(a) >= 40 and len(b) <= MAX_TAIL and b[-1] in ".;" and same_kind
        if lower or short:
            p["join_next"] = True
            if _mid_word(a, b, vocab):
                p["join_glue"] = True  # слово разорвано границей абзаца: склеивать без пробела
            n += 1
    return n


_SPACES = re.compile(" {2,}")


def alignment_line(text: str) -> bool:
    """Строка, где пробелы выравнивают части по ширине страницы («г. Москва          01.10.2026», строка подписей):
    короткая по буквам и с длинной серией пробелов. Такие пробелы не лишние — их не трогаем."""
    t = text.strip()
    if re.search(" {20,}", t):
        return True  # такая длинная серия — только чтобы отодвинуть текст к правому краю
    m = re.search(r" {4,}(\S)", t)
    # короткая строка, и после пробелов не продолжение фразы со строчной буквы («право.      отказаться» — ошибка)
    return m is not None and len(t.replace(" ", "")) < 60 and not m.group(1).islower()


def mark_extra_spaces(out: list[dict]) -> int:
    """Лишние пробелы внутри абзаца («пять  тысяч», «право.            отказаться»): extra_spaces — сколько таких мест.
    Только абзацы без правок в тексте: в Word лишние пробелы убираются нашей правкой, на сайте место подсвечено."""
    n = 0
    for p in out:
        if p["index"] < 0 or any(x["k"] != "equal" for x in p["segments"]):
            continue
        text = "".join(x["t"] for x in p["segments"])
        found = 0 if alignment_line(text) else len(_SPACES.findall(text.strip()))
        if found:
            p["extra_spaces"] = found
            n += found
    return n


# Сокращения, после которых точка и строчная буква — норма («ст. 5», «руб. и», «т. е.»)
_ABBR = {"ст", "п", "пп", "подп", "ч", "гл", "разд", "рис", "табл", "стр", "см", "напр", "руб", "коп", "тыс", "млн", "млрд",
         "трлн", "гг", "им", "ул", "пр", "обл", "тел", "ред", "прим", "наим", "лит", "экз", "шт", "мин", "сек", "кв", "куб",
         "др", "пр", "прочее", "кор", "корр", "расч", "почт", "факс", "адр", "ген", "нач", "зам", "пред", "гор", "обл", "р", "с", "проч", "общ", "соотв", "уч", "изд", "утв", "авг", "сент", "окт", "ноя", "дек", "янв", "февр"}
_DOT = re.compile(r"(?<![\w.])([^\W\d_]{3,})\.[ \t]+(?=[а-яё]{2,}(?!\)))")


def find_stray_dots(text: str) -> list[int]:
    """Точка посреди предложения: слово из 3+ букв, точка, пробелы и слово со строчной буквы («право.   отказаться»).
    Номера пунктов, сокращения (_ABBR), инициалы и «а)» не считаются. Возвращает позиции точек в тексте."""
    return [m.end(1) for m in _DOT.finditer(text) if m.group(1).lower() not in _ABBR]


def mark_stray_dots(out: list[dict]) -> int:
    """Точки внутри предложения: stray_dots — позиции таких точек в абзаце без правок в тексте. Позиции программа ищет заново
    (`find_stray_dots`), а на сайте и в Word место подсвечивается и исправляется нашей правкой, которую можно отклонить."""
    n = 0
    for p in out:
        if p["index"] < 0 or any(x["k"] != "equal" for x in p["segments"]):
            continue
        found = find_stray_dots("".join(x["t"] for x in p["segments"]))
        if found:
            p["stray_dots"] = found  # позиции точек в тексте абзаца: по ним сайт подсвечивает место
            n += len(found)
    return n
