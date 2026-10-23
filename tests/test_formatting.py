from pravki.docx_reader import read_docx
from pravki.unified import build_unified
from tests.helpers import make_docx, p, r

BULLETS = ('<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
           '<w:lvlText w:val=""/></w:lvl><w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
           '<w:lvlText w:val="o"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>')
STYLES = ('<w:style w:type="paragraph" w:styleId="Strong"><w:name w:val="Strong"/><w:rPr><w:b/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="StrongChild"><w:name w:val="StrongChild"/><w:basedOn w:val="Strong"/></w:style>')


def rb(text, props):
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'


def _doc(tmp_path, body):
    return read_docx(str(make_docx(tmp_path / "f.docx", body, numbering=BULLETS, styles=STYLES)))


def test_bold_and_italic_runs(tmp_path):
    doc = _doc(tmp_path, p(rb("Жирно", "<w:b/>"), r(" и "), rb("курсив", "<w:i/>"), rb(" выключено", '<w:b w:val="0"/>')))
    segs = [(s.text, s.bold, s.italic) for s in doc.paragraphs[0].segments]
    assert segs == [("Жирно", True, False), (" и ", False, False), ("курсив", False, True), (" выключено", False, False)]


def test_bold_from_paragraph_style_with_inheritance(tmp_path):
    doc = _doc(tmp_path, p(r("Весь абзац жирный"), ppr='<w:pStyle w:val="StrongChild"/>')
               + p(rb("кроме этого", '<w:b w:val="0"/>'), ppr='<w:pStyle w:val="Strong"/>'))
    assert doc.paragraphs[0].segments[0].bold is True
    assert doc.paragraphs[1].segments[0].bold is False


def test_bullets_levels_indent_and_alignment(tmp_path):
    body = (p(r("Пункт списка"), ppr='<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
            + p(r("Вложенный"), ppr='<w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr><w:ind w:left="1440"/>')
            + p(r("По центру"), ppr='<w:jc w:val="center"/>'))
    paras = _doc(tmp_path, body).paragraphs
    assert [(x.list_kind, x.level, x.label) for x in paras[:2]] == [("bullet", 0, ""), ("bullet", 1, "")]
    assert paras[1].indent == 1440 and paras[2].align == "center" and paras[2].list_kind == ""


def test_unified_keeps_formatting(tmp_path):
    body = p(rb("Индивидуальные опции:", "<w:b/>")) + p(r("Промо-стенд"), ppr='<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    doc = build_unified(None, _doc(tmp_path, body), set(), [])
    assert doc[0]["segments"] == [{"k": "equal", "t": "Индивидуальные опции:", "a": "", "b": True}]
    assert doc[1]["list"] == "bullet" and doc[1]["level"] == 0
