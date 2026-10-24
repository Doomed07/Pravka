"""Генератор синтетических договоров с заранее известными правками.

Для каждой пары получаем:
  base.docx            — наша версия, отправленная контрагенту;
  theirs_tracked.docx  — версия контрагента: часть правок отмечена в рецензировании, часть внесена «тихо»;
  theirs_clean.docx    — та же версия, но без рецензирования (контрагент прислал «чистый» документ);
  truth.json           — список реальных правок: чем проверяем полноту и точность разбора.

Это проверка разбора файлов, а не качества юридических выводов на реальных договорах.
"""
from __future__ import annotations

import json
import os
import random
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

AUTHOR = "Контрагент (Иванов И.)"
DATE = "2026-10-05T10:00:00Z"

# --------------------------------------------------------------------------------------
# Шаблоны договоров: (уровень, номер, текст). Уровень 0 — заголовок раздела.
# --------------------------------------------------------------------------------------
SERVICES = [
    (0, "1", "Предмет договора"),
    (1, "1.1", "Исполнитель обязуется по заданию Заказчика оказать услуги по разработке программного обеспечения (далее – Услуги), а Заказчик обязуется принять и оплатить Услуги."),
    (1, "1.2", "Состав, объём и сроки оказания Услуг определяются Приложением № 1 к настоящему договору."),
    (0, "2", "Цена и порядок расчётов"),
    (1, "2.1", "Стоимость Услуг составляет 1 200 000 (один миллион двести тысяч) рублей, в том числе НДС 20%."),
    (1, "2.2", "Заказчик оплачивает Услуги в течение 10 рабочих дней с даты подписания Акта оказанных услуг."),
    (1, "2.3", "Предварительная оплата не предусмотрена."),
    (0, "3", "Сроки и порядок оказания Услуг"),
    (1, "3.1", "Услуги оказываются в срок до 31.12.2026."),
    (1, "3.2", "По завершении оказания Услуг Исполнитель направляет Заказчику Акт оказанных услуг. Заказчик в течение 5 рабочих дней подписывает Акт либо направляет мотивированный отказ."),
    (1, "3.3", "При отсутствии мотивированного отказа в указанный срок Услуги считаются принятыми."),
    (0, "4", "Ответственность сторон"),
    (1, "4.1", "За нарушение срока оплаты Заказчик уплачивает Исполнителю неустойку в размере 0,1% от неоплаченной суммы за каждый день просрочки, но не более 10% от суммы договора."),
    (1, "4.2", "За нарушение срока оказания Услуг Исполнитель уплачивает Заказчику неустойку в размере 0,1% от стоимости Услуг за каждый день просрочки, но не более 10% от суммы договора."),
    (1, "4.3", "Совокупная ответственность Исполнителя по договору ограничена суммой, равной стоимости Услуг. Исполнитель не возмещает Заказчику упущенную выгоду."),
    (0, "5", "Конфиденциальность и персональные данные"),
    (1, "5.1", "Стороны обязуются не разглашать конфиденциальную информацию в течение срока действия договора и 3 лет после его прекращения."),
    (1, "5.2", "Исполнитель обрабатывает персональные данные, полученные от Заказчика, только в целях исполнения договора."),
    (0, "6", "Срок действия и расторжение"),
    (1, "6.1", "Договор вступает в силу с даты подписания и действует до 31.12.2026, а в части расчётов – до полного исполнения обязательств."),
    (1, "6.2", "Каждая из сторон вправе отказаться от договора, уведомив другую сторону не менее чем за 30 календарных дней."),
    (0, "7", "Разрешение споров"),
    (1, "7.1", "Споры разрешаются в Арбитражном суде города Москвы после соблюдения претензионного порядка. Срок ответа на претензию – 10 календарных дней."),
    (1, "7.2", "Применимое право – право Российской Федерации."),
    (0, "8", "Заключительные положения"),
    (1, "8.1", "Стороны вправе обмениваться первичными документами через систему электронного документооборота."),
    (1, "8.2", "Изменения и дополнения к договору оформляются письменным соглашением сторон"),
]

RENT = [
    (0, "1", "Предмет договора"),
    (1, "1.1", "Арендодатель передаёт, а Арендатор принимает во временное владение и пользование нежилое помещение площадью 120 кв. м, расположенное по адресу: г. Москва, ул. Тверская, д. 1 (далее – Помещение)."),
    (1, "1.2", "Помещение передаётся по Акту приёма-передачи."),
    (0, "2", "Арендная плата"),
    (1, "2.1", "Арендная плата составляет 150 000 (сто пятьдесят тысяч) рублей в месяц, включая НДС 20%."),
    (1, "2.2", "Арендная плата вносится ежемесячно не позднее 5 числа месяца, за который вносится плата."),
    (1, "2.3", "Арендатор вносит обеспечительный платёж в размере 1 (одного) месячного платежа."),
    (1, "2.4", "Арендодатель вправе один раз в год индексировать арендную плату, но не более чем на 5%."),
    (0, "3", "Срок аренды и расторжение"),
    (1, "3.1", "Срок аренды составляет 11 месяцев с даты подписания Акта приёма-передачи."),
    (1, "3.2", "Арендатор вправе отказаться от договора, уведомив Арендодателя не менее чем за 30 календарных дней."),
    (1, "3.3", "Арендодатель вправе расторгнуть договор в одностороннем порядке при просрочке внесения арендной платы более чем на 10 календарных дней."),
    (0, "4", "Содержание Помещения"),
    (1, "4.1", "Текущий ремонт Помещения осуществляет Арендатор. Капитальный ремонт осуществляет Арендодатель."),
    (1, "4.2", "Коммунальные услуги оплачиваются Арендатором по показаниям счётчиков."),
    (0, "5", "Ответственность сторон"),
    (1, "5.1", "За просрочку внесения арендной платы Арендатор уплачивает неустойку в размере 0,1% от суммы задолженности за каждый день просрочки."),
    (1, "5.2", "Арендодатель отвечает перед Арендатором за недостатки Помещения, о которых он не предупредил Арендатора при заключении договора."),
    (0, "6", "Субаренда"),
    (1, "6.1", "Арендатор вправе сдавать Помещение в субаренду с уведомлением Арендодателя."),
    (0, "7", "Разрешение споров"),
    (1, "7.1", "Споры разрешаются в Арбитражном суде города Москвы."),
]

SUPPLY = [
    (0, "1", "Предмет договора"),
    (1, "1.1", "Поставщик обязуется передать в собственность Покупателя товар (далее – Товар), а Покупатель обязуется принять и оплатить Товар."),
    (1, "1.2", "Наименование, количество, цена и сроки поставки Товара указываются в Спецификации, являющейся неотъемлемой частью договора."),
    (0, "2", "Цена и порядок расчётов"),
    (1, "2.1", "Общая стоимость Товара составляет 2 400 000 (два миллиона четыреста тысяч) рублей, в том числе НДС 20%."),
    (1, "2.2", "Покупатель вносит аванс в размере 30% от стоимости Товара в течение 5 рабочих дней с даты подписания договора."),
    (1, "2.3", "Оставшуюся часть стоимости Товара Покупатель оплачивает в течение 10 рабочих дней с даты подписания товарной накладной."),
    (0, "3", "Поставка и приёмка Товара"),
    (1, "3.1", "Поставщик поставляет Товар в течение 30 календарных дней с даты получения аванса."),
    (1, "3.2", "Доставка Товара до склада Покупателя осуществляется силами Поставщика за счёт Покупателя."),
    (1, "3.3", "Покупатель принимает Товар по количеству при получении, по качеству – в течение 5 рабочих дней с даты получения."),
    (1, "3.4", "Право собственности и риск случайной гибели Товара переходят к Покупателю с даты подписания товарной накладной."),
    (0, "4", "Качество и гарантия"),
    (1, "4.1", "Гарантийный срок на Товар составляет 12 месяцев с даты поставки."),
    (1, "4.2", "Поставщик устраняет недостатки Товара в течение 20 рабочих дней с даты получения требования Покупателя."),
    (0, "5", "Ответственность сторон"),
    (1, "5.1", "За нарушение срока оплаты Покупатель уплачивает Поставщику неустойку в размере 0,1% от неоплаченной суммы за каждый день просрочки, но не более 10% от стоимости Товара."),
    (1, "5.2", "За нарушение срока поставки Поставщик уплачивает Покупателю неустойку в размере 0,1% от стоимости непоставленного Товара за каждый день просрочки, но не более 10% от стоимости Товара."),
    (1, "5.3", "Совокупная ответственность Поставщика по договору ограничена суммой, равной стоимости Товара. Поставщик не возмещает Покупателю упущенную выгоду."),
    (0, "6", "Форс-мажор"),
    (1, "6.1", "Сторона, для которой наступили обстоятельства непреодолимой силы, уведомляет об этом другую сторону в течение 5 рабочих дней."),
    (0, "7", "Срок действия и расторжение"),
    (1, "7.1", "Договор действует до 31.12.2026, а в части расчётов – до полного исполнения обязательств."),
    (1, "7.2", "Покупатель вправе отказаться от договора при просрочке поставки более чем на 30 календарных дней."),
    (0, "8", "Разрешение споров"),
    (1, "8.1", "Споры разрешаются в Арбитражном суде города Москвы после соблюдения претензионного порядка. Срок ответа на претензию – 10 календарных дней."),
]


# Преамбулы: в рабочих договорах стороны описаны до первого пункта, по ним определяется наша сторона (C9).
PREAMBLES = {
    "services": [
        "ДОГОВОР ОКАЗАНИЯ УСЛУГ № 12/2026",
        "г. Москва                                                                                          01.10.2026",
        "Общество с ограниченной ответственностью «Альфа Софт», ИНН 7701234567, ОГРН 1027700000001, именуемое в дальнейшем "
        "«Исполнитель», в лице генерального директора Петрова Петра Петровича, действующего на основании Устава, с одной стороны, "
        "и Акционерное общество «Бета Групп», ИНН 7702345678, ОГРН 1027700000002, именуемое в дальнейшем «Заказчик», в лице "
        "директора Сидорова Сергея Сергеевича, действующего на основании Устава, с другой стороны, заключили настоящий "
        "договор о нижеследующем:",
    ],
    "rent": [
        "ДОГОВОР АРЕНДЫ НЕЖИЛОГО ПОМЕЩЕНИЯ № 7/2026",
        "г. Москва                                                                                          01.10.2026",
        "Акционерное общество «Дельта Недвижимость», ИНН 7703456789, именуемое в дальнейшем «Арендодатель», в лице директора "
        "Орлова Олега Олеговича, действующего на основании Устава, с одной стороны, и Общество с ограниченной ответственностью "
        "«Гамма Торг», ИНН 7704567890, именуемое в дальнейшем «Арендатор», в лице генерального директора Волкова Владимира "
        "Владимировича, действующего на основании Устава, с другой стороны, заключили настоящий договор о нижеследующем:",
    ],
    "supply": [
        "ДОГОВОР ПОСТАВКИ № 21/2026",
        "г. Москва                                                                                          01.10.2026",
        "Общество с ограниченной ответственностью «Омега Снаб», ИНН 7705678901, ОГРН 1027700000005, именуемое в дальнейшем "
        "«Поставщик», в лице генерального директора Николаева Николая Николаевича, действующего на основании Устава, с одной "
        "стороны, и Акционерное общество «Сигма Завод», ИНН 7706789012, ОГРН 1027700000006, именуемое в дальнейшем «Покупатель», "
        "в лице директора Фёдорова Фёдора Фёдоровича, действующего на основании Устава, с другой стороны, заключили настоящий "
        "договор о нижеследующем:",
    ],
}

# Кто мы в синтетических договорах: роль совпадает с примерами плейбуков (services — Исполнитель, rent — Арендатор).
OUR_COMPANY = {
    "services": {"role": "Исполнитель", "names": ["Общество с ограниченной ответственностью «Альфа Софт»"], "inn": ["7701234567"]},
    "rent": {"role": "Арендатор", "names": ["ООО «Гамма Торг»"], "inn": ["7704567890"]},
    "supply": {"role": "Поставщик", "names": ["ООО «Омега Снаб»"], "inn": ["7705678901"]},
}


@dataclass(frozen=True)
class EditSpec:
    key: str
    clause: str
    op: str  # replace | append | delete_text | delete_para | insert_para | comment
    old: str = ""
    new: str = ""
    topic: str = ""
    important: bool = True
    expect: str = ""  # ожидаемый уровень по примерному плейбуку: accept | fallback | reject | review
    excl: str = ""  # правки с одинаковым excl не комбинируются


SERVICES_EDITS = [
    EditSpec("price", "2.1", "replace", "1 200 000", "1 000 000", "цена и сумма договора", True, "reject"),
    EditSpec("vat", "2.1", "replace", "НДС 20%", "НДС не облагается", "налоги", True, "review"),
    EditSpec("pay60", "2.2", "replace", "10 рабочих дней", "60 календарных дней", "порядок и сроки оплаты", True, "reject", "2.2"),
    EditSpec("pay7", "2.2", "replace", "10 рабочих дней", "7 рабочих дней", "порядок и сроки оплаты", True, "accept", "2.2"),
    EditSpec("date31", "3.1", "replace", "31.12.2026", "31.03.2027", "сроки исполнения", True, "review"),
    EditSpec("acc15", "3.2", "replace", "5 рабочих дней", "15 рабочих дней", "приёмка и качество", True, "reject"),
    EditSpec("deemed", "3.3", "delete_para", topic="приёмка и качество", expect="reject"),
    EditSpec("pen001", "4.1", "replace", "0,1%", "0,01%", "неустойка и штрафы", True, "reject"),
    EditSpec("pen05", "4.2", "replace", "0,1%", "0,5%", "неустойка и штрафы", True, "reject", "4.2"),
    EditSpec("pen005", "4.2", "replace", "0,1%", "0,05%", "неустойка и штрафы", True, "accept", "4.2"),
    EditSpec("cap_del", "4.3", "delete_text", "Совокупная ответственность Исполнителя по договору ограничена суммой, равной стоимости Услуг. ",
             "", "ограничение ответственности", True, "reject", "4.3"),
    EditSpec("lost_profit", "4.3", "delete_text", " Исполнитель не возмещает Заказчику упущенную выгоду.", "",
             "ограничение ответственности", True, "reject", "4.3"),
    EditSpec("cap3x", "4.3", "replace", "суммой, равной стоимости Услуг", "суммой, равной 3-кратной стоимости Услуг",
             "ограничение ответственности", True, "reject", "4.3"),
    EditSpec("comment43", "4.3", "comment", new="Просим исключить это положение, для нас оно неприемлемо.",
             topic="ограничение ответственности", expect="review"),
    EditSpec("conf10", "5.1", "replace", "3 лет", "10 лет", "конфиденциальность", True, "reject", "5.1"),
    EditSpec("conf5", "5.1", "replace", "3 лет", "5 лет", "конфиденциальность", True, "fallback", "5.1"),
    EditSpec("pd_third", "5.2", "append", new=" Исполнитель вправе передавать такие данные третьим лицам.",
             topic="персональные данные и ИБ", expect="review"),
    EditSpec("term5", "6.2", "replace", "30 календарных дней", "5 календарных дней", "расторжение и отказ от договора", True, "reject", "6.2"),
    EditSpec("term45", "6.2", "replace", "30 календарных дней", "45 календарных дней", "расторжение и отказ от договора", True, "accept", "6.2"),
    EditSpec("valid", "6.1", "replace", "действует до 31.12.2026", "действует до 30.06.2026", "срок действия договора", True, "review"),
    EditSpec("court", "7.1", "replace", "Арбитражном суде города Москвы", "Арбитражном суде города Казани", "разрешение споров", True, "review"),
    EditSpec("claim30", "7.1", "replace", "10 календарных дней", "30 календарных дней", "разрешение споров", True, "fallback"),
    EditSpec("tax_ins", "2.3", "insert_para", new="Исполнитель, применяющий УСН, обязан возместить Заказчику сумму НДС, не принятую к вычету.",
             topic="налоги", expect="review"),
    EditSpec("admin", "5.2", "insert_para", new="Исполнитель предоставляет Заказчику доступ к своей информационной системе с правами администратора.",
             topic="персональные данные и ИБ", expect="reject"),
    EditSpec("unilateral", "8.2", "insert_para", new="Заказчик вправе в одностороннем порядке изменять объём Услуг и сроки их оказания, уведомив Исполнителя за 3 рабочих дня.",
             topic="односторонние изменения условий", expect="reject"),
    # опечатка внутри слова — техническая правка; смена падежа существительного — решает юрист (решение 2026-10-23)
    EditSpec("typo", "1.1", "replace", "разработке", "разроботке", "", False, "accept", excl="w1.1"),
    EditSpec("noun_form", "1.1", "replace", "разработке", "разработки", "", True, "review", excl="w1.1"),
    EditSpec("punct", "8.2", "append", new=".", topic="", important=False, expect="accept", excl="8.2p"),
]

RENT_EDITS = [
    EditSpec("rent165", "2.1", "replace", "150 000", "165 000", "арендная плата и индексация", True, "reject"),
    EditSpec("rent_vat", "2.1", "replace", "включая НДС 20%", "без НДС", "налоги", True, "review"),
    EditSpec("deposit3", "2.3", "replace", "1 (одного)", "3 (трёх)", "порядок и сроки оплаты", True, "reject"),
    EditSpec("index15", "2.4", "replace", "5%", "15%", "арендная плата и индексация", True, "reject", "2.4"),
    EditSpec("index7", "2.4", "replace", "5%", "7%", "арендная плата и индексация", True, "fallback", "2.4"),
    EditSpec("term5m", "3.1", "replace", "11 месяцев", "5 месяцев", "срок действия договора", True, "reject"),
    EditSpec("notice90", "3.2", "replace", "30 календарных дней", "90 календарных дней", "расторжение и отказ от договора", True, "reject", "3.2"),
    EditSpec("notice45", "3.2", "replace", "30 календарных дней", "45 календарных дней", "расторжение и отказ от договора", True, "fallback", "3.2"),
    EditSpec("late3", "3.3", "replace", "10 календарных дней", "3 календарных дней", "расторжение и отказ от договора", True, "reject"),
    EditSpec("repair", "4.1", "replace", "Капитальный ремонт осуществляет Арендодатель", "Капитальный ремонт осуществляет Арендатор",
             "содержание и ремонт имущества", True, "review"),
    EditSpec("utilities", "4.2", "replace", "по показаниям счётчиков", "по тарифам, установленным Арендодателем",
             "арендная плата и индексация", True, "review"),
    EditSpec("pen05", "5.1", "replace", "0,1%", "0,5%", "неустойка и штрафы", True, "reject"),
    EditSpec("no_liab", "5.2", "insert_para", new="Арендодатель не несёт ответственности за сохранность имущества Арендатора в Помещении.",
             topic="ограничение ответственности", expect="reject"),
    EditSpec("sublease", "6.1", "replace", "вправе сдавать", "не вправе сдавать", "субподряд, субаренда, передача прав", True, "reject"),
    EditSpec("court", "7.1", "replace", "Арбитражном суде города Москвы", "Арбитражном суде Санкт-Петербурга и Ленинградской области",
             "разрешение споров", True, "review"),
    EditSpec("typo", "1.2", "replace", "Помещение передаётся", "Помещение передаеться", "", False, "accept", excl="w1.2"),
    EditSpec("noun_form", "1.2", "replace", "Помещение передаётся", "Помещения передаётся", "", True, "review", excl="w1.2"),
    EditSpec("comment", "5.1", "comment", new="Ставку неустойки просим пересмотреть.", topic="неустойка и штрафы", expect="review"),
]

# Поставка: ожидаемые уровни — по плейбуку playbooks/supply_example.yaml (мы — Поставщик).
SUPPLY_EDITS = [
    EditSpec("price", "2.1", "replace", "2 400 000", "2 000 000", "цена и сумма договора", True, "reject", "2.1p"),
    EditSpec("price_small", "2.1", "replace", "2 400 000", "2 350 000", "цена и сумма договора", True, "fallback", "2.1p"),
    EditSpec("vat", "2.1", "replace", "НДС 20%", "НДС 0%", "налоги", True, "review"),
    EditSpec("adv10", "2.2", "replace", "30%", "10%", "порядок и сроки оплаты", True, "reject", "2.2"),
    EditSpec("adv20", "2.2", "replace", "30%", "20%", "порядок и сроки оплаты", True, "fallback", "2.2"),
    EditSpec("adv_del", "2.2", "delete_para", topic="порядок и сроки оплаты", expect="reject", excl="2.2"),
    EditSpec("pay45", "2.3", "replace", "10 рабочих дней", "45 календарных дней", "порядок и сроки оплаты", True, "reject", "2.3"),
    EditSpec("pay5", "2.3", "replace", "10 рабочих дней", "5 рабочих дней", "порядок и сроки оплаты", True, "accept", "2.3"),
    EditSpec("ship10", "3.1", "replace", "30 календарных дней", "10 календарных дней", "сроки исполнения", True, "reject", "3.1"),
    EditSpec("ship45", "3.1", "replace", "30 календарных дней", "45 календарных дней", "сроки исполнения", True, "accept", "3.1"),
    EditSpec("qual20", "3.3", "replace", "5 рабочих дней", "20 рабочих дней", "приёмка и качество", True, "reject", "3.3"),
    EditSpec("risk", "3.4", "replace", "с даты подписания товарной накладной", "с даты полной оплаты Товара",
             "переход права собственности и риска", True, "reject"),
    EditSpec("warranty24", "4.1", "replace", "12 месяцев", "24 месяцев", "приёмка и качество", True, "reject", "4.1"),
    EditSpec("fix5", "4.2", "replace", "20 рабочих дней", "5 рабочих дней", "приёмка и качество", True, "reject", "4.2"),
    EditSpec("pen001", "5.1", "replace", "0,1%", "0,01%", "неустойка и штрафы", True, "reject"),
    EditSpec("pen05", "5.2", "replace", "0,1%", "0,5%", "неустойка и штрафы", True, "reject", "5.2"),
    EditSpec("pen005", "5.2", "replace", "0,1%", "0,05%", "неустойка и штрафы", True, "accept", "5.2"),
    EditSpec("cap_del", "5.3", "delete_text", "Совокупная ответственность Поставщика по договору ограничена суммой, равной стоимости Товара. ",
             "", "ограничение ответственности", True, "reject", "5.3"),
    EditSpec("lost_profit", "5.3", "delete_text", " Поставщик не возмещает Покупателю упущенную выгоду.", "",
             "ограничение ответственности", True, "reject", "5.3"),
    EditSpec("comment53", "5.3", "comment", new="Просим исключить ограничение ответственности.",
             topic="ограничение ответственности", expect="review"),
    EditSpec("refuse10", "7.2", "replace", "30 календарных дней", "10 календарных дней", "расторжение и отказ от договора", True, "reject"),
    EditSpec("court", "8.1", "replace", "Арбитражном суде города Москвы", "Арбитражном суде Новосибирской области",
             "разрешение споров", True, "review"),
    EditSpec("claim30", "8.1", "replace", "10 календарных дней", "30 календарных дней", "разрешение споров", True, "fallback"),
    EditSpec("storage", "3.2", "insert_para", new="При отказе Покупателя принять Товар Поставщик хранит Товар за свой счёт в течение 60 календарных дней.",
             topic="приёмка и качество", expect="review"),
    EditSpec("typo", "1.1", "replace", "собственность", "собсвенность", "", False, "accept"),
    EditSpec("grammar", "3.4", "replace", "переходят", "переходит", "", False, "accept"),
]

TEMPLATES = {"services": (SERVICES, SERVICES_EDITS), "rent": (RENT, RENT_EDITS), "supply": (SUPPLY, SUPPLY_EDITS)}


# --------------------------------------------------------------------------------------
# Модель абзаца для генерации
# --------------------------------------------------------------------------------------
@dataclass
class GSeg:
    kind: str  # equal | ins | del
    text: str


@dataclass
class GPara:
    level: int
    label: str
    segs: list[GSeg]
    heading: bool = False
    mark: str = ""
    comment: int | None = None
    plain: bool = False  # абзац без нумерации и стиля заголовка (преамбула)

    def text(self) -> str:
        return "".join(s.text for s in self.segs if s.kind in ("equal", "ins"))


def build_paragraphs(tpl, numbering: str, preamble: list[str] | None = None) -> list[GPara]:
    out = [GPara(level=0, label="", segs=[GSeg("equal", t)], plain=True) for t in (preamble or [])]
    for level, label, text in tpl:
        body = text if numbering == "auto" else (f"{label}. {text}" if level == 0 else f"{label}. {text}")
        out.append(GPara(level=level, label=label, segs=[GSeg("equal", body)], heading=(level == 0)))
    return out


def find_clause(paras: list[GPara], clause: str) -> int:
    for i, p in enumerate(paras):
        if p.label == clause and not p.mark == "ins":
            return i
    raise KeyError(clause)


def _split_equal(p: GPara, old: str) -> int:
    for i, s in enumerate(p.segs):
        if s.kind == "equal" and old in s.text:
            return i
    raise ValueError(f"в абзаце {p.label} нет текста {old!r}")


def apply_edit(paras: list[GPara], e: EditSpec, tracked: bool, numbering: str, comments: list[tuple[str, str]]) -> dict:
    """Применить правку к списку абзацев. Возвращает ключи для сопоставления с результатом разбора."""
    if e.op == "insert_para":
        i = find_clause(paras, e.clause)
        section = e.clause.split(".")[0]
        # вставляем после последнего пункта раздела; номер — следующий
        last = i
        while last + 1 < len(paras) and paras[last + 1].label.split(".")[0] == section and not paras[last + 1].heading:
            last += 1
        n = int(paras[last].label.split(".")[1]) + 1 if paras[last].level == 1 else 1
        label = f"{section}.{n}"
        body = e.new if numbering == "auto" else f"{label}. {e.new}"
        kind = "ins" if tracked else "equal"
        gp = GPara(level=1, label=label, segs=[GSeg(kind, body)], mark="ins" if tracked else "")
        paras.insert(last + 1, gp)
        return {"clause": label, "kind": "para_insert", "before": "", "after": e.new}

    i = find_clause(paras, e.clause)
    p = paras[i]
    if e.op == "delete_para":
        text = p.text()
        if tracked:
            p.segs = [GSeg("del", s.text) for s in p.segs if s.kind != "ins"]
            p.mark = "del"
        else:
            paras.pop(i)
        body = text
        if numbering != "auto":
            body = text.split(". ", 1)[1] if ". " in text else text
        return {"clause": e.clause, "kind": "para_delete", "before": body, "after": ""}
    if e.op == "comment":
        idx = len(comments)
        comments.append((AUTHOR, e.new))
        p.comment = idx
        return {"clause": e.clause, "kind": "comment", "before": "", "after": e.new}
    if e.op == "append":
        if tracked:
            p.segs.append(GSeg("ins", e.new))
        else:
            if p.segs and p.segs[-1].kind == "equal":
                p.segs[-1].text += e.new
            else:
                p.segs.append(GSeg("equal", e.new))
        return {"clause": e.clause, "kind": "insert", "before": "", "after": e.new.strip()}
    j = _split_equal(p, e.old)
    seg = p.segs[j]
    pre, post = seg.text.split(e.old, 1)
    new_segs = []
    if pre:
        new_segs.append(GSeg("equal", pre))
    if e.op == "replace":
        if tracked:
            new_segs += [GSeg("del", e.old), GSeg("ins", e.new)]
        else:
            new_segs.append(GSeg("equal", e.new))
    elif e.op == "delete_text":
        if tracked:
            new_segs.append(GSeg("del", e.old))
    if post:
        new_segs.append(GSeg("equal", post))
    p.segs[j:j + 1] = new_segs
    # склеиваем соседние равные куски
    merged: list[GSeg] = []
    for s in p.segs:
        if merged and merged[-1].kind == "equal" and s.kind == "equal":
            merged[-1].text += s.text
        else:
            merged.append(GSeg(s.kind, s.text))
    p.segs = merged
    kind = "replace" if e.op == "replace" else "delete"
    return {"clause": e.clause, "kind": kind, "before": e.old.strip(), "after": e.new.strip()}


# --------------------------------------------------------------------------------------
# Запись docx
# --------------------------------------------------------------------------------------
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W_NS}>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/></w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {W_NS}>
<w:abstractNum w:abstractNumId="0">
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2."/></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""


class _Ids:
    def __init__(self):
        self.n = 100

    def next(self) -> int:
        self.n += 1
        return self.n


def _t(text: str, deleted: bool = False) -> str:
    tag = "w:delText" if deleted else "w:t"
    return f'<{tag} xml:space="preserve">{escape(text)}</{tag}>'


def _chunks(text: str, rng: random.Random) -> list[str]:
    """Разбить текст на несколько прогонов в случайных местах, как это делает Word."""
    out, i = [], 0
    while i < len(text):
        step = rng.randint(8, 40)
        out.append(text[i:i + step])
        i += step
    return out or [""]


def _para_xml(p: GPara, ids: _Ids, rng: random.Random, numbering: str, noise: bool) -> str:
    ppr = ""
    if p.heading:
        ppr += '<w:pStyle w:val="Heading1"/>'
    if numbering == "auto" and not p.plain:
        ppr += f'<w:numPr><w:ilvl w:val="{p.level}"/><w:numId w:val="1"/></w:numPr>'
    if p.mark:
        ppr += f'<w:rPr><w:{p.mark} w:id="{ids.next()}" w:author="{AUTHOR}" w:date="{DATE}"/></w:rPr>'
    body = ""
    if p.comment is not None:
        body += f'<w:commentRangeStart w:id="{p.comment}"/>'
    for s in p.segs:
        if s.kind == "equal":
            for ch in _chunks(s.text, rng) if noise else [s.text]:
                body += f"<w:r>{_t(ch)}</w:r>"
                if noise and rng.random() < 0.15:
                    body += '<w:proofErr w:type="spellStart"/>'
        elif s.kind == "ins":
            body += f'<w:ins w:id="{ids.next()}" w:author="{AUTHOR}" w:date="{DATE}"><w:r>{_t(s.text)}</w:r></w:ins>'
        else:
            body += f'<w:del w:id="{ids.next()}" w:author="{AUTHOR}" w:date="{DATE}"><w:r>{_t(s.text, True)}</w:r></w:del>'
    if p.comment is not None:
        body += f'<w:commentRangeEnd w:id="{p.comment}"/><w:r><w:commentReference w:id="{p.comment}"/></w:r>'
    return f"<w:p><w:pPr>{ppr}</w:pPr>{body}</w:p>"


def write_docx(path: str, paras: list[GPara], comments: list[tuple[str, str]], numbering: str, rng: random.Random,
               noise: bool = True) -> None:
    ids = _Ids()
    body = "".join(_para_xml(p, ids, rng, numbering, noise) for p in paras)
    if noise and rng.random() < 0.5:
        body = '<w:p><w:pPr/></w:p>' + body  # пустой абзац в начале, как часто бывает
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W_NS}><w:body>{body}<w:sectPr/></w:body></w:document>'
    com = "".join(
        f'<w:comment w:id="{i}" w:author="{escape(a)}" w:date="{DATE}"><w:p><w:r>{_t(t)}</w:r></w:p></w:comment>'
        for i, (a, t) in enumerate(comments)
    )
    com_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments {W_NS}>{com}</w:comments>'
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/_rels/document.xml.rels", DOC_RELS)
        zf.writestr("word/document.xml", doc)
        zf.writestr("word/styles.xml", STYLES)
        zf.writestr("word/numbering.xml", NUMBERING)
        zf.writestr("word/comments.xml", com_xml)


# --------------------------------------------------------------------------------------
# Сборка пары документов
# --------------------------------------------------------------------------------------
def pick_edits(edits: list[EditSpec], rng: random.Random, p: float = 0.6) -> list[EditSpec]:
    chosen, used = [], set()
    for e in edits:
        if e.excl and e.excl in used:
            continue
        if rng.random() < p:
            chosen.append(e)
            if e.excl:
                used.add(e.excl)
    return chosen


def generate_case(out_dir: str, template: str, seed: int, numbering: str | None = None, p: float = 0.6,
                  silent_share: float = 0.25) -> dict:
    rng = random.Random(seed)
    tpl, catalog = TEMPLATES[template]
    numbering = numbering or rng.choice(["auto", "manual"])
    chosen = pick_edits(catalog, rng, p)
    if len(chosen) < 4:
        chosen = pick_edits(catalog, rng, 0.9)
    delivery = {e.key: ("silent" if (e.op != "comment" and rng.random() < silent_share) else "tracked") for e in chosen}

    pre = PREAMBLES.get(template)
    base = build_paragraphs(tpl, numbering, pre)
    tracked = build_paragraphs(tpl, numbering, pre)
    clean = build_paragraphs(tpl, numbering, pre)
    c_tracked: list[tuple[str, str]] = []
    c_clean: list[tuple[str, str]] = []
    truth_edits = []
    # применяем в порядке документа
    order = {lbl: i for i, (_, lbl, _) in enumerate(tpl)}
    for e in sorted(chosen, key=lambda x: (order.get(x.clause, 0), x.key)):
        d = delivery[e.key]
        info = apply_edit(tracked, e, tracked=(d == "tracked"), numbering=numbering, comments=c_tracked)
        if e.op != "comment":
            apply_edit(clean, e, tracked=False, numbering=numbering, comments=c_clean)
        truth_edits.append({
            "key": e.key, "topic": e.topic, "important": e.important, "expect": e.expect, "op": e.op,
            "source_tracked": "tracked" if (d == "tracked") else "silent",
            "source_clean": None if e.op == "comment" else "diff",
            **info,
        })
    os.makedirs(out_dir, exist_ok=True)
    paths = {
        "base": os.path.join(out_dir, "base.docx"),
        "tracked": os.path.join(out_dir, "theirs_tracked.docx"),
        "clean": os.path.join(out_dir, "theirs_clean.docx"),
        "truth": os.path.join(out_dir, "truth.json"),
    }
    write_docx(paths["base"], base, [], numbering, random.Random(seed + 1))
    write_docx(paths["tracked"], tracked, c_tracked, numbering, random.Random(seed + 2))
    write_docx(paths["clean"], clean, [], numbering, random.Random(seed + 3))
    truth = {"template": template, "seed": seed, "numbering": numbering, "edits": truth_edits}
    with open(paths["truth"], "w", encoding="utf-8") as f:
        json.dump(truth, f, ensure_ascii=False, indent=2)
    return {"paths": paths, "truth": truth, "company": OUR_COMPANY.get(template)}


def side_config(case: dict):
    """Профиль нашей компании для синтетического договора: по нему определяется сторона (C9)."""
    from .parties import CompanyProfile, SideConfig

    c = case.get("company") or {}
    return SideConfig(profile=CompanyProfile(names=list(c.get("names", [])), inns=list(c.get("inn", []))))
