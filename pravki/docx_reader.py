"""Чтение docx: абзацы с отслеживаемыми правками, комментарии, автонумерация.

Читается только word/document.xml и сопутствующие части (numbering, styles, comments).
Файл считается недоверенным: внешние сущности XML отключены, размер частей ограничен.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter

from lxml import etree

from .model import ANNOTATOR, Comment, DocxDoc, Paragraph, Segment

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MAX_PART = 64 * 1024 * 1024


class DocxError(Exception):
    pass


def q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


def _read_part(zf: zipfile.ZipFile, name: str, required: bool = False):
    try:
        info = zf.getinfo(name)
    except KeyError:
        if required:
            raise DocxError(f"в файле нет части {name}: это не docx или файл повреждён")
        return None
    if info.file_size > MAX_PART:
        raise DocxError(f"часть {name} слишком большая ({info.file_size} байт)")
    try:
        return etree.fromstring(zf.read(name), _parser())
    except etree.XMLSyntaxError as e:
        raise DocxError(f"часть {name} не читается: {e}")


# --------------------------------------------------------------------------------------
# Нумерация
# --------------------------------------------------------------------------------------
_RU_LOWER = "абвгдежзиклмнопрстуфхцчшщэюя"


def _fmt_num(n: int, fmt: str) -> str:
    if fmt in ("decimal", "decimalZero"):
        return str(n)
    if fmt == "lowerLetter":
        return chr(96 + ((n - 1) % 26) + 1)
    if fmt == "upperLetter":
        return chr(64 + ((n - 1) % 26) + 1)
    if fmt == "russianLower":
        return _RU_LOWER[(n - 1) % len(_RU_LOWER)]
    if fmt == "russianUpper":
        return _RU_LOWER[(n - 1) % len(_RU_LOWER)].upper()
    if fmt in ("lowerRoman", "upperRoman"):
        vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
        out, x = "", n
        for v, s in vals:
            while x >= v:
                out += s
                x -= v
        return out.upper() if fmt == "upperRoman" else out
    return str(n)


class Numbering:
    def __init__(self, num_root, styles_root):
        self.abstract: dict[str, dict[int, dict]] = {}
        self.num_to_abs: dict[str, str] = {}
        self.overrides: dict[str, dict[int, int]] = {}
        self.counters: dict[str, list[int | None]] = {}
        self.seen_num: set[str] = set()
        self.style_num: dict[str, tuple[str | None, int | None]] = {}
        self.style_based: dict[str, str] = {}
        self.style_names: dict[str, str] = {}
        if num_root is not None:
            self._load_numbering(num_root)
        if styles_root is not None:
            self._load_styles(styles_root)

    def _load_numbering(self, root):
        for an in root.findall(q("abstractNum")):
            aid = an.get(q("abstractNumId"))
            levels = {}
            for lvl in an.findall(q("lvl")):
                il = int(lvl.get(q("ilvl"), "0"))
                start = lvl.find(q("start"))
                fmt = lvl.find(q("numFmt"))
                txt = lvl.find(q("lvlText"))
                levels[il] = {
                    "start": int(start.get(q("val"), "1")) if start is not None else 1,
                    "fmt": fmt.get(q("val"), "decimal") if fmt is not None else "decimal",
                    "text": txt.get(q("val"), "") if txt is not None else "",
                }
            self.abstract[aid] = levels
        for num in root.findall(q("num")):
            nid = num.get(q("numId"))
            ref = num.find(q("abstractNumId"))
            if ref is not None:
                self.num_to_abs[nid] = ref.get(q("val"))
            ov = {}
            for lo in num.findall(q("lvlOverride")):
                so = lo.find(q("startOverride"))
                if so is not None:
                    ov[int(lo.get(q("ilvl"), "0"))] = int(so.get(q("val"), "1"))
            if ov:
                self.overrides[nid] = ov

    def _load_styles(self, root):
        for st in root.findall(q("style")):
            sid = st.get(q("styleId"))
            name = st.find(q("name"))
            if name is not None:
                self.style_names[sid] = name.get(q("val"), "")
            based = st.find(q("basedOn"))
            if based is not None:
                self.style_based[sid] = based.get(q("val"))
            numpr = st.find(f"{q('pPr')}/{q('numPr')}")
            if numpr is not None:
                nid = numpr.find(q("numId"))
                il = numpr.find(q("ilvl"))
                self.style_num[sid] = (
                    nid.get(q("val")) if nid is not None else None,
                    int(il.get(q("val"))) if il is not None else None,
                )

    def style_name(self, sid: str) -> str:
        return self.style_names.get(sid, sid or "")

    def _style_numpr(self, sid: str, depth: int = 0):
        if not sid or depth > 8:
            return None
        if sid in self.style_num:
            return self.style_num[sid]
        return self._style_numpr(self.style_based.get(sid, ""), depth + 1)

    def label_for(self, ppr, style_id: str) -> str:
        num_id = ilvl = None
        if ppr is not None:
            numpr = ppr.find(q("numPr"))
            if numpr is not None:
                n = numpr.find(q("numId"))
                i = numpr.find(q("ilvl"))
                num_id = n.get(q("val")) if n is not None else None
                ilvl = int(i.get(q("val"))) if i is not None else None
        if num_id is None:
            sn = self._style_numpr(style_id)
            if sn:
                num_id, ilvl = sn[0], sn[1]
        if num_id is None or num_id == "0":
            return ""
        if ilvl is None:
            ilvl = 0
        aid = self.num_to_abs.get(num_id)
        levels = self.abstract.get(aid or "")
        if not levels or ilvl not in levels:
            return ""
        ctr = self.counters.setdefault(aid, [None] * 9)
        if num_id not in self.seen_num:
            self.seen_num.add(num_id)
            for lv, start in self.overrides.get(num_id, {}).items():
                ctr[lv] = start - 1
        if ctr[ilvl] is None:
            ctr[ilvl] = levels[ilvl]["start"]
        else:
            ctr[ilvl] += 1
        for k in range(ilvl + 1, 9):
            ctr[k] = None
        text = levels[ilvl]["text"]
        if not text or levels[ilvl]["fmt"] == "bullet":
            return ""

        def repl(m):
            k = int(m.group(1)) - 1
            lv = levels.get(k, {"start": 1, "fmt": "decimal"})
            val = ctr[k] if ctr[k] is not None else lv["start"]
            return _fmt_num(val, lv["fmt"])

        return re.sub(r"%(\d)", repl, text).strip()


# --------------------------------------------------------------------------------------
# Абзацы
# --------------------------------------------------------------------------------------
# Номер пункта в начале текста: «3.2», «3.2.», «5.», «5)»; голое число без точки — только перед заглавной буквой («5 Предмет»).
# «75 % от суммы», «475 000 руб.», «30 (тридцать) дней» номером не считаются.
_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"(\d+(?:\.\d+){1,5})[.)]?(?=\s|$)(?!\s*(?:%|‰|руб|₽|\$|€|тыс|млн|\d{3}\b))"  # 3.2 / 3.2.
    r"|(\d+)[.)](?=\s|$)"  # 5. / 5)
    r"|(\d+)(?=\s+[А-ЯЁA-Z])(?!\s*\d)"  # 5 Предмет
    r")")


def _clean_label(label: str) -> str:
    return label.strip().rstrip(".)").strip()


def _run_text(r) -> str:
    out = []
    for ch in r:
        tag = ch.tag
        if tag in (q("t"), q("delText")):
            out.append(ch.text or "")
        elif tag == q("tab"):
            out.append("\t")
        elif tag in (q("br"), q("cr")):
            out.append("\n")
        elif tag == q("noBreakHyphen"):
            out.append("-")
    return "".join(out)


def _attrs(el) -> tuple[str, str]:
    return el.get(q("author"), "") or "", el.get(q("date"), "") or ""


_TRANSPARENT = {
    q("hyperlink"), q("smartTag"), q("fldSimple"), q("customXml"), q("dir"), q("bdo"),
    q("sdtContent"), q("sdt"),
}


def _parse_paragraph(p, idx: int, open_comments: dict[str, list[str]], comment_para: dict[str, int]):
    """Разобрать абзац. Возвращает (Paragraph, {id комментария: якорный текст})."""
    para = Paragraph(index=idx)
    segs: list[Segment] = []
    anchors: dict[str, str] = {}

    def add(kind, text, author, date, move, ins_by):
        if not text:
            return
        if segs and segs[-1].kind == kind and segs[-1].author == author and segs[-1].date == date \
                and segs[-1].move == move and segs[-1].ins_author == ins_by:
            segs[-1].text += text
        else:
            segs.append(Segment(kind, text, author, date, move, ins_by))

    def note_comment(cid):
        if cid is not None and cid not in para.comment_ids:
            para.comment_ids.append(cid)
        if cid is not None:
            comment_para.setdefault(cid, idx)

    def walk(el, kind, author, date, move, ins_by=None):
        for ch in el:
            tag = ch.tag
            if tag == q("r"):
                text = _run_text(ch)
                add(kind, text, author, date, move, ins_by)
                if text:
                    for buf in open_comments.values():
                        buf.append(text)
                for ref in ch.findall(q("commentReference")):
                    note_comment(ref.get(q("id")))
            elif tag in (q("ins"), q("moveTo")):
                a, d = _attrs(ch)
                walk(ch, "ins", a, d, tag == q("moveTo"))
            elif tag in (q("del"), q("moveFrom")):
                a, d = _attrs(ch)
                # удаление внутри вставки: запоминаем, кто вставил текст
                inner_ins = author if kind == "ins" else ins_by
                walk(ch, "del", a, d, tag == q("moveFrom"), inner_ins)
            elif tag == q("commentRangeStart"):
                cid = ch.get(q("id"))
                if cid is not None:
                    open_comments.setdefault(cid, [])
                    note_comment(cid)
            elif tag == q("commentRangeEnd"):
                cid = ch.get(q("id"))
                if cid in open_comments:
                    anchors[cid] = "".join(open_comments.pop(cid))
            elif tag in _TRANSPARENT:
                walk(ch, kind, author, date, move, ins_by)

    walk(p, "equal", "", "", False)
    para.segments = segs
    return para, anchors


def _paragraph_mark(p) -> tuple[str, str]:
    mark = p.find(f"{q('pPr')}/{q('rPr')}")
    if mark is None:
        return "", ""
    ins = mark.find(q("ins"))
    if ins is not None:
        return "ins", ins.get(q("author"), "") or ""
    dele = mark.find(q("del"))
    if dele is not None:
        return "del", dele.get(q("author"), "") or ""
    return "", ""


def _in_fallback(p) -> bool:
    for anc in p.iterancestors():
        if anc.tag == f"{{{MC}}}Fallback":
            return True
    return False


def _in_table(p) -> bool:
    return any(a.tag == q("tc") for a in p.iterancestors())


def _table_pos(p, table_ids: dict) -> tuple:
    """(номер таблицы, строка, столбец, ширина) для абзаца в ячейке; () вне таблицы. Берётся ближайшая (внутренняя) ячейка.

    Столбец считается по сетке таблицы: объединённые по горизонтали ячейки (gridSpan) занимают несколько столбцов.
    """
    tc = next((a for a in p.iterancestors() if a.tag == q("tc")), None)
    if tc is None:
        return ()
    tr = tc.getparent()
    tbl = tr.getparent() if tr is not None else None
    if tr is None or tbl is None or tbl.tag != q("tbl"):
        return ()
    tid = table_ids.get(tbl)
    if tid is None:
        return ()
    rows = [r for r in tbl if r.tag == q("tr")]
    col = 0
    for cell in tr:
        if cell.tag != q("tc"):
            continue
        span = 1
        tcpr = cell.find(q("tcPr"))
        gs = tcpr.find(q("gridSpan")) if tcpr is not None else None
        if gs is not None:
            try:
                span = max(1, int(gs.get(q("val"), "1")))
            except ValueError:
                span = 1
        if cell is tc:
            return (tid, rows.index(tr) if tr in rows else 0, col, span)
        col += span
    return ()


def _is_heading(para: Paragraph, text: str, style_name: str) -> bool:
    sn = (style_name or "").lower()
    if sn.startswith("heading") or sn.startswith("заголовок") or sn == "title":
        return True
    label = para.label
    if label and "." not in label and 3 <= len(text) <= 90 and not text.rstrip().endswith((".", ";", ":")):
        return True
    letters = [c for c in text if c.isalpha()]
    if 3 <= len(text) <= 80 and letters and all(c.isupper() for c in letters):
        return True
    return False


def read_docx(path: str) -> DocxDoc:
    try:
        zf = zipfile.ZipFile(path)
    except FileNotFoundError:
        raise DocxError(f"файл не найден: {path}")
    except (zipfile.BadZipFile, IsADirectoryError, PermissionError) as e:
        raise DocxError(f"не удалось открыть {path}: это не docx или файл повреждён ({e.__class__.__name__})")
    with zf:
        if len(zf.namelist()) > 5000:
            raise DocxError("в архиве слишком много частей")
        doc_root = _read_part(zf, "word/document.xml", required=True)
        num_root = _read_part(zf, "word/numbering.xml")
        styles_root = _read_part(zf, "word/styles.xml")
        comments_root = _read_part(zf, "word/comments.xml")

    numbering = Numbering(num_root, styles_root)
    body = doc_root.find(q("body"))
    if body is None:
        raise DocxError("в document.xml нет тела документа")

    paragraphs: list[Paragraph] = []
    # номера таблиц по порядку; словарь держит ссылки на элементы, поэтому lxml отдаёт те же объекты-обёртки
    table_ids = {tbl: i for i, tbl in enumerate(body.iter(q("tbl")))}
    open_comments: dict[str, list[str]] = {}
    comment_para: dict[str, int] = {}
    anchors_all: dict[str, str] = {}
    last_label = ""
    last_heading = ""

    for p in body.iter(q("p")):
        if _in_fallback(p):
            continue
        idx = len(paragraphs)
        para, p_anchors = _parse_paragraph(p, idx, open_comments, comment_para)
        ppr = p.find(q("pPr"))
        style_el = ppr.find(q("pStyle")) if ppr is not None else None
        style_id = style_el.get(q("val"), "") if style_el is not None else ""
        para.style = numbering.style_name(style_id)
        para.in_table = _in_table(p)
        para.table = _table_pos(p, table_ids) if para.in_table else ()
        para.mark, para.mark_author = _paragraph_mark(p)
        # текст «как показан»: для нумерации берём исходный текст абзаца без удалённого
        visible = "".join(s.text for s in para.segments if s.kind in ("equal", "ins"))
        full = "".join(s.text for s in para.segments)
        auto = numbering.label_for(ppr, style_id)
        label = _clean_label(auto) if auto else ""
        if not label:
            m = _LABEL_RE.match(visible or full)
            if m:
                label = next(g for g in m.groups() if g)
                para.label_in_text = True
        para.label = label
        para.near = last_label
        if label:
            last_label = label
        text_for_head = (visible or full).strip()
        text_for_head = _LABEL_RE.sub("", text_for_head, count=1).strip() if not auto else text_for_head
        if _is_heading(para, text_for_head, para.style):
            last_heading = text_for_head
        para.heading = last_heading
        anchors_all.update(p_anchors)
        paragraphs.append(para)

    comments: dict[str, Comment] = {}
    if comments_root is not None:
        for c in comments_root.findall(q("comment")):
            cid = c.get(q("id"))
            text = "\n".join(
                "".join(t.text or "" for t in cp.iter(q("t"))) for cp in c.iter(q("p"))
            ).strip()
            comments[cid] = Comment(
                id=cid,
                author=c.get(q("author"), "") or "",
                date=c.get(q("date"), "") or "",
                text=text,
                anchor=(anchors_all.get(cid, "") or "")[:500],
                paragraph_index=comment_para.get(cid, -1),
            )

    authors = Counter()
    for para in paragraphs:
        for s in para.segments:
            if s.kind != "equal" and s.author:
                authors[s.author] += 1
        if para.mark_author:
            authors[para.mark_author] += 1
    for c in comments.values():
        if c.author:
            authors[c.author] += 1
    return DocxDoc(path=path, paragraphs=paragraphs, comments=comments, authors=[a for a, _ in authors.most_common()])


# --------------------------------------------------------------------------------------
# Представления документа: «принять все» / «отклонить все»
# --------------------------------------------------------------------------------------
def view_paragraphs(doc: DocxDoc, mode: str, ours: frozenset[str] | set[str] = frozenset()) -> list[tuple[Paragraph, str]]:
    """Список (абзац, текст) для режима 'accepted' или 'rejected'.

    Правки авторов из ours считаются принятыми в обоих режимах: это наши собственные
    правки, которые уже были в отправленной версии.
    """
    if mode not in ("accepted", "rejected"):
        raise ValueError(mode)

    def seg_included(s: Segment) -> bool:
        if s.kind == "equal":
            return True
        if s.author == ANNOTATOR:
            return s.kind == "del"  # примечания программы (annotate.py) — как будто их нет
        mine = s.author in ours
        if mode == "accepted":
            return s.kind == "ins"
        if s.kind == "del" and s.ins_author is not None:
            # текст вставил один автор, удалил другой: после «отклонить чужое» он есть,
            # только если вставка наша, а удаление чужое
            return s.ins_author in ours and not mine
        # rejected: чужие вставки убираем, чужие удаления возвращаем; свои правки принимаем
        if s.kind == "ins":
            return mine
        return not mine  # del

    texts = []
    for para in doc.paragraphs:
        text = "".join(s.text for s in para.segments if seg_included(s))
        texts.append(text)

    out: list[tuple[Paragraph, str]] = []
    carry = ""
    n = len(doc.paragraphs)
    for i, para in enumerate(doc.paragraphs):
        text = carry + texts[i]
        carry = ""
        kinds = {s.kind for s in para.segments if s.text.strip()}
        had_content = bool(kinds)
        content_gone = had_content and not texts[i].strip()
        mark_mine = para.mark_author in ours
        # знак абзаца: при принятии удаления / отклонении вставки абзацы склеиваются
        merge = False
        nxt = doc.paragraphs[i + 1] if i + 1 < n else None
        if nxt is not None:
            if mode == "accepted" and para.mark == "del" and not mark_mine:
                merge = nxt.state() != "deleted"
            if mode == "rejected" and para.mark == "ins" and not mark_mine:
                merge = nxt.state() != "inserted"
        if content_gone and not text.strip() and not merge:
            continue  # абзац целиком исчез
        if merge:
            carry = text
            continue
        out.append((para, text))
    if carry:
        if out:
            out[-1] = (out[-1][0], out[-1][1] + carry)
        else:
            out.append((doc.paragraphs[-1], carry))
    return out
