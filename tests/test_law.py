"""ГК РФ для подсказок: разбор страницы ИПС pravo.gov.ru и сверка сохранённого текста с КонсультантПлюс."""
import os
import re

from pravki.law import load_jsonl, parse_ips

LAW = os.path.join(os.path.dirname(__file__), "..", "pravki", "law")

PAGE = """
<p class="H">Раздел IV. Отдельные виды обязательств</p><p class="H">Глава 30. Купля-продажа</p>
<p class="H">§ 3. Поставка товаров</p><p>&nbsp;</p>
<p class="H">Статья 506. Договор поставки</p><p>&nbsp;</p>
<p>По договору поставки поставщик&nbsp;- продавец обязуется передать товары.</p>
<p class="H">Статья 406<span class="W9" style="">1</span>. Возмещение потерь</p>
<p>1.&nbsp;Стороны могут предусмотреть обязанность возместить потери.<span class="mark" style="">&nbsp;(В редакции Федерального закона
<a class="doclink" href="?x">от&nbsp;08.03.2015&nbsp;№&nbsp;42-ФЗ</a>)</span></p>
<p>Абзац продолжения первого пункта:</p><p>подпункт без номера;</p>
<p>2.&nbsp;(Пункт утратил силу - Федеральный закон от 01.01.2020 № 1-ФЗ)</p>
<p>3.&nbsp;Третий пункт. (Дополнение пунктом - Федеральный закон от 18.03.2019 № 34-ФЗ)</p>
<p class="H">Статья 91. (Утратила силу - Федеральный закон от 05.05.2014 № 99-ФЗ)</p>
"""


def test_parse_structure_superscript_and_notes():
    arts = {a.number: a for a in parse_ips(PAGE)}
    s = arts["506"]
    assert (s.title, s.chapter, s.paragraph, s.section) == ("Договор поставки", "Глава 30. Купля-продажа", "§ 3. Поставка товаров",
                                                             "Раздел IV. Отдельные виды обязательств")
    assert [p.number for p in s.points] == [""] and "поставщик - продавец" in s.points[0].text
    a = arts["406.1"]  # надстрочный номер
    assert a.title == "Возмещение потерь" and not a.lost
    assert [p.number for p in a.points] == ["1", "3"]  # п. 2 утратил силу и в поиск не идёт
    assert a.points[0].text.endswith("подпункт без номера;") and "редакции" not in a.points[0].text
    assert a.points[1].text == "3. Третий пункт."  # пометка «Дополнение пунктом …» убрана
    assert a.edited == "2020-01-01"  # последняя дата редакции
    assert arts["91"].lost and not arts["91"].points


def test_saved_gk_covers_all_parts():
    arts = load_jsonl(os.path.join(LAW, "gk.jsonl"))
    nums = [a.number for a in arts]
    assert len(nums) == len(set(nums))
    by = {a.number: a for a in arts}
    for n in ("1", "330", "406.1", "431.1", "454", "506", "779", "783.1", "1109", "1110", "1225", "1541"):
        assert n in by and not by[n].lost, n
    assert all(p.text and "Федеральный закон от" not in p.text[-60:] for a in arts for p in a.points)


def _consultant(name):
    """Статьи из выгрузки КонсультантПлюс (сверена со страницей по контрольной сумме): номер → текст."""
    out, cur = {}, None
    for line in open(os.path.join(LAW, name), encoding="utf-8").read().split("\n"):
        m = re.match(r"Статья (\d+(?:\.\d+)?)\. ", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        else:
            out[cur].append(line)
    return {k: " ".join(v) for k, v in out.items()}


def test_saved_gk_matches_consultant_for_supply_and_services():
    by = {a.number: a for a in load_jsonl(os.path.join(LAW, "gk.jsonl"))}

    def norm(s):  # портал пишет «поставщик - продавец», КонсультантПлюс — «поставщик-продавец»
        return re.sub(r"\s+", " ", s.replace(" - ", "-")).strip()

    for name in ("gk_supply.txt", "gk_services.txt"):
        for num, text in _consultant(name).items():
            assert norm(" ".join(p.text for p in by[num].points)) == norm(text), num
