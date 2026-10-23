"""Ответ контрагенту в Word: решения юриста по правкам применяются к его файлу.

Источник — единая версия из разбора (`annotate.annotate_docx`): файл контрагента с его правками в рецензировании
и нашими примечаниями. Наши примечания (автор ANNOTATOR) вырезаются: файл уходит контрагенту. Дисклеймер остаётся
вставкой в рецензировании — юрист отклоняет его перед отправкой (принцип 5: файл — черновик).

Выбор по правке (choices[id правки]):
  accept  — принять правку контрагента;
  reject  — отклонить её (вернуть прежний текст);
  counter — встречная редакция: правку контрагента убрать, прежний текст удалить нашей правкой и вставить
            текст юриста нашей правкой в рецензировании. Текст пишет юрист, программа его не сочиняет.
Правки без выбора остаются в файле как есть. Правки без отметки в рецензировании (найдены сравнением) оформляются
нашей правкой в рецензировании (`answer_silent`). Ответы на комментарии пока не входят.
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone

from lxml import etree

from .docx_reader import XML_NS, DocxError, _read_part, q
from .answer_silent import Writer, apply_silent, paragraphs
from .model import ANNOTATOR

TRACKED = {q("ins"), q("del"), q("moveFrom"), q("moveTo")}
INSERTS = {q("ins"), q("moveTo")}
CHOICES = ("accept", "reject", "counter")


def _unwrap(el) -> None:
    """Заменить элемент его содержимым (принять вставку, отклонить удаление)."""
    parent = el.getparent()
    i = parent.index(el)
    for child in list(el):
        parent.insert(i, child)
        i += 1
    parent.remove(el)


def _undelete(el) -> None:
    """Удалённый текст снова становится обычным: w:delText → w:t."""
    for t in el.iter(q("delText")):
        t.tag = q("t")
    for t in el.iter(q("delInstrText")):
        t.tag = q("instrText")


def _is_mark(el) -> bool:
    """Правка знака абзаца (w:pPr/w:rPr/w:ins|w:del), а не текста."""
    parent = el.getparent()
    return parent is not None and parent.tag == q("rPr") and parent.getparent() is not None \
        and parent.getparent().tag == q("pPr")


def _has_text(p) -> bool:
    return any((t.text or "").strip() for t in p.iter(q("t"), q("delText")))


def _drop_mark(el, remove_empty_paragraph: bool) -> None:
    p = el.getparent().getparent().getparent()  # w:p / w:pPr / w:rPr / метка
    el.getparent().remove(el)
    if remove_empty_paragraph and p is not None and p.getparent() is not None and not _has_text(p):
        p.getparent().remove(p)


def _apply(el, choice: str, author: str, date: str) -> None:
    if _is_mark(el):
        inserted = el.tag == q("ins")
        # принять удаление знака или отклонить вставку: пустой абзац исчезает; с текстом — снимаем только метку
        _drop_mark(el, remove_empty_paragraph=(choice == "accept") != inserted)
        return
    if el.tag in INSERTS:
        if choice == "accept":
            _unwrap(el)
        else:  # reject и counter: вставку контрагента убираем
            el.getparent().remove(el)
        return
    if choice == "accept":
        el.getparent().remove(el)
    elif choice == "reject":
        _undelete(el)
        _unwrap(el)
    else:  # counter: прежний текст удаляем уже мы — правка остаётся удалением, но наша
        el.set(q("author"), author)
        el.set(q("date"), date)


def _strip_annotations(doc_root, comments_root) -> int:
    """Убрать наши примечания (ANNOTATOR) и их якоря в тексте. Комментарии сторон остаются."""
    if comments_root is None:
        return 0
    ours = {c.get(q("id")) for c in comments_root.findall(q("comment")) if c.get(q("author")) == ANNOTATOR}
    for c in [c for c in comments_root.findall(q("comment")) if c.get(q("id")) in ours]:
        comments_root.remove(c)
    for el in list(doc_root.iter(q("commentRangeStart"), q("commentRangeEnd"), q("commentReference"))):
        if el.get(q("id")) not in ours:
            continue
        target = el.getparent() if el.tag == q("commentReference") else el  # ссылка живёт в своём w:r
        if target.getparent() is not None:
            target.getparent().remove(target)
    return len(ours)


def _our_insert(text: str, author: str, date: str, rev_id: int):
    ins = etree.Element(q("ins"))
    for k, v in (("id", str(rev_id)), ("author", author), ("date", date)):
        ins.set(q(k), v)
    r = etree.SubElement(ins, q("r"))
    t = etree.SubElement(r, q("t"))
    t.set(f"{{{XML_NS}}}space", "preserve")
    t.text = text
    return ins


def build_answer(src_docx: str, out_docx: str, changes: list[dict], choices: dict[str, dict], author: str,
                 document: list[dict] | None = None) -> dict:
    """Собрать ответ. changes — правки разбора (to_dict, с полем revs), choices — {id: {"choice", "text"}},
    document — единая версия (абзацы): по ней возвращается абзац, удалённый контрагентом без отметки.
    Возвращает счётчики: принято, отклонено, встречных редакций, «без отметки» — решения, которые не удалось
    применить (место правки не найдено)."""
    author = (author or "").strip() or "Юрист"
    try:
        zin = zipfile.ZipFile(src_docx)
    except (OSError, zipfile.BadZipFile) as e:
        raise DocxError(f"не удалось открыть {src_docx}: {e.__class__.__name__}")
    with zin:
        names = zin.namelist()
        doc_root = _read_part(zin, "word/document.xml", required=True)
        comments_root = _read_part(zin, "word/comments.xml")
        raw = {n: zin.read(n) for n in names}

    stats = {"accept": 0, "reject": 0, "counter": 0, "без отметки": 0, "наших примечаний убрано": 0}
    stats["наших примечаний убрано"] = _strip_annotations(doc_root, comments_root)
    by_id: dict[str, list] = {}
    max_id = 0
    for el in doc_root.iter():
        if el.tag in TRACKED and el.get(q("id")):
            by_id.setdefault(el.get(q("id")), []).append(el)
            if el.get(q("id")).isdigit():
                max_id = max(max_id, int(el.get(q("id"))))
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    paras = paragraphs(doc_root)  # один раз, до изменений: номера абзацев правок указывают сюда

    for ch in changes:
        sel = choices.get(ch.get("id", "")) or {}
        choice = sel.get("choice", "")
        if choice not in CHOICES or ch.get("kind") == "comment":
            continue
        text = sel.get("text") or ""  # как написал юрист: ведущий пробел отделяет вставку от текста перед ней
        els = [e for r in ch.get("revs") or [] for e in by_id.get(r, []) if e.getparent() is not None]
        if not els:
            # правка без отметки в рецензировании: текст контрагента становится нашей правкой (answer_silent)
            silent = ch.get("source") in ("silent", "diff") and ch.get("rule_id") != "PARTY"
            if silent and (choice != "counter" or text.strip()):
                writer = Writer(author, date, max_id)
                done = apply_silent(paras, ch, choice, text, writer, document)
                max_id = writer.max_id
                if done:
                    stats[choice] += 1
                    continue
            stats["без отметки"] += 1
            continue
        if choice == "counter" and text.strip():
            # наш текст ставим до применения решений: вставка контрагента сейчас будет убрана, привязаться будет не к чему
            body = [e for e in els if not _is_mark(e)]
            dels = [e for e in body if e.tag not in INSERTS]
            if body:
                max_id += 1
                ins = _our_insert(text, author, date, max_id)
                if dels:
                    dels[-1].addnext(ins)  # сразу после прежнего текста, который мы удаляем
                else:
                    body[0].addprevious(ins)  # на место вставки контрагента
        for e in els:
            _apply(e, choice, author, date)
        stats[choice] += 1

    def ser(root) -> bytes:
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    raw["word/document.xml"] = ser(doc_root)
    if comments_root is not None:
        raw["word/comments.xml"] = ser(comments_root)
    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, raw[name])
    return stats
