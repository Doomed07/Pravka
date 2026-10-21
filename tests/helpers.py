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
