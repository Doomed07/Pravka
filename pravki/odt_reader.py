"""Чтение .odt (OpenDocument, LibreOffice): абзацы, отслеживаемые правки, комментарии, таблицы, нумерация списков.

Файл недоверенный: внешние сущности XML отключены, размер частей ограничен — как в read_docx. Перемещений в ODF нет:
перенесённый текст приходит как удаление и вставка. Удаление нескольких абзацев сразу читается одним удалённым текстом.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field

from .docx_reader import MAX_PART, DocxError, _fmt_num, _parser
from .model import Comment, DocxDoc, Paragraph, Segment
from .readers import finish_labels

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def q(name: str) -> str:
    prefix, local = name.split(":")
    return "{%s}%s" % (NS[prefix], local)


# «1», «a», «A», «i», «I» из style:num-format → формат нумерации, как в Word
_NUM_FORMATS = {"1": "decimal", "a": "lowerLetter", "A": "upperLetter", "i": "lowerRoman", "I": "upperRoman"}


@dataclass
class _Level:
    kind: str  # number | bullet
    fmt: str = "decimal"
    display: int = 1
    start: int = 1


@dataclass
class _ListState:
    style: str
    counters: list[int] = field(default_factory=lambda: [0] * 12)


def _read_part(zf: zipfile.ZipFile, name: str, required: bool = False):
    from lxml import etree

    try:
        info = zf.getinfo(name)
    except KeyError:
        if required:
            raise DocxError(f"в файле нет части {name}: это не odt или файл повреждён")
        return None
    if info.file_size > MAX_PART:
        raise DocxError(f"часть {name} слишком большая ({info.file_size} байт)")
    try:
        return etree.fromstring(zf.read(name), _parser())
    except etree.XMLSyntaxError as e:
        raise DocxError(f"часть {name} не читается: {e}")


def _style_name(raw: str) -> str:
    """«Heading_20_1» → «Heading 1»: в ODF пробелы в именах стилей записаны как _20_."""
    return re.sub(r"_([0-9a-fA-F]{2})_", lambda m: chr(int(m.group(1), 16)), raw or "")


def _read_styles(roots) -> tuple[dict[str, tuple[bool, bool]], dict[str, dict[int, _Level]]]:
    """Шрифт текстовых стилей (жирный, курсив) и уровни нумерации списков: имя стиля → {уровень: _Level}."""
    fonts: dict[str, tuple[bool, bool]] = {}
    lists: dict[str, dict[int, _Level]] = {}
    for root in roots:
        if root is None:
            continue
        for st in root.iter(q("style:style")):
            props = st.find(q("style:text-properties"))
            if props is not None:
                bold = props.get(q("fo:font-weight")) in ("bold", "700", "800", "900")
                italic = props.get(q("fo:font-style")) in ("italic", "oblique")
                fonts[st.get(q("style:name"), "")] = (bold, italic)
        for ls in root.iter(q("text:list-style")):
            levels: dict[int, _Level] = {}
            for lv in ls:
                try:
                    n = int(lv.get(q("text:level"), "1"))
                except ValueError:
                    continue
                if lv.tag == q("text:list-level-style-number"):
                    fmt = _NUM_FORMATS.get(lv.get(q("style:num-format"), "1"), "")
                    if not fmt:
                        levels[n] = _Level("bullet")  # num-format пустой: номера нет
                        continue
                    try:
                        display = max(1, int(lv.get(q("text:display-levels"), "1")))
                        start = int(lv.get(q("text:start-value"), "1"))
                    except ValueError:
                        display, start = 1, 1
                    levels[n] = _Level("number", fmt, display, start)
                elif lv.tag in (q("text:list-level-style-bullet"), q("text:list-level-style-image")):
                    levels[n] = _Level("bullet")
            lists[ls.get(q("style:name"), "")] = levels
    return fonts, lists


class _Reader:
    def __init__(self, body, changes, fonts, lists):
        self.changes = changes  # id → (вид, автор, дата, текст удалённого)
        self.fonts = fonts
        self.lists = lists
        self.paragraphs: list[Paragraph] = []
        self.comments: dict[str, Comment] = {}
        self.auto: dict[int, str] = {}
        self.anchors: dict[str, str] = {}
        self.open_changes: dict[str, str] = {}  # id открытой вставки → вид
        self.open_anchor: dict[str, list[str]] = {}
        self.table_count = 0
        self.table_pos: tuple = ()
        self.list_stack: list[tuple[str, int]] = []  # (стиль списка, уровень)
        self.list_state: dict[str, _ListState] = {}
        self.pending_label: tuple[str, str] | None = None  # метка первого абзаца пункта списка (вид, текст)
        self.list_kind = ""
        self.list_level = 0
        self.comment_seq = 0
        self.walk_block(body)

    # ---------- блоки ----------
    def walk_block(self, node):
        for el in node:
            tag = el.tag
            if tag in (q("text:p"), q("text:h")):
                self.paragraph(el)
            elif tag == q("text:list"):
                self.list_block(el)
            elif tag == q("table:table"):
                self.table(el)
            elif tag in (q("text:section"), q("text:index-body"), q("text:table-of-content")):
                self.walk_block(el)

    def table(self, tbl):
        if self.table_pos:  # вложенная таблица: её абзацы относим к ячейке внешней
            self.walk_rows(tbl, None)
            return
        tid = self.table_count
        self.table_count += 1
        self.walk_rows(tbl, tid)

    def walk_rows(self, tbl, tid):
        rows = [r for r in tbl.iter(q("table:table-row"))]
        for ri, row in enumerate(rows):
            col = 0
            for cell in row:
                if cell.tag not in (q("table:table-cell"), q("table:covered-table-cell")):
                    continue
                try:
                    span = max(1, int(cell.get(q("table:number-columns-spanned"), "1")))
                except ValueError:
                    span = 1
                try:
                    repeated = max(1, int(cell.get(q("table:number-columns-repeated"), "1")))
                except ValueError:
                    repeated = 1
                if tid is not None and cell.tag == q("table:table-cell"):
                    self.table_pos = (tid, ri, col, span)
                    self.walk_block(cell)
                    self.table_pos = ()
                col += repeated  # объединённые ячейки в ODF идут следом как table:covered-table-cell: каждая занимает свой столбец

    def list_block(self, lst):
        style = lst.get(q("text:style-name")) or (self.list_stack[-1][0] if self.list_stack else "")
        level = len(self.list_stack) + 1
        if level == 1:
            keep = lst.get(q("text:continue-numbering")) == "true" or lst.get(q("text:continue-list")) is not None
            if not keep or style not in self.list_state:
                self.list_state[style] = _ListState(style)
        self.list_stack.append((style, level))
        for item in lst:
            if item.tag == q("text:list-header"):
                self.pending_label = None
                self.walk_block(item)
            elif item.tag == q("text:list-item"):
                st = self.list_state[self.list_stack[0][0]]
                levels = self.lists.get(style, {})
                lv = levels.get(level, _Level("number"))
                if lv.kind == "bullet":
                    self.pending_label = ("bullet", "")
                else:
                    try:
                        value = int(item.get(q("text:start-value")) or 0)
                    except ValueError:
                        value = 0
                    st.counters[level - 1] = value or (st.counters[level - 1] + 1 if st.counters[level - 1] else lv.start)
                    for deeper in range(level, len(st.counters)):
                        st.counters[deeper] = 0
                    parts = []
                    for n in range(max(1, level - lv.display + 1), level + 1):
                        cl = levels.get(n, _Level("number"))
                        parts.append(_fmt_num(max(st.counters[n - 1], 1), cl.fmt))
                    self.pending_label = ("number", ".".join(parts))
                self.list_kind, self.list_level = self.pending_label[0], level - 1
                self.walk_block(item)
                self.pending_label = None
                self.list_kind, self.list_level = "", 0
        self.list_stack.pop()

    # ---------- абзац ----------
    def paragraph(self, p):
        idx = len(self.paragraphs)
        para = Paragraph(index=idx)
        style = _style_name(p.get(q("text:style-name"), ""))
        para.style = "Heading" if p.tag == q("text:h") and not style else style
        if self.table_pos:
            para.in_table, para.table = True, self.table_pos
        if self.pending_label is not None:
            para.list_kind, para.level = self.list_kind, self.list_level
            if self.pending_label[1]:
                self.auto[idx] = self.pending_label[1]
            self.pending_label = None
        self.segments: list[Segment] = []
        self.para = para
        self.inline(p, (False, False))
        para.segments = self.segments
        self.paragraphs.append(para)

    def emit(self, text: str, font=(False, False)):
        if not text:
            return
        for anchor in self.open_anchor.values():
            anchor.append(text)
        kind, author, date, rev = "equal", "", "", ""
        if self.open_changes:
            cid = next(reversed(self.open_changes))
            _, author, date, _ = self.changes.get(cid, ("ins", "", "", ""))
            kind, rev = "ins", cid
        self.add(kind, text, author, date, rev, font)

    def add(self, kind, text, author, date, rev, font):
        s = self.segments
        if s and (s[-1].kind, s[-1].author, s[-1].rev, s[-1].bold, s[-1].italic) == (kind, author, rev, font[0], font[1]):
            s[-1].text += text
        else:
            s.append(Segment(kind=kind, text=text, author=author, date=date, rev=rev, bold=font[0], italic=font[1]))

    def inline(self, node, font):
        self.emit(node.text or "", font)
        for ch in node:
            tag = ch.tag
            if tag in (q("text:span"), q("text:a"), q("text:meta"), q("text:ruby"), q("text:ruby-base")):
                f = self.fonts.get(ch.get(q("text:style-name"), ""), (False, False))
                self.inline(ch, (font[0] or f[0], font[1] or f[1]))
            elif tag == q("text:s"):
                try:
                    self.emit(" " * max(1, int(ch.get(q("text:c"), "1"))), font)
                except ValueError:
                    self.emit(" ", font)
            elif tag == q("text:tab"):
                self.emit("\t", font)
            elif tag == q("text:line-break"):
                self.emit("\n", font)
            elif tag == q("text:change-start"):
                cid = ch.get(q("text:change-id"), "")
                kind = self.changes.get(cid, ("", "", "", ""))[0]
                if kind == "ins":
                    self.open_changes[cid] = "ins"
            elif tag == q("text:change-end"):
                self.open_changes.pop(ch.get(q("text:change-id"), ""), None)
            elif tag == q("text:change"):
                kind, author, date, deleted = self.changes.get(ch.get(q("text:change-id"), ""), ("", "", "", ""))
                if kind == "del" and deleted:  # удалённый текст в якорь комментария не входит
                    self.add("del", deleted, author, date, ch.get(q("text:change-id"), ""), font)
            elif tag == q("office:annotation"):
                self.annotation(ch)
            elif tag == q("office:annotation-end"):
                name = ch.get(q("office:name"), "")
                if name in self.open_anchor:
                    self.anchors[name] = "".join(self.open_anchor.pop(name))
            elif tag in (q("text:note"), q("text:bookmark"), q("text:bookmark-start"), q("text:bookmark-end"),
                         q("text:soft-page-break")):
                pass
            else:
                self.inline(ch, font)
            self.emit(ch.tail or "", font)

    def annotation(self, ann):
        self.comment_seq += 1
        name = ann.get(q("office:name"), "") or f"c{self.comment_seq}"
        author = (ann.findtext(q("dc:creator")) or "").strip()
        date = (ann.findtext(q("dc:date")) or "").strip()
        paras = ["".join(t for t in p.itertext()) for p in ann.iter(q("text:p"))]
        self.comments[name] = Comment(id=name, author=author, date=date, text="\n".join(paras).strip(),
                                      paragraph_index=self.para.index)
        self.para.comment_ids.append(name)
        self.open_anchor[name] = []


def _tracked_changes(root) -> dict[str, tuple[str, str, str, str]]:
    """id правки → (вид: ins | del, автор, дата, текст удалённого)."""
    out = {}
    for region in root.iter(q("text:changed-region")):
        cid = region.get(q("text:id"), "") or region.get(q("xml:id"), "")
        for kind, tag in (("ins", "text:insertion"), ("del", "text:deletion")):
            el = region.find(q(tag))
            if el is None:
                continue
            info = el.find(q("office:change-info"))
            author = (info.findtext(q("dc:creator")) or "").strip() if info is not None else ""
            date = (info.findtext(q("dc:date")) or "").strip() if info is not None else ""
            deleted = ""
            if kind == "del":
                deleted = "\n".join("".join(p.itertext()) for p in el if p.tag in (q("text:p"), q("text:h"))).strip("\n")
            out[cid] = (kind, author, date, deleted)
    return out


def read_odt(path: str) -> DocxDoc:
    try:
        zf = zipfile.ZipFile(path)
    except FileNotFoundError:
        raise DocxError(f"файл не найден: {path}")
    except (zipfile.BadZipFile, IsADirectoryError, PermissionError) as e:
        raise DocxError(f"не удалось открыть {path}: это не odt или файл повреждён ({e.__class__.__name__})")
    with zf:
        if len(zf.namelist()) > 5000:
            raise DocxError("в архиве слишком много частей")
        content = _read_part(zf, "content.xml", required=True)
        styles = _read_part(zf, "styles.xml")
    text = content.find(".//" + q("office:text"))
    if text is None:
        raise DocxError("в content.xml нет текста документа")
    fonts, lists = _read_styles([styles, content])
    rd = _Reader(text, _tracked_changes(text), fonts, lists)
    finish_labels(rd.paragraphs, rd.auto)
    for name, comment in rd.comments.items():
        comment.anchor = (rd.anchors.get(name, "") or "")[:500]
    authors = Counter()
    for para in rd.paragraphs:
        for s in para.segments:
            if s.kind != "equal" and s.author:
                authors[s.author] += 1
    for c in rd.comments.values():
        if c.author:
            authors[c.author] += 1
    return DocxDoc(path=path, paragraphs=rd.paragraphs, comments=rd.comments, authors=[a for a, _ in authors.most_common()],
                   format="odt")
