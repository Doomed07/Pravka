from pravki import textdiff as t


def test_normalize_quotes_dashes_spaces():
    assert t.normalize("а б — «в»​") == 'а б - "в"'


def test_numbers_canonical_and_dates_excluded():
    assert t.numbers("1 500 000,50 руб., срок 30 дней, до 01.02.2025") == ["1500000.50", "30"]


def test_flags():
    assert t.flags_for_change("30 дней", "45 дней") == ["число", "срок"]
    assert "процент" in t.flags_for_change("0,1%", "0,5%")
    assert "сумма" in t.flags_for_change("100 000 рублей", "90 000 рублей")
    assert "дата" in t.flags_for_change("до 01.02.2025", "до 01.03.2025")
    assert "отрицание" in t.flags_for_change("вправе", "не вправе")
    assert t.flags_for_change("договор", "Договор") == []


def test_diff_number_with_thousands_is_one_token():
    assert t.diff_changes("цена 1 200 000 руб.", "цена 1 000 000 руб.") == [("1 200 000", "1 000 000")]


def test_diff_slides_deletion_to_sentence_boundary():
    a = "4.3. Совокупная ответственность ограничена суммой. Исполнитель не возмещает убытки."
    b = "4.3. Исполнитель не возмещает убытки."
    assert t.diff_changes(a, b) == [("Совокупная ответственность ограничена суммой.", "")]


def test_diff_merges_changes_separated_by_one_word():
    assert t.diff_changes("включая НДС 20%", "без НДС") == [("включая НДС 20%", "без НДС")]


def test_diff_does_not_merge_across_sentences():
    out = t.diff_changes("Срок 10 дней. Штраф 5%.", "Срок 20 дней. Штраф 9%.")
    assert len(out) == 2


def test_strip_label():
    assert t.strip_label("4.3. Текст", "4.3") == "Текст"
    assert t.strip_label("Текст", "") == "Текст"
