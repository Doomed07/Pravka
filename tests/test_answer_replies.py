"""Ответы на комментарии контрагента: ответ юриста — в той же ветке примечаний Word."""
import zipfile

from lxml import etree

from pravki.annotate import annotate_docx
from pravki.answer import build_answer
from pravki.answer_replies import W14, W15
from pravki.compare import compare_versions
from pravki.docx_reader import q, read_docx
from pravki.unified import build_unified
from tests.helpers import make_docx, p, r

BODY = p('<w:commentRangeStart w:id="3"/>', r("1.1. Срок оплаты 10 дней."), '<w:commentRangeEnd w:id="3"/>',
         '<w:r><w:commentReference w:id="3"/></w:r>')
COMMENT = ('<w:comment w:id="3" w:author="Контрагент" w:date="2026-03-30T10:00:00Z">'
           '<w:p><w:r><w:t>Просим 30 дней.</w:t></w:r></w:p><w:p><w:r><w:t>Иначе не согласуем.</w:t></w:r></w:p></w:comment>')


def _answer(tmp_path, text, body=BODY, comments=COMMENT):
    tp = str(make_docx(tmp_path / "t.docx", body, comments=comments))
    theirs = read_docx(tp)
    changes = compare_versions(None, theirs, ["Мы"])
    unified = str(tmp_path / "u.docx")
    annotate_docx(tp, unified, changes, build_unified(None, theirs, {"Мы"}, changes))
    dicts = [c.to_dict() for c in changes]
    cm = next(c for c in dicts if c["kind"] == "comment")
    out = str(tmp_path / "a.docx")
    stats = build_answer(unified, out, dicts, {cm["id"]: {"choice": "reply", "text": text}}, "Иванова А.")
    return out, stats


def _part(path, name):
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read(name)) if name in z.namelist() else None


def test_reply_is_in_the_same_thread(tmp_path):
    out, stats = _answer(tmp_path, "Согласны на 20 дней.\nПредлагаем компромисс.")
    assert stats["reply"] == 1
    comments = read_docx(out).comments
    reply = next(c for c in comments.values() if c.author == "Иванова А.")
    assert reply.text == "Согласны на 20 дней.\nПредлагаем компромисс."
    # ветка: commentEx ответа указывает на последний абзац родительского комментария
    croot = _part(out, "word/comments.xml")
    parent = next(c for c in croot.findall(q("comment")) if c.get(q("id")) == "3")
    mine = next(c for c in croot.findall(q("comment")) if c.get(q("author")) == "Иванова А.")
    parent_pid = parent.findall(q("p"))[-1].get(f"{{{W14}}}paraId")
    reply_pid = mine.findall(q("p"))[-1].get(f"{{{W14}}}paraId")
    ext = {e.get(f"{{{W15}}}paraId"): e.get(f"{{{W15}}}paraIdParent") for e in _part(out, "word/commentsExtended.xml")}
    assert parent_pid and reply_pid and ext[reply_pid] == parent_pid
    with zipfile.ZipFile(out) as z:
        raw = z.read("word/comments.xml").decode("utf-8")
    assert "w14:paraId=" in raw and "ns0:" not in raw  # пространство w14 объявлено в корне, как у Word
    # пакет объявляет новую часть, якорь ответа — рядом с якорем родителя
    ct = _part(out, "[Content_Types].xml")
    assert any(o.get("PartName") == "/word/commentsExtended.xml" for o in ct)
    rels = _part(out, "word/_rels/document.xml.rels")
    assert any(x.get("Target") == "commentsExtended.xml" for x in rels)
    doc = _part(out, "word/document.xml")
    rid = mine.get(q("id"))
    for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
        assert any(e.get(q("id")) == rid for e in doc.iter(q(tag))), tag


def test_empty_reply_is_not_added(tmp_path):
    out, stats = _answer(tmp_path, "   ")
    assert stats["reply"] == 0
    assert [c.author for c in read_docx(out).comments.values()] == ["Контрагент"]
    assert _part(out, "word/commentsExtended.xml") is None


def test_reply_does_not_change_contract_text(tmp_path):
    out, _ = _answer(tmp_path, "Согласны.")
    para = read_docx(out).paragraphs[0]
    assert "".join(s.text for s in para.segments) == "1.1. Срок оплаты 10 дней." and {s.kind for s in para.segments} == {"equal"}


def test_anchor_order_matches_word(tmp_path):
    out, _ = _answer(tmp_path, "Согласны.")
    doc = _part(out, "word/document.xml")
    tags = {q("commentRangeStart"): "start", q("commentRangeEnd"): "end", q("commentReference"): "ref"}
    seq = [(tags[e.tag], e.get(q("id"))) for e in doc.iter() if e.tag in tags]
    reply = next(i for _, i in seq if i != "3")
    # так пишет сам Word: начало родителя, начало ответа, конец родителя, ссылка родителя, конец ответа, ссылка ответа
    assert seq == [("start", "3"), ("start", reply), ("end", "3"), ("ref", "3"), ("end", reply), ("ref", reply)]
