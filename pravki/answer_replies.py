"""Ответы на комментарии контрагента в ответе Word: ответ юриста — в той же ветке примечаний, от его имени.

Word связывает ответ с комментарием через часть commentsExtended.xml: у каждого абзаца примечания есть w14:paraId,
а запись w15:commentEx ответа указывает paraIdParent — последний абзац родительского комментария. Якорь ответа
в тексте — тот же, что у родителя (commentRangeStart / commentRangeEnd / commentReference рядом с родительскими).
Текст ответа пишет юрист; программа его не сочиняет.
"""
from __future__ import annotations

import secrets

from lxml import etree

from .docx_reader import XML_NS, q

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
EXT_PART = "word/commentsExtended.xml"
EXT_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
EXT_REL = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _para_id(used: set[str]) -> str:
    """Новый w14:paraId: 8 шестнадцатеричных цифр, меньше 0x80000000, не занятый в документе."""
    while True:
        pid = f"{secrets.randbelow(0x7FFFFFFF) + 1:08X}"
        if pid not in used:
            used.add(pid)
            return pid


MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def with_w14(comments_root):
    """Корень comments.xml с пространствами w14 и mc, как пишет сам Word: иначе paraId получает префикс ns0
    и Word не связывает ответ с комментарием. Возвращает новый корень (lxml не добавляет nsmap к готовому элементу)."""
    if comments_root.nsmap.get("w14") == W14:
        return comments_root
    nsmap = dict(comments_root.nsmap)
    nsmap.update({"w14": W14, "mc": MC})
    root = etree.Element(comments_root.tag, nsmap=nsmap, attrib=dict(comments_root.attrib))
    ign = f"{{{MC}}}Ignorable"
    root.set(ign, " ".join(sorted(set((comments_root.get(ign) or "").split()) | {"w14"})))
    for child in list(comments_root):
        root.append(child)
    return root


def _ensure_para_id(p, used: set[str]) -> str:
    pid = p.get(f"{{{W14}}}paraId")
    if not pid:
        pid = _para_id(used)
        p.set(f"{{{W14}}}paraId", pid)
    return pid


class Replies:
    """Добавляет ответы на комментарии в comments.xml, commentsExtended.xml и якоря в document.xml."""

    def __init__(self, doc_root, comments_root, ext_root, date: str):
        self.doc, self.comments, self.date = doc_root, comments_root, date
        if ext_root is None:
            ext_root = etree.Element(f"{{{W15}}}commentsEx", nsmap={"w15": W15, "mc": MC})
            ext_root.set(f"{{{MC}}}Ignorable", "w15")
        self.ext = ext_root
        self.used = {el.get(f"{{{W14}}}paraId") for root in (doc_root, comments_root) if root is not None
                     for el in root.iter(q("p")) if el.get(f"{{{W14}}}paraId")}
        ids = [int(c.get(q("id"))) for c in comments_root.findall(q("comment")) if (c.get(q("id")) or "").isdigit()]
        self.next_id = max(ids, default=0) + 1
        self.added = 0

    def _ext_for(self, pid: str):
        for e in self.ext.findall(f"{{{W15}}}commentEx"):
            if e.get(f"{{{W15}}}paraId") == pid:
                return e
        e = etree.SubElement(self.ext, f"{{{W15}}}commentEx")
        e.set(f"{{{W15}}}paraId", pid)
        e.set(f"{{{W15}}}done", "0")
        return e

    def reply(self, parent_id: str, text: str, author: str) -> bool:
        """Ответить на комментарий parent_id. False — такого комментария в файле нет."""
        parent = next((c for c in self.comments.findall(q("comment")) if c.get(q("id")) == parent_id), None)
        if parent is None or not text.strip():
            return False
        paras = parent.findall(q("p"))
        if not paras:
            return False
        parent_pid = _ensure_para_id(paras[-1], self.used)
        self._ext_for(parent_pid)

        cid = str(self.next_id)
        self.next_id += 1
        c = etree.SubElement(self.comments, q("comment"))
        for k, v in (("id", cid), ("author", author), ("date", self.date), ("initials", author[:1])):
            c.set(q(k), v)
        last = None
        for line in text.strip().split("\n"):
            last = etree.SubElement(c, q("p"))
            r = etree.SubElement(last, q("r"))
            t = etree.SubElement(r, q("t"))
            t.set(f"{{{XML_NS}}}space", "preserve")
            t.text = line
        ext = self._ext_for(_ensure_para_id(last, self.used))
        ext.set(f"{{{W15}}}paraIdParent", parent_pid)

        self._anchor(parent_id, cid)
        self.added += 1
        return True

    def _anchor(self, parent_id: str, cid: str) -> None:
        """Якорь ответа — рядом с якорем родителя: Word показывает их одной веткой."""
        def find(tag):
            return next((e for e in self.doc.iter(q(tag)) if e.get(q("id")) == parent_id), None)

        start, end, ref = find("commentRangeStart"), find("commentRangeEnd"), find("commentReference")
        if start is not None:
            s = etree.Element(q("commentRangeStart"))
            s.set(q("id"), cid)
            start.addnext(s)
        # порядок как у Word: …конец родителя, ссылка родителя, конец ответа, ссылка ответа
        after = ref.getparent() if ref is not None and ref.getparent() is not None else end
        e = etree.Element(q("commentRangeEnd"))
        e.set(q("id"), cid)
        r = etree.Element(q("r"))
        etree.SubElement(r, q("commentReference")).set(q("id"), cid)
        if after is not None:
            after.addnext(e)
            e.addnext(r)
        elif start is not None:
            start.getparent().append(e)
            start.getparent().append(r)

    def package(self, raw: dict, ct_root, rels_root) -> None:
        """Записать commentsExtended.xml и объявить его в [Content_Types].xml и связях документа."""
        if not self.added:
            return
        raw[EXT_PART] = etree.tostring(self.ext, xml_declaration=True, encoding="UTF-8", standalone=True)
        if not any(o.get("PartName") == "/" + EXT_PART for o in ct_root.findall(f"{{{CT_NS}}}Override")):
            o = etree.SubElement(ct_root, f"{{{CT_NS}}}Override")
            o.set("PartName", "/" + EXT_PART)
            o.set("ContentType", EXT_CT)
        rels = rels_root.findall(f"{{{REL_NS}}}Relationship")
        if not any(r.get("Type") == EXT_REL for r in rels):
            ids = {r.get("Id") for r in rels}
            k = 1
            while f"rIdPravkiExt{k}" in ids:
                k += 1
            rel = etree.SubElement(rels_root, f"{{{REL_NS}}}Relationship")
            rel.set("Id", f"rIdPravkiExt{k}")
            rel.set("Type", EXT_REL)
            rel.set("Target", "commentsExtended.xml")
