"""Ответ на правки без отметки в рецензировании: текст контрагента становится нашей правкой в рецензировании.

Правка найдена сравнением с нашей редакцией, в файле контрагента это обычный текст. Отклонить — значит удалить его
текст и вставить прежний (наша правка в рецензировании); встречная редакция — вставить текст юриста. Принять — ничего
не менять: текст контрагента уже стоит.

Текст в Word разбит на куски (w:r / w:t) в произвольных местах, а «было / стало» правки нормализованы (кавычки, тире,
пробелы), поэтому место ищется регулярным выражением, терпимым к этим различиям. Если одинаковых мест несколько,
выбирается то, после замены в котором абзац ближе всего к нашей редакции. Не нашли — правка не трогается и попадает
в счётчик «без отметки».
"""
from __future__ import annotations

import copy
import re
from difflib import SequenceMatcher

from lxml import etree

from .docx_reader import XML_NS, _in_fallback, q
from .textdiff import _DASHES, _QUOTES, normalize

_QUOTE_CLASS = "[" + re.escape("".join(_QUOTES) + "\"'") + "]"
_DASH_CLASS = "[" + re.escape("".join(_DASHES) + "-") + "]"
_HIDDEN = {q("del"), q("moveFrom")}


def pattern(norm: str) -> str:
    """Регулярное выражение для нормализованного текста: любые кавычки, тире и пробельные промежутки."""
    out, space = [], False
    for ch in norm:
        if ch.isspace():
            if not space:
                out.append(r"\s+")
            space = True
            continue
        space = False
        if ch in "\"'":
            out.append(_QUOTE_CLASS)
        elif ch == "-":
            out.append(_DASH_CLASS)
        else:
            out.append(re.escape(ch))
    return "".join(out)


def paragraphs(doc_root) -> list:
    """Абзацы в том же порядке, что в read_docx: индекс правки (paragraph_index) указывает сюда."""
    body = doc_root.find(q("body"))
    return [p for p in body.iter(q("p")) if not _in_fallback(p)] if body is not None else []


def _visible(r, p) -> bool:
    for a in r.iterancestors():
        if a is p:
            return True
        if a.tag in _HIDDEN:
            return False
    return False


def _explode(p) -> None:
    """Каждый видимый прогон — с одним элементом содержимого: так текст можно резать по символам."""
    for r in [r for r in p.iter(q("r")) if _visible(r, p)]:
        content = [c for c in r if c.tag != q("rPr")]
        if len(content) <= 1:
            continue
        rpr = r.find(q("rPr"))
        anchor = r
        for c in content[1:]:
            nr = etree.Element(q("r"))
            if rpr is not None:
                nr.append(copy.deepcopy(rpr))
            nr.append(c)  # элемент переезжает из прежнего прогона в новый
            anchor.addnext(nr)
            anchor = nr


def _nodes(p) -> list[tuple]:
    """(прогон, элемент, текст) видимого текста абзаца по порядку; табуляция и перенос — по одному символу."""
    out = []
    for r in p.iter(q("r")):
        if not _visible(r, p):
            continue
        for c in r:
            if c.tag == q("t"):
                out.append((r, c, c.text or ""))
            elif c.tag == q("tab"):
                out.append((r, c, "\t"))
            elif c.tag in (q("br"), q("cr")):
                out.append((r, c, "\n"))
    return out


def _split_at(p, pos: int) -> None:
    """Разрезать прогон так, чтобы граница текста pos приходилась на границу прогонов."""
    off = 0
    for r, el, text in _nodes(p):
        if off < pos < off + len(text) and el.tag == q("t"):
            k = pos - off
            nr = copy.deepcopy(r)
            el.text = text[:k]
            nt = nr.find(q("t"))
            nt.text = text[k:]
            nt.set(f"{{{XML_NS}}}space", "preserve")
            el.set(f"{{{XML_NS}}}space", "preserve")
            r.addnext(nr)
            return
        off += len(text)


def _runs_in(p, a: int, b: int) -> list:
    off, out = 0, []
    for r, _el, text in _nodes(p):
        if off >= a and off + len(text) <= b and text:
            out.append(r)
        off += len(text)
    return out


def _track(tag: str, rev_id: int, author: str, date: str):
    el = etree.Element(q(tag))
    for k, v in (("id", str(rev_id)), ("author", author), ("date", date)):
        el.set(q(k), v)
    return el


def _ins_run(text: str, like=None):
    r = etree.Element(q("r"))
    if like is not None and like.find(q("rPr")) is not None:
        r.append(copy.deepcopy(like.find(q("rPr"))))
    t = etree.SubElement(r, q("t"))
    t.set(f"{{{XML_NS}}}space", "preserve")
    t.text = text
    return r


class Writer:
    """Наши правки в рецензировании: номера w:id и автор."""

    def __init__(self, author: str, date: str, max_id: int):
        self.author, self.date, self.max_id = author, date, max_id

    def track(self, tag: str):
        self.max_id += 1
        return _track(tag, self.max_id, self.author, self.date)

    def delete_runs(self, runs: list):
        """Обернуть прогоны в нашу w:del (текст → w:delText). Возвращает w:del."""
        d = self.track("del")
        runs[0].addprevious(d)
        for r in runs:
            for t in r.iter(q("t")):
                t.tag = q("delText")
            d.append(r)
        return d

    def insert_after(self, ref, text: str, like=None):
        ins = self.track("ins")
        ins.append(_ins_run(text, like))
        ref.addnext(ins)
        return ins

    def insert_before(self, ref, text: str, like=None):
        ins = self.track("ins")
        ins.append(_ins_run(text, like))
        ref.addprevious(ins)
        return ins

    def mark_paragraph(self, p, tag: str) -> None:
        ppr = p.find(q("pPr"))
        if ppr is None:
            ppr = etree.Element(q("pPr"))
            p.insert(0, ppr)
        rpr = ppr.find(q("rPr"))
        if rpr is None:
            rpr = etree.SubElement(ppr, q("rPr"))
        rpr.append(self.track(tag))


def _best_span(p, ch: dict) -> tuple[int, int] | None:
    """Где в абзаце текст контрагента «стало»: при нескольких совпадениях — ближайший к нашей редакции результат."""
    text = "".join(t for _, _, t in _nodes(p))
    after = ch.get("after", "")
    # отдельным словом или числом («0» не внутри «400 000»), но знак препинания ищется где угодно
    left = r"(?<![\w\d])" if after[:1].isalnum() else ""
    right = r"(?![\d])" if after[-1:].isdigit() else ""
    spans = [m.span() for m in re.finditer(left + pattern(after) + right, text)] if after else []
    if len(spans) <= 1:
        return spans[0] if spans else None
    ours = normalize(ch.get("context", ""))
    return max(spans, key=lambda s: SequenceMatcher(None, normalize(text[:s[0]] + ch.get("before", "") + text[s[1]:]),
                                                   ours, autojunk=False).ratio())


def _insert_point(p, ch: dict) -> int | None:
    """Куда вернуть удалённый контрагентом текст: сразу после слов, которые стояли перед ним в нашей редакции."""
    ours, before = normalize(ch.get("context", "")), ch.get("before", "")
    i = ours.find(before)
    if i < 0:
        return None
    left = ours[:i].rstrip()[-30:]
    if not left:
        return 0
    text = "".join(t for _, _, t in _nodes(p))
    m = None
    for m in re.finditer(pattern(left), text):
        pass  # последнее совпадение слева — ближайшее к месту правки
    return m.end() if m else None


def apply_silent(paras: list, ch: dict, choice: str, text: str, w: Writer, document: list[dict] | None) -> bool:
    """Применить решение к правке без отметки. True — применено, False — место не найдено.

    paras — абзацы файла, снятые один раз до любых изменений (`paragraphs`): возвращённый или удалённый абзац
    не должен сдвигать номера, по которым ищутся следующие правки.
    """
    if choice == "accept":
        return True  # текст контрагента уже в файле
    new = text if choice == "counter" else ch.get("before", "")
    kind, idx = ch.get("kind"), ch.get("paragraph_index", -1)

    if kind == "para_delete" and idx < 0:
        return _restore_paragraph(paras, ch, new, w, document)
    if not 0 <= idx < len(paras):
        return False
    p = paras[idx]
    _explode(p)

    if kind == "para_insert":
        runs = [r for r, _, t in _nodes(p) if t]
        if not runs:
            return False
        d = w.delete_runs(_unique(runs))
        if choice == "counter" and new.strip():
            w.insert_after(d, new, d[0] if len(d) else None)
        else:
            w.mark_paragraph(p, "del")  # абзац контрагента целиком уходит
        return True

    if ch.get("after"):
        span = _best_span(p, ch)
        if span is None:
            return False
        a, b = span
        full = "".join(t for _, _, t in _nodes(p))
        if not new.strip() and a > 0 and full[a - 1] == " " and (b == len(full) or full[b] in " .,;:)»\""):
            a -= 1  # удаляем вставку вместе с пробелом перед ней: «по счёту без предоплаты.» → «по счёту.»
        _split_at(p, b)
        _split_at(p, a)
        runs = _unique(_runs_in(p, a, b))
        if not runs:
            return False
        d = w.delete_runs(runs)
        if new.strip():
            w.insert_after(d, new, d[0])
        return True

    # контрагент удалил наш текст: вернуть его (или встречную редакцию) на прежнее место
    pos = _insert_point(p, ch)
    if pos is None or not new.strip():
        return False
    full = "".join(t for _, _, t in _nodes(p))
    piece = new.strip()
    if pos > 0 and not full[pos - 1].isspace():
        piece = " " + piece  # отделить от слова перед вставкой
    if pos < len(full) and not full[pos].isspace() and full[pos] not in ".,;:)»\"":
        piece += " "  # и от слова после неё
    _split_at(p, pos)
    off = 0
    for r, _el, t in _nodes(p):
        if off == pos:
            w.insert_before(r, piece, r)
            return True
        off += len(t)
    nodes = _nodes(p)
    if not nodes:
        return False
    w.insert_after(nodes[-1][0], piece, nodes[-1][0])  # вставка в конец абзаца
    return True


def _unique(runs: list) -> list:
    seen, out = set(), []
    for r in runs:
        if id(r) not in seen:
            seen.add(id(r))
            out.append(r)
    return out


def _restore_paragraph(paras: list, ch: dict, new: str, w: Writer, document: list[dict] | None) -> bool:
    """Абзац, удалённый контрагентом без отметки: вставить его заново нашей правкой после соседнего абзаца."""
    if not document or not new.strip():
        return False
    prev = -1
    for para in document:
        if para["index"] >= 0:
            prev = para["index"]
        elif ch.get("id") in para.get("changes", []):
            if ch.get("kind") == "para_delete" and para.get("segments"):
                full = para["segments"][0].get("t", "")
                if normalize(new) in normalize(full):
                    new = full  # с номером пункта, как было у нас
            break
    else:
        return False
    if not 0 <= prev < len(paras):
        return False
    anchor = paras[prev]
    p = etree.Element(q("p"))
    ppr = anchor.find(q("pPr"))
    if ppr is not None:
        ppr = copy.deepcopy(ppr)
        for old in ppr.findall(q("rPr")):
            ppr.remove(old)
        p.append(ppr)
    w.mark_paragraph(p, "ins")
    ins = w.track("ins")
    ins.append(_ins_run(new))
    p.append(ins)
    anchor.addnext(p)
    return True


def _tokens(text: str) -> list[str]:
    return re.findall(r"\s+|\w+|[^\w\s]", text)


def apply_edit(p, new_text: str, w: Writer) -> bool:
    """Правка текста абзаца юристом на сайте: разница между текстом в файле и новым текстом оформляется нашими
    вставками и удалениями в рецензировании (по словам). Абзац с правками контрагента не трогается (False): его
    текст в файле неоднозначен, там юрист отвечает решением по правке. Одинаковый текст — ничего не делает (True)."""
    if any(e.tag in (q("ins"), q("del"), q("moveFrom"), q("moveTo")) for e in p.iter()):
        return False
    _explode(p)
    old = "".join(t for _, _, t in _nodes(p))
    if "\t" in old or "\n" in old:
        return False  # табуляция и переносы режут слова непредсказуемо: правка вручную в Word
    new_text = " ".join(new_text.split()) if "\n" in new_text else new_text
    a, b = _tokens(old), _tokens(new_text)
    ops = [o for o in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != "equal"]
    if not ops:
        return True
    pos = [0]
    for tok in a:
        pos.append(pos[-1] + len(tok))
    for tag, i1, i2, j1, j2 in reversed(ops):  # с конца: ранние смещения не меняются
        start, end, ins = pos[i1], pos[i2], "".join(b[j1:j2])
        if end > start:
            _split_at(p, end)
            _split_at(p, start)
            runs = _unique(_runs_in(p, start, end))
            if not runs:
                return False
            d = w.delete_runs(runs)
            if ins:
                w.insert_after(d, ins, d[0] if len(d) else None)
            continue
        _split_at(p, start)  # чистая вставка
        off, placed = 0, False
        for r, _el, t in _nodes(p):
            if off == start and t:
                w.insert_before(r, ins, r)
                placed = True
                break
            off += len(t)
        if not placed:
            nodes = _nodes(p)
            if not nodes:
                return False
            w.insert_after(nodes[-1][0], ins, nodes[-1][0])
    return True


def collapse_spaces(p, w: Writer) -> int:
    """Лишние пробелы в абзаце: из каждой серии пробелов остаётся первый, остальные удаляются нашей правкой. Абзац с
    правками в тексте не трогается. Возвращает число серий."""
    if any(e.tag in (q("ins"), q("del"), q("moveFrom"), q("moveTo")) for e in p.iter()):
        return 0
    from .unified import alignment_line
    _explode(p)
    full = "".join(t for _, _, t in _nodes(p))
    if alignment_line(full):
        return 0  # пробелы выравнивают строку («г. Москва      01.10.2026»)
    spans = [(m.start() + 1, m.end()) for m in re.finditer(" {2,}", full.rstrip()) if m.start() > 0 or full[:m.start()].strip()]
    done = 0
    for a, b in reversed(spans):
        _split_at(p, b)
        _split_at(p, a)
        runs = _unique(_runs_in(p, a, b))
        if runs:
            w.delete_runs(runs)
            done += 1
    return done


def remove_dots(p, w: Writer) -> int:
    """Точка посреди предложения (`unified.find_stray_dots`) удаляется нашей правкой в рецензировании."""
    from .unified import find_stray_dots
    _explode(p)
    full = "".join(t for _, _, t in _nodes(p))
    done = 0
    for a in reversed(find_stray_dots(full)):
        _split_at(p, a + 1)
        _split_at(p, a)
        runs = _unique(_runs_in(p, a, a + 1))
        if runs:
            w.delete_runs(runs)
            done += 1
    return done


def delete_paragraph(p, w: Writer) -> bool:
    """Абзац удаляется нашей правкой в рецензировании: текст зачёркнут, знак абзаца удалён. Абзац с правками в тексте
    не трогается (False): его текст в файле неоднозначен."""
    if any(e.tag in (q("ins"), q("del"), q("moveFrom"), q("moveTo")) for e in p.iter()):
        return False
    _explode(p)
    runs = _unique([r for r, _, t in _nodes(p) if t])
    if runs:
        w.delete_runs(runs)
    w.mark_paragraph(p, "del")
    return True


def insert_paragraphs_after(anchor, text: str, w: Writer) -> int:
    """Новые абзацы (каждая строка текста — абзац) после anchor нашей вставкой в рецензировании; вид (стиль, нумерация,
    отступы) берётся у anchor. Возвращает число вставленных абзацев."""
    n, prev = 0, anchor
    for line in [x.strip() for x in text.splitlines() if x.strip()]:
        p = etree.Element(q("p"))
        ppr = anchor.find(q("pPr"))
        if ppr is not None:
            ppr = copy.deepcopy(ppr)
            for old in ppr.findall(q("rPr")):
                ppr.remove(old)
            p.append(ppr)
        w.mark_paragraph(p, "ins")
        ins = w.track("ins")
        ins.append(_ins_run(line))
        p.append(ins)
        prev.addnext(p)
        prev = p
        n += 1
    return n


def row_of(p):
    """Строка таблицы (w:tr), в которой стоит абзац; None — абзац не в таблице."""
    for a in p.iterancestors():
        if a.tag == q("tr"):
            return a
    return None


def _row_mark(tr, el) -> None:
    trpr = tr.find(q("trPr"))
    if trpr is None:
        trpr = etree.Element(q("trPr"))
        tcs = tr.find(q("tblPrEx"))
        (tcs.addnext if tcs is not None else (lambda x: tr.insert(0, x)))(trpr)
    trpr.append(el)


def delete_row(tr, w: Writer) -> bool:
    """Строка таблицы удаляется нашей правкой: текст ячеек зачёркнут, строка помечена удалённой (w:trPr/w:del)."""
    if any(e.tag in (q("ins"), q("del"), q("moveFrom"), q("moveTo")) for e in tr.iter() if e.getparent() is not None
           and e.getparent().tag != q("trPr")):
        return False
    for p in tr.iter(q("p")):
        _explode(p)
        runs = _unique([r for r, _, t in _nodes(p) if t])
        if runs:
            w.delete_runs(runs)
    _row_mark(tr, w.track("del"))
    return True


def insert_row_after(tr, cells: list[str], w: Writer) -> bool:
    """Новая строка после tr нашей вставкой: та же разметка ячеек (ширины, границы), в каждой ячейке — свой текст."""
    new = copy.deepcopy(tr)
    trpr = new.find(q("trPr"))
    if trpr is not None:
        for old in [x for x in trpr if x.tag in (q("ins"), q("del"))]:
            trpr.remove(old)
    tcs = new.findall(q("tc"))
    if not tcs:
        return False
    for k, tc in enumerate(tcs):
        ps = tc.findall(q("p"))
        for extra in ps[1:]:
            tc.remove(extra)
        for other in [x for x in tc if x.tag not in (q("tcPr"), q("p"))]:
            tc.remove(other)  # вложенные таблицы и прочее — не копируем
        p = ps[0] if ps else etree.SubElement(tc, q("p"))
        for child in [x for x in p if x.tag != q("pPr")]:
            p.remove(child)
        text = cells[k].strip() if k < len(cells) else ""
        if text:
            ins = w.track("ins")
            ins.append(_ins_run(text))
            p.append(ins)
        w.mark_paragraph(p, "ins")
    _row_mark(new, w.track("ins"))
    tr.addnext(new)
    return True
