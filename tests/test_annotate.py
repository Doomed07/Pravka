import zipfile

from lxml import etree

from pravki.annotate import DISCLAIMER, annotate_docx
from pravki.compare import compare_versions
from pravki.docx_reader import q, read_docx
from pravki.model import ANNOTATOR
from pravki.unified import build_unified
from tests.helpers import dele, ins, make_docx, p, r

BASE = p(r("1.1. Срок 10 дней.")) + p(r("1.2. Штраф 5%.")) + p(r("1.3. Подсудность — Москва."))
THEIRS = p(r("1.1. Срок "), dele("10"), ins("20"), r(" дней.")) + p(r("1.2. Штраф 9%."))


def _run(tmp_path, base_body=BASE, theirs_body=THEIRS, **kw):
    base = read_docx(str(make_docx(tmp_path / "base.docx", base_body)))
    theirs_path = str(make_docx(tmp_path / "theirs.docx", theirs_body, **kw))
    theirs = read_docx(theirs_path)
    changes = compare_versions(base, theirs)
    for c in changes:
        c.action = "Отклонить или предложить встречную редакцию"
    doc = build_unified(base, theirs, set(), changes)
    out = str(tmp_path / "unified.docx")
    n = annotate_docx(theirs_path, out, changes, doc)
    return base, theirs, changes, out, n


def _key(changes):
    return [(c.source, c.kind, c.before, c.after) for c in changes]


def test_counterparty_changes_are_kept_and_ours_are_ignored(tmp_path):
    base, _, changes, out, _ = _run(tmp_path)
    again = compare_versions(base, read_docx(out))
    assert _key(again) == _key(changes)  # примечания и дисклеймер не стали «правками контрагента»


def test_one_comment_per_change(tmp_path):
    _, _, changes, out, n = _run(tmp_path)
    comments = read_docx(out).comments
    assert n == len(changes) == len(comments) == 3
    texts = [c.text for c in comments.values()]
    assert all(c.author == ANNOTATOR for c in comments.values())
    assert any("без отметки" in t and "«5» → стало «9»" in t for t in texts)
    assert all("Отклонить" in t for t in texts)


def test_removed_paragraph_comment_goes_to_previous_paragraph(tmp_path):
    _, _, changes, out, _ = _run(tmp_path)
    removed = next(c for c in changes if c.kind == "para_delete")
    doc = read_docx(out)
    note = next(c for c in doc.comments.values() if c.text.startswith(removed.id))
    assert doc.paragraphs[note.paragraph_index].clause == "1.2"


def test_disclaimer_is_last_and_tracked(tmp_path):
    _, _, _, out, _ = _run(tmp_path)
    last = read_docx(out).paragraphs[-1]
    assert "".join(s.text for s in last.segments) == DISCLAIMER
    assert {(s.kind, s.author) for s in last.segments} == {("ins", ANNOTATOR)}


def test_existing_comments_keep_their_ids(tmp_path):
    body = p('<w:commentRangeStart w:id="5"/>', r("1.1. Срок 20 дней."), '<w:commentRangeEnd w:id="5"/>',
             '<w:r><w:commentReference w:id="5"/></w:r>')
    old = '<w:comment w:id="5" w:author="Контрагент"><w:p><w:r><w:t>Почему 10?</w:t></w:r></w:p></w:comment>'
    _, _, changes, out, _ = _run(tmp_path, p(r("1.1. Срок 10 дней.")), body, comments=old)
    comments = read_docx(out).comments
    assert comments["5"].text == "Почему 10?"
    assert len(comments) == len(changes) + 1 and "5" not in [k for k, c in comments.items() if c.author == ANNOTATOR]


def test_package_declares_comments_part(tmp_path):
    _, _, _, out, _ = _run(tmp_path)
    with zipfile.ZipFile(out) as z:
        ct = etree.fromstring(z.read("[Content_Types].xml"))
        rels = etree.fromstring(z.read("word/_rels/document.xml.rels"))
        doc = etree.fromstring(z.read("word/document.xml"))
    assert any(o.get("PartName") == "/word/comments.xml" for o in ct)
    assert any(r.get("Target") == "comments.xml" for r in rels)
    starts = {e.get(q("id")) for e in doc.iter(q("commentRangeStart"))}
    refs = {e.get(q("id")) for e in doc.iter(q("commentReference"))}
    assert starts == refs and len(starts) == 3


def test_accepted_change_from_our_version_is_described_as_such(tmp_path):
    base = read_docx(str(make_docx(tmp_path / "base.docx", p(r("1.1. Срок "), ins("10", author="Коллега"), r(" дней.")))))
    theirs_path = str(make_docx(tmp_path / "theirs.docx", p(r("1.1. Срок 10 дней."))))
    theirs = read_docx(theirs_path)
    changes = compare_versions(base, theirs, ["kandu"])  # коллега не указан среди наших авторов
    out = str(tmp_path / "unified.docx")
    annotate_docx(theirs_path, out, changes, build_unified(base, theirs, {"kandu"}, changes))
    text = next(iter(read_docx(out).comments.values())).text
    assert changes[0].detail.get("accepted_from_base") and "Принята правка из нашей версии" in text
    assert "без отметки" not in text
