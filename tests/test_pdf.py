import pytest

from pravki.docx_reader import DocxError
from pravki.pdf_reader import MAX_PAGES, paragraphs_from_pages, read_pdf
from pravki.readers import read_document, sniff_format
from tests.helpers import make_pdf

PAGE1 = """ООО «Омега» — Договор поставки № 15
1. Предмет договора
1.1. Поставщик обязуется поставить, а Покупатель принять и оплатить
товар в порядке и на условиях, указанных в настоящем договоре и спе-
цификации к нему.
2. Цена и порядок оплаты
2.1. Цена товара составляет 2 400 000 рублей, в том числе НДС 20%.
2.2. Покупатель оплачивает товар в течение 10 рабочих дней.
1""".splitlines()
PAGE2 = """ООО «Омега» — Договор поставки № 15
3. Ответственность сторон
3.1. За нарушение срока оплаты Покупатель уплачивает неустойку 0,1% от
неоплаченной суммы за каждый день просрочки.
3.2. Совокупная ответственность Поставщика ограничена суммой договора.
2""".splitlines()
PAGE3 = """ООО «Омега» — Договор поставки № 15
ПОДПИСИ СТОРОН
Поставщик: ООО «Омега»
3""".splitlines()


def test_paragraphs_drop_furniture_join_wrapped_lines_and_hyphenation():
    got = paragraphs_from_pages(["\n".join(PAGE1), "\n".join(PAGE2), "\n".join(PAGE3)])
    assert got == [
        "1. Предмет договора",
        "1.1. Поставщик обязуется поставить, а Покупатель принять и оплатить товар в порядке и на условиях, указанных в "
        "настоящем договоре и спецификации к нему.",
        "2. Цена и порядок оплаты",
        "2.1. Цена товара составляет 2 400 000 рублей, в том числе НДС 20%.",
        "2.2. Покупатель оплачивает товар в течение 10 рабочих дней.",
        "3. Ответственность сторон",
        "3.1. За нарушение срока оплаты Покупатель уплачивает неустойку 0,1% от неоплаченной суммы за каждый день просрочки.",
        "3.2. Совокупная ответственность Поставщика ограничена суммой договора.",
        "ПОДПИСИ СТОРОН",
        "Поставщик: ООО «Омега»",
    ]


def test_header_is_kept_when_pages_are_fewer_than_three():
    # колонтитул определяется по повтору на страницах: у двухстраничного файла его не отличить от обычной строки, но
    # номера страниц уходят, а строка колонтитула не прилипает к концу предыдущего пункта
    got = paragraphs_from_pages(["\n".join(PAGE1), "\n".join(PAGE2)])
    assert got.count("ООО «Омега» — Договор поставки № 15") == 2
    assert "1" not in got and "2" not in got
    assert got[got.index("2.2. Покупатель оплачивает товар в течение 10 рабочих дней.") + 1].startswith("ООО «Омега»")


def test_paragraph_continues_across_a_page_break():
    got = paragraphs_from_pages(["1.1. Поставщик обязуется поставить товар в порядке и на условиях, указанных в настоящем договоре и в\n"
                                 "спецификации к нему, а Покупатель обязуется принять товар и оплатить его в сроки, установленные",
                                 "договором.\n1.2. Следующий пункт договора."])
    assert got == ["1.1. Поставщик обязуется поставить товар в порядке и на условиях, указанных в настоящем договоре и в "
                   "спецификации к нему, а Покупатель обязуется принять товар и оплатить его в сроки, установленные договором.",
                   "1.2. Следующий пункт договора."]


def test_page_number_in_the_middle_of_a_page_is_text():
    got = paragraphs_from_pages(["Статья\n5\nПоставщик поставляет товар партиями по заявкам покупателя.\nВторая строка."])
    assert "5" in " ".join(got)


def test_labels_and_headings_are_restored(tmp_path):
    path = make_pdf(tmp_path / "t.pdf", [PAGE1, PAGE2, PAGE3])
    doc = read_document(str(path))
    assert doc.format == "pdf" and not doc.has_tracked and doc.comments == {}
    by = {p.label: p for p in doc.paragraphs if p.label}
    assert {"1", "1.1", "2", "2.1", "2.2", "3", "3.1", "3.2"} <= set(by)
    assert by["2.2"].heading == "2. Цена и порядок оплаты" or by["2.2"].heading.startswith("Цена и порядок")
    assert "В PDF" not in " ".join(doc.notes) and doc.notes[0].startswith("PDF: правки найдены сравнением")


def test_real_pdf_roundtrip_gives_cyrillic_text(tmp_path):
    doc = read_pdf(str(make_pdf(tmp_path / "t.pdf", [["1. Цена договора", "1.1. Цена 2 400 000 рублей."]])))
    assert [p.segments[0].text for p in doc.paragraphs] == ["1. Цена договора", "1.1. Цена 2 400 000 рублей."]


def test_scan_empty_encrypted_and_big_pdfs_are_refused(tmp_path):
    with pytest.raises(DocxError, match="нет текста"):
        read_pdf(str(make_pdf(tmp_path / "e.pdf", [[" "]])))
    with pytest.raises(DocxError, match="не удалось прочитать"):
        read_pdf(str(tmp_path / "a.pdf") if (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 garbage") else "")
    with pytest.raises(DocxError, match=f"больше {MAX_PAGES}"):
        read_pdf(str(make_pdf(tmp_path / "big.pdf", [["1. Пункт договора"]] * (MAX_PAGES + 1))))
    with pytest.raises(DocxError, match="не найден"):
        read_pdf(str(tmp_path / "нет.pdf"))


def test_pages_without_text_are_reported(tmp_path):
    doc = read_pdf(str(make_pdf(tmp_path / "t.pdf", [["1. Предмет договора"], [" "], ["2. Цена договора"]])))
    assert any("1 из 3 страниц без текста" in n for n in doc.notes)


def test_sniff_pdf(tmp_path):
    assert sniff_format(str(make_pdf(tmp_path / "t.pdf", [["x"]]))) == "pdf"


def test_repeated_line_in_the_middle_of_a_page_is_text():
    page = lambda n: "\n".join([f"{n}.1. Первый пункт договора номер {n}.", f"{n}.2. Второй пункт договора номер {n}.", "Согласовано сторонами.",
                                f"{n}.3. Третий пункт договора номер {n}.", f"{n}.4. Четвёртый пункт договора номер {n}.",
                                f"{n}.5. Пятый пункт договора номер {n}."])
    got = paragraphs_from_pages([page(1), page(2), page(3), page(4)])
    assert got.count("Согласовано сторонами.") == 4  # повторяется, но не с краю страницы — это текст, а не колонтитул


def test_line_must_repeat_on_half_of_the_pages_to_be_a_header():
    names = ["первой", "второй", "третьей", "четвёртой"]
    body = lambda n: "\n".join(f"{n}.{k}. Пункт {k} на странице {names[n - 1]}: уникальный текст {names[(n + k) % 4]}." for k in range(1, 7))
    pages = [f"Проект от 05.10.2026\n{body(1)}", f"Проект от 05.10.2026\n{body(2)}", f"Начало третьей страницы\n{body(3)}",
             f"Начало четвёртой страницы\n{body(4)}"]
    got = paragraphs_from_pages(pages)
    assert got.count("Проект от 05.10.2026") == 2  # на 2 из 4 страниц: меньше половины и меньше трёх — не колонтитул
    pages[2] = f"Проект от 05.10.2026\n{body(3)}"
    assert "Проект от 05.10.2026" not in paragraphs_from_pages(pages)  # на 3 из 4 — колонтитул


def test_hyphen_at_end_of_a_short_line_is_not_a_word_break():
    long = "Поставщик обязуется поставить товар в порядке и на условиях, указанных в договоре и в приложениях к нему"
    got = paragraphs_from_pages([f"1. {long}.\n2. {long}.\n3. Срок поставки -\nпо заявке покупателя.\n4. {long}."])
    assert "3. Срок поставки - по заявке покупателя." in got


def test_full_line_ending_with_a_period_does_not_end_the_paragraph():
    long = "Поставщик обязуется поставить товар в порядке и на условиях, указанных в договоре и в приложениях к нему"
    got = paragraphs_from_pages([f"1. {long}.\nПокупатель обязуется принять и оплатить поставленный товар в срок, указанный в договоре.\n"
                                 f"2. {long}.\n3. {long}."])
    assert got[0] == f"1. {long}. Покупатель обязуется принять и оплатить поставленный товар в срок, указанный в договоре."


def test_password_protected_pdf_is_refused(tmp_path):
    from pypdf import PdfReader, PdfWriter

    src = make_pdf(tmp_path / "plain.pdf", [["1. Пункт договора"]])
    w = PdfWriter(clone_from=PdfReader(str(src)))
    w.encrypt("секрет", algorithm="RC4-128")
    out = tmp_path / "locked.pdf"
    with open(out, "wb") as f:
        w.write(f)
    with pytest.raises(DocxError, match="паролем"):
        read_pdf(str(out))


def test_short_line_without_a_period_ends_the_paragraph():
    long = "Поставщик обязуется поставить товар в порядке и на условиях, указанных в договоре и в приложениях к нему"
    got = paragraphs_from_pages([f"ДОГОВОР ПОСТАВКИ № 15\nг. Москва 01.10.2026\n"
                                 f"ООО «Омега», именуемое в дальнейшем Поставщик, и ООО «Альфа», именуемое Покупатель, заключили договор о нижеследующем\n"
                                 f"1. {long}.\n2. {long}.\n3. {long}."])
    assert got[1] == "г. Москва 01.10.2026" and got[2].startswith("ООО «Омега»")


def test_short_line_followed_by_lowercase_continues():
    long = "Поставщик обязуется поставить товар в порядке и на условиях, указанных в договоре и в приложениях к нему"
    got = paragraphs_from_pages([f"1. {long}.\n2. Покупатель оплачивает товар по цене\nуказанной в спецификации к договору поставки и оплачивает доставку.\n"
                                 f"3. {long}.\n4. {long}."])
    assert "2. Покупатель оплачивает товар по цене указанной в спецификации к договору поставки и оплачивает доставку." in got


def test_short_line_threshold_is_about_two_thirds_of_a_full_line():
    full = "Поставщик обязуется поставить товар в порядке и на условиях, указанных в договоре и в приложениях к нему"[:88].rstrip()
    filler = "\n".join(f"{n}. {full}." for n in range(1, 8))
    # строка в 0,7 полной: так выглядит перенос внутри абзаца при другой ширине — склеиваем со следующей
    mid = "Покупатель принимает товар и оплачивает его по цене договора ежемесячно"[:62]
    got = paragraphs_from_pages([f"{filler}\n8. {mid}\nСледующая строка продолжает тот же пункт договора."])
    assert any(g.startswith("8. ") and "Следующая строка" in g for g in got)
    # строка в 0,45 полной без точки — абзац закончился
    short = "Реквизиты и подписи сторон"
    got = paragraphs_from_pages([f"{filler}\n8. {short}\nПоставщик: ООО «Омега», ИНН 7701234567."])
    assert any(g == f"8. {short}" for g in got)
