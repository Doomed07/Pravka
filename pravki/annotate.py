"""Единая версия договора в Word: файл контрагента с его правками в рецензировании плюс наши примечания.

Текст и правки контрагента не меняются. К каждому абзацу с правкой добавляется примечание Word от автора
ANNOTATOR: решение по плейбуку, правило, пояснение (с пометкой, если его написала модель), наша позиция.
Правки без отметки в рецензировании описываются в примечании («было → стало»). В конце документа — дисклеймер
вставкой в рецензировании того же автора, чтобы его было видно и можно было отклонить одной кнопкой.

Автор ANNOTATOR всегда считается нашим (compare.resolve_ours): если файл уйдёт дальше и вернётся, наши
примечания и дисклеймер не попадут в отчёт как правки контрагента.
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone

from lxml import etree

from .docx_reader import W as W_NS, XML_NS, DocxError, _in_fallback, _read_part, q
from .model import ANNOTATOR, Change

DISCLAIMER = "Черновик — требует вашей проверки перед отправкой (draft — needs your review before sending)."

COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def comment_lines(ch: Change) -> list[str]:
    """Текст примечания к правке, по строкам."""
    head = ch.action or "Правка контрагента"
    if ch.rule_id and ch.rule_id != "PARTY":
        head += f" · правило {ch.rule_id}"
    lines = [f"{ch.id} · {head}"]
    if ch.detail.get("accepted_from_base"):
        lines.append(f"Принята правка из нашей версии: было «{ch.before or '—'}» → стало «{ch.after or '—'}».")
    elif ch.source in ("silent", "diff"):
        lines.append(f"Изменено без отметки в рецензировании: было «{ch.before or '—'}» → стало «{ch.after or '—'}».")
    if ch.explanation:
        lines.append(("Пояснение ИИ: " if "template_explanation" in ch.detail else "Пояснение: ") + ch.explanation)
    if ch.suggested:
        lines.append(f"Наша позиция: {ch.suggested}")
    if ch.escalate_to:
        lines.append(f"Согласовать: {ch.escalate_to}")
    return lines


def _t(text: str):
    t = etree.Element(q("t"))
    t.set(f"{{{XML_NS}}}space", "preserve")
    t.text = text
    return t


def _comment(cid: int, lines: list[str], date: str):
    c = etree.Element(q("comment"))
    c.set(q("id"), str(cid))
    c.set(q("author"), ANNOTATOR)
    c.set(q("date"), date)
    c.set(q("initials"), "П")
    for line in lines:
        p = etree.SubElement(c, q("p"))
        r = etree.SubElement(p, q("r"))
        r.append(_t(line))
    return c


def _anchor(p, cid: int) -> None:
    start = etree.Element(q("commentRangeStart"))
    start.set(q("id"), str(cid))
    ppr = p.find(q("pPr"))
    p.insert(p.index(ppr) + 1 if ppr is not None else 0, start)
    end = etree.SubElement(p, q("commentRangeEnd"))
    end.set(q("id"), str(cid))
    r = etree.SubElement(p, q("r"))
    ref = etree.SubElement(r, q("commentReference"))
    ref.set(q("id"), str(cid))


def _disclaimer(body, date: str) -> None:
    p = etree.Element(q("p"))
    ppr = etree.SubElement(p, q("pPr"))
    rpr = etree.SubElement(ppr, q("rPr"))
    mark = etree.SubElement(rpr, q("ins"))
    for k, v in (("id", "990001"), ("author", ANNOTATOR), ("date", date)):
        mark.set(q(k), v)
    ins = etree.SubElement(p, q("ins"))
    for k, v in (("id", "990002"), ("author", ANNOTATOR), ("date", date)):
        ins.set(q(k), v)
    r = etree.SubElement(ins, q("r"))
    r.append(_t(DISCLAIMER))
    sect = body.find(q("sectPr"))
    if sect is not None:
        sect.addprevious(p)
    else:
        body.append(p)


def _targets(changes: list[Change], document: list[dict], n_paras: int) -> list[tuple[int, Change]]:
    """К какому абзацу (по номеру в файле контрагента) привязать примечание каждой правки."""
    where: dict[str, int] = {}
    prev = -1
    for para in document:
        if para["index"] >= 0:
            prev = para["index"]
        for cid in para["changes"]:
            # абзац, удалённый без отметки, есть только в нашей версии: примечание — к абзацу перед ним
            where.setdefault(cid, para["index"] if para["index"] >= 0 else max(prev, 0))
    out = []
    for ch in changes:
        idx = where.get(ch.id, ch.paragraph_index)
        if not 0 <= idx < n_paras:
            idx = 0  # стороны и реквизиты, правки без места в тексте — к началу договора
        out.append((idx, ch))
    return out


def annotate_docx(theirs_path: str, out_path: str, changes: list[Change], document: list[dict]) -> int:
    """Записать единую версию в out_path. Возвращает число добавленных примечаний."""
    try:
        zin = zipfile.ZipFile(theirs_path)
    except (OSError, zipfile.BadZipFile) as e:
        raise DocxError(f"не удалось открыть {theirs_path}: {e.__class__.__name__}")
    with zin:
        names = zin.namelist()
        doc_root = _read_part(zin, "word/document.xml", required=True)
        comments_root = _read_part(zin, "word/comments.xml")
        ct_root = _read_part(zin, "[Content_Types].xml", required=True)
        rels_root = _read_part(zin, "word/_rels/document.xml.rels")
        raw = {n: zin.read(n) for n in names}

    body = doc_root.find(q("body"))
    if body is None:
        raise DocxError("в document.xml нет тела документа")
    paras = [p for p in body.iter(q("p")) if not _in_fallback(p)]  # тот же порядок, что в read_docx

    if comments_root is None:
        comments_root = etree.Element(q("comments"), nsmap={"w": W_NS})
    used = [int(c.get(q("id"))) for c in comments_root.findall(q("comment")) if (c.get(q("id")) or "").isdigit()]
    next_id = max(used, default=0) + 1
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for idx, ch in _targets(changes, document, len(paras)):
        if not paras:
            break
        comments_root.append(_comment(next_id, comment_lines(ch), date))
        _anchor(paras[idx], next_id)
        next_id += 1
        n += 1
    _disclaimer(body, date)

    if not any(o.get("PartName") == "/word/comments.xml" for o in ct_root.findall(f"{{{CT_NS}}}Override")):
        o = etree.SubElement(ct_root, f"{{{CT_NS}}}Override")
        o.set("PartName", "/word/comments.xml")
        o.set("ContentType", COMMENTS_CT)
    if rels_root is None:
        rels_root = etree.Element(f"{{{REL_NS}}}Relationships", nsmap={None: REL_NS})
    rels = rels_root.findall(f"{{{REL_NS}}}Relationship")
    if not any(r.get("Type") == COMMENTS_REL for r in rels):
        ids = {r.get("Id") for r in rels}
        k = 1
        while f"rIdPravki{k}" in ids:
            k += 1
        rel = etree.SubElement(rels_root, f"{{{REL_NS}}}Relationship")
        rel.set("Id", f"rIdPravki{k}")
        rel.set("Type", COMMENTS_REL)
        rel.set("Target", "comments.xml")

    def ser(root) -> bytes:
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    raw["word/document.xml"] = ser(doc_root)
    raw["word/comments.xml"] = ser(comments_root)
    raw["[Content_Types].xml"] = ser(ct_root)
    raw["word/_rels/document.xml.rels"] = ser(rels_root)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        order = names + [x for x in raw if x not in names]
        for name in order:
            zout.writestr(name, raw[name])
    return n
