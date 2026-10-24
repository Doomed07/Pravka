"""Темы в договоре поставки: слова перед изменённым числом, переход риска, хранение, срок поставки."""
from pravki.classify import _lead_in, classify
from pravki.model import Change

PRICE = "Общая стоимость Товара составляет 2 400 000 (два миллиона четыреста тысяч) рублей, в том числе НДС 20%."
PAY = "Оставшуюся часть стоимости Товара Покупатель оплачивает в течение 10 рабочих дней с даты подписания товарной накладной."
SHIP = "Поставщик поставляет Товар в течение 30 календарных дней с даты получения аванса."
RISK = "Право собственности и риск случайной гибели Товара переходят к Покупателю с даты подписания товарной накладной."


def _topic(before, after, ctx, kind="replace"):
    return classify(Change(kind=kind, source="diff", before=before, after=after, context=ctx,
                           context_after=ctx.replace(before, after, 1) if before else after)).topic


def test_number_without_words_takes_topic_from_words_before_it():
    assert _topic("20", "0", PRICE) == "налоги"  # «…в том числе НДС 20%», а не «стоимость»
    assert _topic("10 рабочих дней", "45 календарных дней", PAY) == "порядок и сроки оплаты"


def test_supply_term_is_not_payment():
    assert _topic("30 календарных дней", "10 календарных дней", SHIP) == "сроки исполнения"


def test_risk_transfer_has_own_topic():
    assert _topic("с даты подписания товарной накладной", "с даты полной оплаты Товара", RISK) == \
        "переход права собственности и риска"


def test_storage_is_acceptance():
    text = "При отказе Покупателя принять Товар Поставщик хранит Товар за свой счёт в течение 60 календарных дней."
    assert _topic("", text, "", kind="para_insert") == "приёмка и качество"


def test_words_without_numbers_keep_sentence_topic():
    ctx = "Коммунальные услуги оплачиваются Арендатором по показаниям счётчиков."
    # без рецензирования правка приходит усечённой — «Коммунальные» выпадает из слов перед ней
    assert _topic("показаниям счётчиков", "тарифам, установленным Арендодателем", ctx) == "арендная плата и индексация"


def test_number_is_found_as_a_whole_number():
    ch = Change(kind="replace", after="0", context_after=PRICE.replace("НДС 20%", "НДС 0%"))
    assert _lead_in(ch).split()[-1] == "НДС"  # «0» в «НДС 0%», а не внутри «400 000»
