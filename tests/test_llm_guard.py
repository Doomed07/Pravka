"""Защита пояснений модели: направление правки, выдуманные органы и должности, факты соседних правок."""
import json

from pravki.llm import Explainer, check_output
from pravki.model import Change

ACCEPT_TEXT = "При отсутствии мотивированного отказа в указанный срок Услуги считаются принятыми."
CLAUSE_71 = ("Споры разрешаются в Арбитражном суде города Санкт-Петербурга после соблюдения претензионного порядка. "
             "Срок ответа на претензию - 30 календарных дней.")


class Stub:
    def __init__(self, answer):
        self.answer = answer
        self.last = None

    def complete(self, system, user):
        self.last = json.loads(user)
        return self.answer


def _deletion():
    return Change(kind="para_delete", source="tracked", clause="3.3", before=ACCEPT_TEXT, context=ACCEPT_TEXT,
                  explanation="Приёмка услуг", suggested="молчание считается приёмкой")


def _explain(ch, answer, neighbours=()):
    ex = Explainer(Stub(answer))
    ch.explanation = ch.explanation or "Шаблон по правилу."
    before = ch.explanation
    ex.apply(ch, neighbours)
    return ex, ch.explanation != before


def test_deletion_described_as_missing_is_rejected():
    _, used = _explain(_deletion(), "В текущей редакции договора отсутствует условие о том, что услуги считаются принятыми.")
    assert not used


def test_deletion_described_as_removal_is_accepted():
    _, used = _explain(_deletion(), "Контрагент удалил условие о том, что услуги считаются принятыми при молчании.")
    assert used


def test_insertion_must_be_described_as_added():
    ch = Change(kind="insert", source="tracked", after="Исполнитель возмещает НДС.", context_after="Исполнитель возмещает НДС.")
    assert check_output("Исполнитель теперь обязан возмещать НДС.", ch, []) is not None
    assert check_output("Контрагент добавил обязанность Исполнителя возмещать НДС.", ch, []) is None


def test_invented_authority_is_rejected_but_known_one_passes():
    ch = Change(kind="insert", source="tracked", after="Исполнитель на УСН возмещает НДС.",
                context_after="Исполнитель на УСН возмещает НДС.", escalate_to="Главный бухгалтер")
    assert "налогов" in check_output("Добавлено возмещение НДС; нужна проверка налоговой службы.", ch, [])
    assert check_output("Добавлено возмещение НДС; подключите бухгалтерию.", ch, []) is None


def test_facts_of_neighbour_change_are_rejected():
    term = Change(kind="replace", source="tracked", clause="7.1", before="10 календарных дней", after="30 календарных дней",
                  context=CLAUSE_71.replace("30", "10").replace("Санкт-Петербурга", "Москвы"), context_after=CLAUSE_71)
    venue = Change(kind="replace", source="silent", clause="7.1", before="Москвы", after="Санкт-Петербурга")
    bad = "Срок ответа на претензию увеличен до 30 календарных дней. Споры будут решаться в суде Санкт-Петербурга."
    assert "соседней правки" in check_output(bad, term, [], [venue])
    assert check_output("Срок ответа на претензию увеличен с 10 до 30 календарных дней.", term, [], [venue]) is None


def test_model_gets_kind_and_only_the_sentence_with_the_change():
    term = Change(kind="replace", source="tracked", clause="7.1", before="10 календарных дней", after="30 календарных дней",
                  context=CLAUSE_71.replace("30", "10"), context_after=CLAUSE_71)
    stub = Stub("Срок ответа на претензию увеличен с 10 до 30 календарных дней.")
    Explainer(stub).apply(term)
    assert stub.last["вид правки"] == "заменено"
    assert "Санкт-Петербурга" not in json.dumps(stub.last, ensure_ascii=False)
    assert stub.last["предложение после правки"] == "Срок ответа на претензию - 30 календарных дней."
    silent = Change(kind="para_delete", source="silent", before=ACCEPT_TEXT, context=ACCEPT_TEXT)
    assert Explainer(stub).facts(silent)["вид правки"] == "удалён абзац без отметки в рецензировании"


def test_clause_number_in_answer_is_not_an_invented_number():
    ch = Change(kind="replace", source="tracked", clause="2.1", before="1 200 000", after="1 000 000",
                context_after="Стоимость Услуг составляет 1 000 000 рублей.")
    assert check_output("В п. 2.1 цена снижена с 1 200 000 до 1 000 000 рублей.", ch, []) is None


def test_deletion_described_with_new_text_is_rejected():
    # удалено ограничение ответственности; соседняя фраза про упущенную выгоду была и раньше — модель выдала её за новую
    ch = Change(kind="delete", source="tracked", clause="4.3", before="Ответственность ограничена ценой услуг.",
                context="Ответственность ограничена ценой услуг. Упущенная выгода не возмещается.",
                context_after="Упущенная выгода не возмещается.")
    assert check_output("Удалено ограничение ответственности. Вместо этого добавлено, что упущенная выгода не возмещается.", ch, [])
    assert check_output("Удалено ограничение ответственности. Теперь указано, что упущенная выгода не возмещается.", ch, [])
    assert check_output("Контрагент удалил ограничение ответственности ценой услуг.", ch, []) is None


def test_comment_described_as_done_edit_is_rejected():
    ch = Change(kind="comment", source="tracked", clause="4.3", before="Ответственность ограничена ценой услуг.",
                after="Просим исключить это положение.", context="Ответственность ограничена ценой услуг.")
    assert check_output("Контрагент удалил из договора пункт об ограничении ответственности.", ch, [])
    assert check_output("Контрагент просит исключить ограничение ответственности ценой услуг.", ch, []) is None
