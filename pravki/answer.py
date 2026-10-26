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
нашей правкой в рецензировании (`answer_silent`). reply — ответ юриста на комментарий контрагента в той же ветке
примечаний (`answer_replies`).
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime, timezone

from lxml import etree

from .docx_reader import XML_NS, DocxError, _read_part, q
from .answer_replies import EXT_PART, REL_NS, Replies, with_w14
from .answer_silent import Writer, _explode, _nodes, _unique, apply_edit, apply_silent, collapse_spaces, delete_paragraph, delete_row, insert_paragraphs_after, insert_row_after, paragraphs, remove_dots, row_of
from .model import ANNOTATOR
from .unified import mark_extra_spaces

TRACKED = {q("ins"), q("del"), q("moveFrom"), q("moveTo")}
INSERTS = {q("ins"), q("moveTo")}
CHOICES = ("accept", "reject", "counter")
EDIT = "edit"  # правка текста абзаца на сайте
REPLY = "reply"  # ответ на комментарий контрагента (answer_replies)


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


def _merge_with_next(p) -> None:
    """Принятое удаление знака абзаца: текст абзаца переходит в начало следующего, как делает Word (у склеенного абзаца
    вид и нумерация следующего). Следующего абзаца нет (таблица, конец раздела) — абзац остаётся как есть."""
    nxt = p.getnext()
    if nxt is None or nxt.tag != q("p"):
        return
    anchor = nxt.find(q("pPr"))
    pos = list(nxt).index(anchor) + 1 if anchor is not None else 0
    for child in [c for c in p if c.tag != q("pPr")]:
        nxt.insert(pos, child)
        pos += 1
    p.getparent().remove(p)


def _apply(el, choice: str, author: str, date: str) -> None:
    if _is_mark(el):
        inserted = el.tag == q("ins")
        p = el.getparent().getparent().getparent()
        # принять удаление знака или отклонить вставку: пустой абзац исчезает; абзац с текстом при принятом
        # удалении знака склеивается со следующим, при отклонённой вставке — снимаем только метку
        _drop_mark(el, remove_empty_paragraph=(choice == "accept") != inserted)
        if choice == "accept" and not inserted and p is not None and p.getparent() is not None and _has_text(p):
            _merge_with_next(p)
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


CLAUSE_REJECT = "Не согласны с этим положением."


def _add_comment(comments_root, p, text: str, author: str, date: str, last_id: int) -> int:
    """Примечание юриста к абзацу p; возвращает его номер."""
    cid = last_id + 1
    c = etree.SubElement(comments_root, q("comment"))
    for k, v in (("id", str(cid)), ("author", author), ("date", date), ("initials", author[:1].upper())):
        c.set(q(k), v)
    for line in text.splitlines() or [text]:
        r = etree.SubElement(etree.SubElement(c, q("p")), q("r"))
        t = etree.SubElement(r, q("t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = line
    start = etree.Element(q("commentRangeStart"))
    start.set(q("id"), str(cid))
    ppr = p.find(q("pPr"))
    p.insert(p.index(ppr) + 1 if ppr is not None else 0, start)
    end = etree.SubElement(p, q("commentRangeEnd"))
    end.set(q("id"), str(cid))
    ref = etree.SubElement(etree.SubElement(p, q("r")), q("commentReference"))
    ref.set(q("id"), str(cid))
    return cid


def _inserts_inside(els: list) -> list:
    """Чужие вставки внутри отклоняемой вставки контрагента: наш юрист уже поправил её прямо в файле («8» → «12»).
    Без вставки контрагента правка поверх неё теряет смысл и остаётся обрывком («…2026 12.»), поэтому уходит вместе с ней."""
    ins = [e for e in els if e.tag in INSERTS]
    if len(ins) < 2:
        return []
    para = next((a for a in ins[0].iterancestors() if a.tag == q("p")), None)
    if para is None or any(next((a for a in e.iterancestors() if a.tag == q("p")), None) is not para for e in ins):
        return []
    order = {e: n for n, e in enumerate(para.iter())}
    first, last = min(order[e] for e in ins), max(order[e] for e in ins)
    mine = set(els)
    return [e for e in para.iter(*INSERTS) if first < order[e] < last and e not in mine
            and not any(a in mine for a in e.iterancestors())]


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
        ext_root = _read_part(zin, EXT_PART)
        ct_root = _read_part(zin, "[Content_Types].xml", required=True)
        rels_root = _read_part(zin, "word/_rels/document.xml.rels")
        raw = {n: zin.read(n) for n in names}

    stats = {"accept": 0, "reject": 0, "counter": 0, "reply": 0, "edit": 0, "join": 0, "spaces": 0, "dots": 0, "delete": 0, "add": 0, "comment": 0, "rows_deleted": 0, "rows_added": 0, "без отметки": 0, "наших примечаний убрано": 0}
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
    if comments_root is not None:
        comments_root = with_w14(comments_root)  # ответы в ветке: w14:paraId с объявленным пространством имён
    max_cid = max([int(c.get(q("id"))) for c in comments_root.findall(q("comment")) if (c.get(q("id")) or "").isdigit()],
                  default=0) if comments_root is not None else 0
    replies = Replies(doc_root, comments_root, ext_root, date) if comments_root is not None else None

    joins = {d["index"] for d in document or [] if d.get("join_next") and 0 <= d["index"] + 1 < len(paras)
             and (choices.get(f"J{d['index']:03d}") or {}).get("choice") != "reject"}

    # абзацы, удалённые юристом на сайте (X<абзац>, reject): другие правки в них не делаются. Склеенный абзац удаляется
    # обеими частями, склейка в этом случае не нужна
    gone = {i for i in range(len(paras)) if (choices.get(f"X{i:03d}") or {}).get("choice") == "reject"}
    removed = gone | {i + 1 for i in gone if i in joins}
    joins -= gone
    # строки таблиц, удалённые юристом (R<первый абзац строки>, reject): в их абзацах другие правки не делаются
    at = {id(p): i for i, p in enumerate(paras)}
    dead_rows = []
    for key, sel in choices.items():
        if key.startswith("R") and key[1:].isdigit() and sel.get("choice") == "reject" and int(key[1:]) < len(paras):
            tr = row_of(paras[int(key[1:])])
            if tr is not None and tr not in dead_rows:
                dead_rows.append(tr)
    in_dead = {at[id(p)] for tr in dead_rows for p in tr.iter(q("p")) if id(p) in at}
    removed |= in_dead

    for ch in changes:
        sel = choices.get(ch.get("id", "")) or {}
        choice = sel.get("choice", "")
        if ch.get("kind") == "comment":
            if choice == REPLY and replies is not None and replies.reply(ch.get("comment_id", ""), sel.get("text") or "", author):
                stats["reply"] += 1
            continue
        if choice not in CHOICES:
            continue
        if ch.get("source") == "clause":
            # положение первой версии: текста контрагента в рецензировании нет, ответ юриста — примечание к абзацу
            note = (sel.get("text") or "").strip() or (CLAUSE_REJECT if choice == "reject" else "")
            idx = ch.get("paragraph_index", -1)
            if idx - 1 in joins:
                idx -= 1  # абзац склеен с предыдущим: примечание — к склеенному, второй абзац удаляется
            if choice == "accept":
                stats["accept"] += 1
            elif note and comments_root is not None and 0 <= idx < len(paras):
                max_cid = _add_comment(comments_root, paras[idx], note, author, date, max_cid)
                stats[choice] += 1
            else:
                stats["без отметки"] += 1
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
        if choice in ("reject", "counter"):
            els += _inserts_inside(els)
        for e in els:
            _apply(e, choice, author, date)
        stats[choice] += 1

    # лишние пробелы внутри абзаца: серия сокращается до одного пробела нашей правкой. Абзацы, которые юрист правил сам, пропускаются: там
    # пробелы убирает его правка; вторая часть склеенного абзаца удаляется целиком. Делается до правок и склейки: у абзаца
    # с нашими вставками и удалениями серии пробелов уже не найти.
    mark_extra_spaces(document or [])  # пометки считаются заново: работает и для разборов, сделанных до этой правки
    for para in document or []:
        idx = para.get("index", -1)
        if not para.get("extra_spaces") or idx - 1 in joins or idx in removed or not 0 <= idx < len(paras):
            continue
        if (choices.get(f"P{idx:03d}") or {}).get("choice") == EDIT:
            continue
        writer = Writer(author, date, max_id)
        if collapse_spaces(paras[idx], writer):
            max_id = writer.max_id
            stats["spaces"] += 1

    # правки текста абзацев, сделанные юристом на сайте: choices["P<номер абзаца>"] = {"choice": "edit", "text": ...}
    for key, sel in choices.items():
        if not (key.startswith("P") and sel.get("choice") == EDIT):
            continue
        idx = int(key[1:]) if key[1:].isdigit() else -1
        if idx in joins or idx in removed:
            continue  # склеенный абзац правится вместе со второй частью (ниже)
        writer = Writer(author, date, max_id)
        if 0 <= idx < len(paras) and (sel.get("text") or "").strip() and apply_edit(paras[idx], sel["text"], writer):
            stats["edit"] += 1
            max_id = writer.max_id
        else:
            stats["без отметки"] += 1

    # склеенные абзацы: предложение разорвано в файле контрагента. Текст второго абзаца вставляется в конец первого нашей
    # правкой, а сам второй абзац удаляется: нумерация и вид первого остаются (при удалении знака абзаца Word
    # оставил бы вид второго).
    for idx in sorted(joins):
        writer = Writer(author, date, max_id)
        head, rest = paras[idx], paras[idx + 1]
        _explode(head)
        _explode(rest)
        tail = "".join(t for _, _, t in _nodes(rest))
        last, runs = _nodes(head), _unique([r for r, _, t in _nodes(rest) if t])
        if not last or not runs or not tail.strip():
            stats["без отметки"] += 1
            continue
        mine = choices.get(f"P{idx:03d}") or {}
        if mine.get("choice") == EDIT and (mine.get("text") or "").strip():
            # юрист правил склеенный абзац: новый текст целиком сравнивается с первой частью, всё, чего в ней нет
            # (вторая часть с правками), вставляется в её конец; сама вторая часть удаляется
            if not apply_edit(head, mine["text"], writer):
                stats["без отметки"] += 1
                continue
            stats["edit"] += 1
        else:
            body = "".join(t for _, _, t in last)
            glue = next((d.get("join_glue") for d in document or [] if d.get("index") == idx), False)
            writer.insert_after(last[-1][0], ("" if glue or body.endswith(" ") else " ") + tail.strip(), last[-1][0])
        writer.delete_runs(runs)
        writer.mark_paragraph(rest, "del")
        max_id = writer.max_id
        stats["join"] += 1

    # точки посреди предложения: флаг stray_dots поставлен при разборе (по нему сайт показывает то же место); юрист мог
    # отказаться (решение reject у D<абзац>) или править абзац сам
    for para in document or []:
        idx = para.get("index", -1)
        if not para.get("stray_dots") or idx in joins or idx - 1 in joins or idx in removed or not 0 <= idx < len(paras):
            continue
        if (choices.get(f"P{idx:03d}") or {}).get("choice") == EDIT or (choices.get(f"D{idx:03d}") or {}).get("choice") == "reject":
            continue
        writer = Writer(author, date, max_id)
        if remove_dots(paras[idx], writer):
            max_id = writer.max_id
            stats["dots"] += 1

    # удаление абзацев и новые абзацы, сделанные юристом на сайте
    for idx in sorted(removed - in_dead):
        writer = Writer(author, date, max_id)
        if delete_paragraph(paras[idx], writer):
            stats["delete"] += 1
            max_id = writer.max_id
        else:
            stats["без отметки"] += 1
    for key, sel in sorted(choices.items()):
        if not (key.startswith("A") and key[1:].isdigit() and sel.get("choice") == EDIT and (sel.get("text") or "").strip()):
            continue
        idx = int(key[1:])
        idx = idx + 1 if idx in joins else idx  # у склеенного абзаца новый идёт после второй части
        if not 0 <= idx < len(paras):
            stats["без отметки"] += 1
            continue
        writer = Writer(author, date, max_id)
        stats["add"] += insert_paragraphs_after(paras[idx], sel["text"], writer)
        max_id = writer.max_id

    # строки таблиц: удаление и новая строка после (N<первый абзац строки>, edit: ячейки через табуляцию)
    for tr in dead_rows:
        writer = Writer(author, date, max_id)
        if delete_row(tr, writer):
            stats["rows_deleted"] += 1
            max_id = writer.max_id
        else:
            stats["без отметки"] += 1
    for key, sel in sorted(choices.items()):
        if not (key.startswith("N") and key[1:].isdigit() and sel.get("choice") == EDIT and (sel.get("text") or "").strip()):
            continue
        tr = row_of(paras[int(key[1:])]) if int(key[1:]) < len(paras) else None
        writer = Writer(author, date, max_id)
        if tr is not None and insert_row_after(tr, sel["text"].split("\t"), writer):
            stats["rows_added"] += 1
            max_id = writer.max_id
        else:
            stats["без отметки"] += 1

    # комментарии юриста к абзацам (C<абзац>): примечание Word от его имени, в том числе к удалённому абзацу — обоснование
    for key, sel in sorted(choices.items()):
        if not (key.startswith("C") and key[1:].isdigit() and sel.get("choice") == EDIT and (sel.get("text") or "").strip()):
            continue
        idx = int(key[1:])
        text = sel["text"].strip()
        if idx in removed and 0 <= idx < len(paras):
            # примечание к удалённому абзацу Word может не показать (текст зачёркнут, знак абзаца удалён): крепим его к
            # ближайшему оставшемуся абзацу, а в тексте называем, о каком пункте речь
            quote = " ".join(re.sub(r"\s+", " ", "".join(t.text or "" for t in paras[idx].iter(q("t"), q("delText")))).split())
            text = f"К удалённому пункту «{quote[:80]}{'…' if len(quote) > 80 else ''}»: {text}"
            keep = [i for i in range(idx + 1, len(paras)) if i not in removed] or [i for i in range(idx - 1, -1, -1) if i not in removed]
            idx = keep[0] if keep else idx
        if comments_root is not None and 0 <= idx < len(paras):
            max_cid = _add_comment(comments_root, paras[idx], text, author, date, max_cid)
            stats["comment"] += 1
        else:
            stats["без отметки"] += 1

    def ser(root) -> bytes:
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    if replies is not None and replies.added:
        if rels_root is None:
            rels_root = etree.Element(f"{{{REL_NS}}}Relationships", nsmap={None: REL_NS})
        replies.package(raw, ct_root, rels_root)
        raw["[Content_Types].xml"] = ser(ct_root)
        raw["word/_rels/document.xml.rels"] = ser(rels_root)
    raw["word/document.xml"] = ser(doc_root)
    if comments_root is not None:
        raw["word/comments.xml"] = ser(comments_root)
    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names + [n for n in raw if n not in names]:
            zout.writestr(name, raw[name])
    return stats
