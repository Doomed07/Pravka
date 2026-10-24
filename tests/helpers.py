"""Вспомогательные функции тестов: сборка docx из произвольного XML тела документа."""
import zipfile

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'w:author="Контрагент" w:date="2026-10-05T10:00:00Z"'
CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')


def make_docx(path, body, numbering=None, comments=None, styles=None, raw_document=None):
    doc = raw_document or f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
        if numbering:
            z.writestr("word/numbering.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:numbering {W}>{numbering}</w:numbering>')
        if comments:
            z.writestr("word/comments.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:comments {W}>{comments}</w:comments>')
        if styles:
            z.writestr("word/styles.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:styles {W}>{styles}</w:styles>')
    return path


def r(text):
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def ins(text, n=1, author="Контрагент"):
    return f'<w:ins w:id="{n}" w:author="{author}" w:date="2026-10-05T10:00:00Z"><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:ins>'


def dele(text, n=2, author="Контрагент"):
    return f'<w:del w:id="{n}" w:author="{author}" w:date="2026-10-05T10:00:00Z"><w:r><w:delText xml:space="preserve">{text}</w:delText></w:r></w:del>'


def p(*content, ppr=""):
    return f"<w:p><w:pPr>{ppr}</w:pPr>{''.join(content)}</w:p>"


ODF_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
          'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/"')


def make_odt(path, body, tracked="", automatic="", mimetype="application/vnd.oasis.opendocument.text"):
    """odt из XML тела (без LibreOffice). tracked — содержимое text:tracked-changes; automatic — автоматические стили."""
    tc = f"<text:tracked-changes>{tracked}</text:tracked-changes>" if tracked else ""
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ODF_NS}><office:automatic-styles>{automatic}'
           f"</office:automatic-styles><office:body><office:text>{tc}{body}</office:text></office:body></office:document-content>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", doc)
    return path


def odt_ins_region(cid, text_unused="", author="Контрагент"):
    return (f'<text:changed-region text:id="{cid}"><text:insertion><office:change-info><dc:creator>{author}</dc:creator>'
            f"<dc:date>2026-10-05T10:00:00</dc:date></office:change-info></text:insertion></text:changed-region>")


def odt_del_region(cid, deleted, author="Контрагент"):
    return (f'<text:changed-region text:id="{cid}"><text:deletion><office:change-info><dc:creator>{author}</dc:creator>'
            f"<dc:date>2026-10-05T10:00:00</dc:date></office:change-info><text:p>{deleted}</text:p></text:deletion></text:changed-region>")


def odt_ins(cid, text):
    return f'<text:change-start text:change-id="{cid}"/>{text}<text:change-end text:change-id="{cid}"/>'


def odt_del(cid):
    return f'<text:change text:change-id="{cid}"/>'


def make_pdf(path, pages, encrypt_note=False):
    """Настоящий PDF с текстом из строк страниц (pages — список списков строк), без внешних библиотек.

    Шрифт — Helvetica без встроенной программы, а русские буквы заданы через ToUnicode: pypdf достаёт текст так же, как из
    PDF, собранных Word или LibreOffice (внешний вид здесь не важен).
    """
    chars = sorted({c for page in pages for line in page for c in line})
    code = {c: i + 1 for i, c in enumerate(chars)}
    assert len(chars) < 250
    cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /T def /CMapType 2 def "
            "1 begincodespacerange <00> <FF> endcodespacerange %d beginbfchar %s endbfchar endcmap end end" % (
                len(chars), " ".join("<%02X> <%04X>" % (code[c], ord(c)) for c in chars)))
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    cat = add(b"")  # 1: каталог (заполним ниже)
    pages_id = add(b"")  # 2: список страниц
    tou = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(cmap), cmap.encode("ascii")))
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode %d 0 R >>" % tou)
    kids = []
    for page in pages:
        ops = ["BT /F1 11 Tf 14 TL 50 780 Td"]
        for line in page:
            enc = bytes(code[c] for c in line).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
            ops.append("(%s) Tj T*" % enc.decode("latin-1"))
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        kids.append(add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                        b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content, font)))
    objs[cat - 1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids).encode(), len(kids))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "wb") as f:
        f.write(bytes(out))
    return path


def odt_from_doc(path, doc):
    """odt с теми же абзацами, правками и комментариями, что в прочитанном docx (DocxDoc). Номера, которые в docx дала
    автонумерация, печатаются в тексте: списки ODF здесь не нужны."""
    from xml.sax.saxutils import escape

    tracked, body, n = [], [], 0
    for para in doc.paragraphs:
        out = []
        prefix = f"{para.label}. " if para.label and not para.label_in_text else ""
        for cid in para.comment_ids:
            c = doc.comments[cid]
            out.append(f'<office:annotation office:name="{cid}"><dc:creator>{escape(c.author)}</dc:creator><dc:date>{c.date}</dc:date>'
                       f"<text:p>{escape(c.text)}</text:p></office:annotation>")
        whole = para.state() != ""  # абзац вставлен или удалён целиком: номер входит в правку
        if prefix and not whole:
            out.append(escape(prefix))
        for i, s in enumerate(para.segments):
            text = escape((prefix if i == 0 and whole else "") + s.text)
            if s.kind == "equal":
                out.append(text)
                continue
            n += 1
            cid = f"ct{n}"
            if s.kind == "ins":
                tracked.append(odt_ins_region(cid, author=s.author))
                out.append(f'<text:change-start text:change-id="{cid}"/>{text}<text:change-end text:change-id="{cid}"/>')
            else:
                tracked.append(odt_del_region(cid, text, author=s.author))
                out.append(f'<text:change text:change-id="{cid}"/>')
        if not para.segments and prefix:
            out.append(escape(prefix))
        body.append("<text:p>" + "".join(out) + "</text:p>")
    return make_odt(path, "".join(body), "".join(tracked))


def pdf_from_docx(path, docx_path, width=88, per_page=22):
    """PDF с текстом договора «как принят» (без рецензирования): строки по width знаков, колонтитул и номер на каждой странице."""
    import textwrap

    from pravki.docx_reader import read_docx, view_paragraphs

    lines = []
    for para, text in view_paragraphs(read_docx(docx_path), "accepted"):
        text = " ".join(text.split())
        if not text:
            continue
        if para.label and not para.label_in_text:
            text = f"{para.label}. {text}"
        lines += textwrap.wrap(text, width) or [text]
    pages = []
    for i in range(0, len(lines), per_page):
        pages.append(["ООО «Омега» — Договор № 15"] + lines[i:i + per_page] + [str(len(pages) + 1)])
    return make_pdf(path, pages)
