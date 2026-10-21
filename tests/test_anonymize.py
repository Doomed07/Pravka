"""Обезличивание docx: что заменяется, что остаётся, и что рецензирование не ломается."""
import zipfile

import pytest

from pravki.anonymize import Anonymizer, anonymize_docx, learn_docx, residual_candidates, scan_leaks
from pravki.docx_reader import read_docx, view_paragraphs
from pravki.extract import extract_tracked
from pravki.parties import parse_parties
from tests.helpers import CT, RELS, W, dele, ins, p, r

AUTHOR = "Иван Петров"  # учебное имя автора, ни с кем не связано


def _write(path, body, comments=None, extra=None, rels=None, content_types=None):
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", content_types or CT)
        z.writestr("_rels/.rels", rels or RELS)
        z.writestr("word/document.xml", doc)
        if comments:
            z.writestr("word/comments.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:comments {W}>{comments}</w:comments>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return str(path)


PREAMBLE = (
    "Общество с ограниченной ответственностью «Ромашка Софт», ИНН 7701234567, ОГРН 1027700000001, именуемое в дальнейшем "
    "«Исполнитель», в лице генерального директора Смирнова Алексея Петровича, действующего на основании Устава, с одной стороны, и "
    "Индивидуальный предприниматель Кузнецова Ольга Ивановна, ИНН 500100732259, именуемая в дальнейшем «Заказчик», с другой стороны, "
    "заключили договор о нижеследующем:"
)


def _anon_for(*paths, authors=None, terms=None):
    a = Anonymizer(authors=dict(authors or {}), terms=dict(terms or {}))
    for pth in paths:
        learn_docx(a, pth)
    return a


def _all_text(path):
    with zipfile.ZipFile(path) as z:
        return "\n".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith((".xml", ".rels")))


def test_names_ids_and_contacts_are_replaced(tmp_path):
    body = (p(r(PREAMBLE)) +
            p(r("1.1. Исполнитель обязуется передать Заказчику отчёт за 30 дней, неустойка 0,1% в день, не более 10%.")) +
            p(r("Тел.: +7 (495) 123-45-67, e-mail: info@romashka.ru, сайт https://romashka.ru/contacts, г. Москва, ул. Тверская, д. 5")) +
            p(r("Р/с 40702810900000012345 в Банке «Северный»; Смирнов А.П., Кузнецова О.И.")))
    src = _write(tmp_path / "a.docx", body)
    a = _anon_for(src)
    dst = str(tmp_path / "out.docx")
    anonymize_docx(a, src, dst)
    text = _all_text(dst)
    for secret in ("Ромашка", "Смирнов", "Кузнецов", "7701234567", "1027700000001", "500100732259", "40702810900000012345",
                   "romashka", "123-45-67", "Тверская", "Алексе", "Ольга", "Северный"):
        assert secret not in text, secret
    doc = read_docx(dst)
    full = " ".join("".join(s.text for s in para.segments) for para in doc.paragraphs)
    # условия договора остались как были
    assert "за 30 дней" in full and "0,1% в день" in full and "не более 10%" in full
    assert scan_leaks(a, dst) == []


def test_preamble_stays_parseable_and_roles_survive(tmp_path):
    src = _write(tmp_path / "a.docx", p(r(PREAMBLE)))
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    doc = read_docx(dst)
    text = "".join(s.text for s in doc.paragraphs[0].segments)
    ps = parse_parties(text)
    assert [x.role for x in ps] == ["Исполнитель", "Заказчик"]
    assert all(x.name for x in ps) and "Ромашка" not in ps[0].name
    assert ps[0].inn and ps[0].inn != "7701234567" and len(ps[0].inn) == 10


def test_name_split_across_runs_and_in_tracked_changes(tmp_path):
    # «Ромашка» набрана двумя кусками, «Смирнов» удалён внутри правки, номер телефона заменён правкой
    body = p(r("ООО «Ромаш"), r("ка Софт» передаёт товар. В лице "), dele("Смирнова А.П.", 1, AUTHOR), ins("Кузнецовой О.И.", 2, "Администратор"),
             r(". Тел. "), dele("495 111-22-33", 3, AUTHOR), ins("495 444-55-66", 4, "Администратор"))
    src = _write(tmp_path / "a.docx", body + p(r("Ромашка Софт и Смирнов Алексей Петрович подписали.")))
    a = _anon_for(src, authors={AUTHOR: "Мы", "Администратор": "Контрагент"})
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    text = _all_text(dst)
    for secret in ("Ромаш", "Смирнов", "Кузнецов", "111-22-33", "444-55-66", AUTHOR, "Администратор"):
        assert secret not in text, secret
    # рецензирование на месте: те же авторы-роли, та же структура правок
    ch = extract_tracked(read_docx(dst))
    assert sorted({c.author for c in ch}) == ["Контрагент", "Мы"]
    assert scan_leaks(a, dst) == []


def test_declined_forms_of_a_person_are_all_replaced(tmp_path):
    body = (p(r("Директор Смирнов Алексей Петрович.")) + p(r("Договор подписан Смирновым А.П. и вручён Смирнову Алексею Петровичу.")) +
            p(r("От имени Смирнова действует доверенность.")))
    src = _write(tmp_path / "a.docx", body)
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    text = _all_text(dst)
    assert "Смирн" not in text and "Алекс" not in text and "Петрович" not in text
    assert scan_leaks(a, dst) == []


def test_same_name_gets_the_same_replacement_in_both_versions(tmp_path):
    s1 = _write(tmp_path / "base.docx", p(r(PREAMBLE)) + p(r("1.1. Срок 10 дней.")))
    s2 = _write(tmp_path / "theirs.docx", p(r(PREAMBLE)) + p(r("1.1. Срок "), dele("10"), ins("30"), r(" дней.")))
    a = _anon_for(s1, s2)
    o1, o2 = str(tmp_path / "o1.docx"), str(tmp_path / "o2.docx")
    anonymize_docx(a, s1, o1)
    anonymize_docx(a, s2, o2)
    d1, d2 = read_docx(o1), read_docx(o2)
    assert "".join(s.text for s in d1.paragraphs[0].segments) == "".join(s.text for s in d2.paragraphs[0].segments)
    ch = extract_tracked(d2)
    assert [(c.before, c.after) for c in ch] == [("10", "30")]


def test_map_roundtrip_keeps_replacements(tmp_path):
    src = _write(tmp_path / "a.docx", p(r(PREAMBLE)))
    a = _anon_for(src, authors={"Контрагент": "Они"})
    o1 = str(tmp_path / "o1.docx")
    anonymize_docx(a, src, o1)
    b = Anonymizer.from_json(a.to_json())
    o2 = str(tmp_path / "o2.docx")
    anonymize_docx(b, src, o2)
    assert read_docx(o1).paragraphs[0].segments[0].text == read_docx(o2).paragraphs[0].segments[0].text


def test_metadata_thumbnail_custom_parts_images_and_links_are_cleaned(tmp_path):
    ct = CT.replace("</Types>", '<Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/>'
                    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                    '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
                    '</Types>')
    rels = RELS.replace("</Relationships>",
                        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail" Target="docProps/thumbnail.jpeg"/>'
                        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/>'
                        '</Relationships>')
    core = ('<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Петров Иван Сергеевич</dc:creator><cp:lastModifiedBy>Петров И.</cp:lastModifiedBy>'
            '<dc:title>Договор с Ромашка</dc:title></cp:coreProperties>')
    docrels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
               'Target="https://romashka.ru/secret?id=7" TargetMode="External"/>'
               '<Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
               '</Relationships>')
    src = _write(tmp_path / "a.docx", p(r("ООО «Ромашка Софт» поставляет товар.")), rels=rels, content_types=ct, extra={
        "docProps/core.xml": core, "docProps/custom.xml": "<Properties><x>секрет</x></Properties>",
        "docProps/thumbnail.jpeg": b"\xff\xd8thumb", "word/_rels/document.xml.rels": docrels,
        "word/media/image1.png": b"\x89PNG-secret-logo", "customXml/item1.xml": "<r>Ромашка</r>"})
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    s = anonymize_docx(a, src, dst)
    with zipfile.ZipFile(dst) as z:
        names = z.namelist()
        assert not any(n.startswith(("customXml", "docProps/thumbnail", "docProps/custom")) for n in names)
        assert b"secret-logo" not in z.read("word/media/image1.png")
        ctx = z.read("[Content_Types].xml").decode()
        assert "custom.xml" not in ctx and "core.xml" in ctx
        rootrels = z.read("_rels/.rels").decode()
        assert "thumbnail" not in rootrels and "custom.xml" not in rootrels
    text = _all_text(dst)
    for secret in ("Петров", "Ромашка", "romashka", "секрет", "secret"):
        assert secret not in text, secret
    assert s["картинок заменено"] == 1 and s["удалено частей"] >= 3
    read_docx(dst)  # файл по-прежнему читается
    assert scan_leaks(a, dst) == []


def test_comment_authors_are_mapped_and_comment_text_cleaned(tmp_path):
    body = p('<w:commentRangeStart w:id="0"/>', r("Спорная фраза."), '<w:commentRangeEnd w:id="0"/>', '<w:r><w:commentReference w:id="0"/></w:r>') + \
        p(r("ООО «Ромашка Софт», Смирнов А.П."))
    com = (f'<w:comment w:id="0" w:author="Admin" w:initials="AD" w:date="2026-10-05T10:00:00Z"><w:p><w:r><w:t>Ромашка настаивает, '
           f'звоните Смирнову: +7 495 000-11-22</w:t></w:r></w:p></w:comment>')
    src = _write(tmp_path / "a.docx", body, comments=com)
    a = _anon_for(src, authors={"Admin": "Контрагент"})
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    text = _all_text(dst)
    assert "Admin" not in text and "Ромашка" not in text and "Смирн" not in text and "000-11-22" not in text
    doc = read_docx(dst)
    cm = next(iter(doc.comments.values()))
    assert cm.author == "Контрагент" and "настаивает" in cm.text
    assert scan_leaks(a, dst) == []


def test_digits_are_not_touched_outside_identifiers(tmp_path):
    body = p(r("2.2. Оплата в течение 10 рабочих дней, сумма 1 200 000 рублей, ст. 317.1 ГК РФ, срок до 31.12.2026, п. 4.3.")) + \
        p(r("Не позднее 15 числа месяца, следующего за отчётным; почта для уведомлений указана в п. 9.1, срок ответа 5 дней."))
    src = _write(tmp_path / "a.docx", body)
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    before = [" ".join(s.text for s in x.segments) for x in read_docx(src).paragraphs]
    after = [" ".join(s.text for s in x.segments) for x in read_docx(dst).paragraphs]
    assert before == after  # в длинной строке про срок «почта» не должна стирать числа


def test_foreign_company_and_manual_terms(tmp_path):
    body = p(r("Huawei Technologies Co., Ltd., именуемое в дальнейшем «Поставщик», поставляет оборудование Leisuwash 360 в рамках мероприятия «Форум Будущего»."))
    src = _write(tmp_path / "a.docx", body)
    a = _anon_for(src, terms={"Leisuwash": "Продукт", "Форум Будущего": "Мероприятие"})
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    text = _all_text(dst)
    assert "Huawei" not in text and "Leisuwash" not in text and "Будущего" not in text
    assert "Foreign Trading" in text and "Продукт 360" in text


def test_residual_candidates_show_unknown_names(tmp_path):
    src = _write(tmp_path / "a.docx", p(r("Стороны договорились о поставке продукции Нептун и оказании услуг сервиса Zorro.")))
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    words = [w for w, _ in residual_candidates(dst)]
    assert "Нептун" in words and "Zorro" in words


def test_leak_scan_catches_a_name_the_anonymizer_missed(tmp_path):
    src = _write(tmp_path / "a.docx", p(r("ИП Смирнов Алексей подписал, а Смирнов А.П. согласен.")))
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    assert scan_leaks(a, dst) == []
    # подмешиваем в результат исходное имя: проверка должна сработать
    with zipfile.ZipFile(dst) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].replace("</w:body>".encode(), "<w:p><w:r><w:t>Смирнов</w:t></w:r></w:p></w:body>".encode())
    bad = str(tmp_path / "bad.docx")
    with zipfile.ZipFile(bad, "w") as z:
        for n, d in parts.items():
            z.writestr(n, d)
    leaks = scan_leaks(a, bad)
    assert leaks and any("Смирнов" in str(x) for x in leaks)


def test_cli_anonymizes_a_set_with_one_map(tmp_path, capsys):
    from pravki.cli import main
    s1 = _write(tmp_path / "base.docx", p(r(PREAMBLE)) + p(r("1.1. Срок 10 дней.")))
    s2 = _write(tmp_path / "theirs.docx", p(r(PREAMBLE)) + p(r("1.1. Срок "), dele("10", 1, "Admin"), ins("30", 2, "Admin"), r(" дней.")))
    out, mp = tmp_path / "out", tmp_path / "map.json"
    rc = main(["anonymize", s1, s2, "--out", str(out), "--map", str(mp), "--author", "Admin=Контрагент", "--residual"])
    assert rc == 0
    names = sorted(x.name for x in out.iterdir())
    assert names == ["doc01.docx", "doc02.docx"]  # имена исходных файлов не сохраняются
    assert (tmp_path / "map.index.json").exists() and mp.exists()
    doc = read_docx(str(out / "doc02.docx"))
    ch = extract_tracked(doc)
    assert [(c.before, c.after, c.author) for c in ch] == [("10", "30", "Контрагент")]
    # повторный запуск с той же картой даёт те же замены
    first = read_docx(str(out / "doc01.docx")).paragraphs[0].segments[0].text
    out2 = tmp_path / "out2"
    assert main(["anonymize", s1, "--out", str(out2), "--map", str(mp)]) == 0
    assert read_docx(str(out2 / "doc01.docx")).paragraphs[0].segments[0].text == first


def test_street_after_name_building_numbers_and_postal_code(tmp_path):
    src = _write(tmp_path / "a.docx", p(r("Юридический адрес: 123098, Москва г., Маршала Василевского ул., д.7, корп. 1, кв. 32")) +
                 p(r("1.1. Передать товар в течение 5 дней по пункту д. 3 приложения.")))
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    text = " ".join("".join(s.text for s in x.segments) for x in read_docx(dst).paragraphs)
    assert "Василев" not in text and "123098" not in text and "кв. 32" not in text and "д.7" not in text
    assert "Москва" in text  # город остаётся
    assert "в течение 5 дней" in text and "д. 3 приложения" in text  # вне адреса ничего не трогаем


def test_org_name_in_different_case_is_replaced_everywhere(tmp_path):
    src = _write(tmp_path / "a.docx", p(r("ООО «КВАДРАТ РЕСУРС» и ООО «Квадрат ресурс» подписали. Квадрат просит ускорить.")) +
                 p(r("Центральный банк России не изменился, а портал остался порталом.")))
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    text = " ".join("".join(s.text for s in x.segments) for x in read_docx(dst).paragraphs)
    assert "КВАДРАТ" not in text.upper().replace("ОРГАНИЗАЦИЯ", "") and "Организация-1" in text
    assert "Центральный банк России" in text and "портал" in text  # обычные слова не портим


def test_role_in_quotes_is_not_an_organization(tmp_path):
    src = _write(tmp_path / "a.docx", p(r("ООО «Ромашка», именуемое в дальнейшем «Перевозчик», и Компания «Нептун» заключили договор. «___» месяца.")))
    a = _anon_for(src)
    assert "перевозчик" not in a.orgs and "___" not in " ".join(a.orgs) and "нептун" in a.orgs


def test_field_codes_keep_bookmark_names(tmp_path):
    body = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGEREF _Toc227125846 \\h </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r><w:bookmarkStart w:id="1" w:name="_Toc227125846"/><w:r><w:t>Раздел</w:t></w:r></w:p>')
    src = _write(tmp_path / "a.docx", body)
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    xml = _all_text(dst)
    assert xml.count("_Toc227125846") == 2  # ссылка в поле и закладка совпадают
    assert scan_leaks(a, dst) == []


def test_phone_digits_already_replaced_are_not_replaced_twice(tmp_path):
    src = _write(tmp_path / "a.docx", p(r("Тел.: +7 (916) 123-45-67, +7 (916) 765-43-21; e-mail: a@b.ru")))
    a = _anon_for(src)
    dst = str(tmp_path / "o.docx")
    anonymize_docx(a, src, dst)
    again = str(tmp_path / "o2.docx")
    anonymize_docx(a, dst, again)  # повторное обезличивание уже обезличенного не меняет его
    assert read_docx(dst).paragraphs[0].segments[0].text == read_docx(again).paragraphs[0].segments[0].text
    assert scan_leaks(a, dst) == []
