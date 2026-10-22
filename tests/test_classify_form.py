from pravki.classify import classify
from pravki.model import Change

PREAMBLE = ("ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «КВАДРАТ», именуемое в дальнейшем «Организатор», и ИП Иванов И.И., "
            "действующий на основании записи ОГРНИП № 319774600680622 от 27 ноября 2019 г.")


def test_legal_form_is_not_liability_topic():
    ch = classify(Change(kind="insert", after="319774600680622", context_after=PREAMBLE, context=PREAMBLE))
    assert ch.topic != "ограничение ответственности"


def test_real_liability_limit_is_still_found():
    text = "Совокупная ответственность Исполнителя ограничена суммой, равной стоимости Услуг."
    ch = classify(Change(kind="delete", before=text, context=text))
    assert ch.topic == "ограничение ответственности"
