"""Обезличивание docx: названия, ФИО, реквизиты, контакты, авторы правок, свойства файла.

Зачем. Реальные договоры нельзя класть в репозиторий и отправлять в облако как есть. Обезличенная копия
сохраняет структуру, рецензирование (вставки, удаления, комментарии), числа, сроки и проценты условий и меняет
только то, что называет людей и компании, поэтому на ней можно проверять разбор и собирать золотой набор.

Что заменяется:
  * названия организаций с формой собственности и названия в кавычках после неё («Альфа Софт» → «Организация-1»);
    иностранные наименования (Ltd, LLC, GmbH…) → Foreign … Ltd;
  * ФИО в любом падеже, «Фамилия И.О.», «ИП Фамилия Имя» → вымышленные (падеж не сохраняется);
  * ИНН, КПП, ОГРН, БИК, счета, паспорт, любые числа из 9 и более цифр → цифры той же длины;
  * телефоны и числа в коротких строках с «тел.», «факс», «почта»; e-mail; ссылки и адреса сайтов;
  * названия улиц и почтовые индексы;
  * авторы правок и комментариев (по карте «автор → роль», остальные → «Автор-N»);
  * свойства файла (автор, организация, заголовки), миниатюра, пользовательские свойства, customXml,
    картинки (заменяются пустой), адреса внешних ссылок и шаблона.
Одно и то же имя везде заменяется одним и тем же значением, поэтому пары версий остаются парами.

Чего не делает (честно). Название, которого нет рядом с формой собственности (бренд, мероприятие, продукт),
само не находится: такие слова выводит `residual_candidates`, их добавляют вручную через `terms`.
Проверка `scan_leaks` ищет в готовом файле всё, что было найдено и заменено, но не гарантирует, что в договоре
не осталось ничего, чего программа не знает. Перед использованием файл нужно просмотреть глазами.
Карта соответствий (`Anonymizer.to_json`) содержит исходные данные: хранить только на своём компьютере.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field

from lxml import etree

from .docx_reader import MAX_PART, W, DocxError, q
from .parties import _LEGAL, _NAME_FOREIGN, is_known_role, is_numbered_role

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

TEXT_PARTS = re.compile(r"^word/(document|comments\w*|footnotes|endnotes|header\d*|footer\d*)\.xml$")
PEOPLE_PARTS = re.compile(r"^word/people\w*\.xml$")
DROP_PREFIXES = ("customXml/", "docProps/thumbnail", "docProps/custom.xml")
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001"
    "e221bc330000000049454e44ae426082")
JPG_1X1 = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f14"
    "1d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100"
    "ffc4001f0000010501010101010100000000000000000102030405060708090a0bffda0008010100003f00d2cf20ffd9")

MALE_SURNAMES = ["Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов", "Попов", "Васильев", "Соколов", "Михайлов", "Новиков",
                 "Фёдоров", "Морозов", "Волков", "Алексеев", "Лебедев", "Семёнов", "Егоров", "Павлов", "Козлов", "Степанов",
                 "Николаев", "Орлов", "Андреев", "Макаров", "Захаров", "Зайцев", "Соловьёв", "Борисов"]
FEMALE_SURNAMES = [s + "а" for s in MALE_SURNAMES]
MALE_NAMES = ["Иван", "Пётр", "Сергей", "Алексей", "Андрей", "Дмитрий", "Николай", "Михаил", "Владимир", "Олег", "Виктор",
              "Роман", "Максим", "Артём", "Евгений", "Павел", "Денис", "Игорь", "Антон", "Кирилл", "Глеб", "Тимур", "Руслан",
              "Станислав", "Вадим", "Леонид", "Борис", "Юрий"]
FEMALE_NAMES = ["Анна", "Мария", "Елена", "Ольга", "Наталья", "Татьяна", "Ирина", "Светлана", "Екатерина", "Юлия", "Оксана",
                "Марина", "Алла", "Вера", "Галина", "Диана", "Инна", "Кира", "Лариса", "Нина", "Полина", "Раиса", "Софья",
                "Тамара", "Ульяна", "Фаина", "Эльвира", "Яна"]
MALE_PATR = ["Иванович", "Петрович", "Сергеевич", "Алексеевич", "Андреевич", "Дмитриевич", "Николаевич", "Михайлович",
             "Владимирович", "Олегович", "Викторович", "Романович", "Максимович", "Евгеньевич", "Павлович", "Денисович",
             "Игоревич", "Антонович", "Кириллович", "Артёмович", "Глебович", "Тимурович", "Русланович", "Станиславович",
             "Вадимович", "Леонидович", "Борисович", "Юрьевич"]
FEMALE_PATR = [x[:-2] + "на" for x in MALE_PATR]
GREEK = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa", "Lambda", "Mu", "Nu", "Xi"]

_VOWELS = "аяоеуюыиьй"
# Форма организации в любом падеже, затем (возможно, с парой слов между) название в кавычках.
_ORG_FORMS = (r"(?:Обществ[а-я]*\s+с\s+ограниченной\s+ответственностью|Акционерн[а-я]+\s+обществ[а-я]*|"
              r"Индивидуальн[а-я]+\s+предпринимател[а-я]*|Некоммерческ[а-я]+\s+организаци[а-я]*|"
              r"ООО|ПАО|НАО|АО|ЗАО|ОАО|ИП|НКО|АНО|ФГУП|МУП|ГУП|ГБУ|ФГБУ|ФГБОУ|ГК|"
              r"Банк[а-я]*|Фирм[а-я]*|Компани[а-я]*|Корпораци[а-я]*|Фонд[а-я]*|Ассоциаци[а-я]*|Университет[а-я]*)")
_ORG_QUOTED = re.compile(r"(?<![А-ЯЁа-яё])(?P<form>" + _ORG_FORMS + r")(?![а-яё])[^«\"“,;.]{0,40}?[«\"“](?P<name>[^»\"”]{1,80})[»\"”]")
_PATR = r"[А-ЯЁ][а-яё]+(?:ович|евич|ьич|ич|овн|евн|ичн)[а-яё]{0,3}"
_FIO = re.compile(r"(?<![А-ЯЁа-яё])([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ][а-яё]{2,})\s+(" + _PATR + r")(?![А-ЯЁа-яё])")
_IP2 = re.compile(r"(?:Индивидуальный\s+предприниматель|ИП)\s+([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ][а-яё]{2,})(?![А-ЯЁа-яё]|\s*\.)")
_SURNAME_INIT = re.compile(r"(?<![А-ЯЁа-яё])([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ])\.\s?([А-ЯЁ])\.?")
_INIT_SURNAME = re.compile(r"(?<![А-ЯЁа-яё])([А-ЯЁ])\.\s?([А-ЯЁ])\.?\s*([А-ЯЁ][а-яё]{2,})(?![А-ЯЁа-яё])")

_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>)»\"'”]+", re.IGNORECASE)
_DOMAIN = re.compile(r"(?<![\w@.\-])(?:[a-zA-Z0-9\-]+\.)+(?:ru|com|org|net|su|io|рф|info|biz|pro|shop|store|online)(?![\w\-])")
_LABELED_ID = re.compile(
    r"(?i:ИНН|КПП|ОГРНИП|ОГРН|БИК|ОКПО|ОКТМО|СНИЛС|р/с|к/с|р\.\s*с\.|к\.\s*с\.|"
    r"(?:расч[её]тн\w+|корреспондентск\w+)\s+сч[её]т\w*|сч[её]т\w*)\s*[:№N.]*\s*(?P<d>\d[\d\s\-]{4,}\d)")
_LONG_DIGITS = re.compile(r"(?<![\d,.])\d{9,}(?![\d])")
_PASSPORT = re.compile(r"(?i:паспорт)[^.;]{0,80}")
_PHONE_EXPLICIT = re.compile(r"(?<![\d])(?:\+7|8)[\s\-(]*(?P<rest>\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2})(?![\d])")
_PHONE_CHAIN = re.compile(r"(?<![\w.,/])\+?\d[\d\s()\-]{5,}\d(?![\w])")
_PHONE_CONTEXT = re.compile(r"(?i)\b(?:тел|телефон|факс|моб|phone|whatsapp|telegram|e-?mail|эл\.?\s*почт\w*|почт\w*)\b|\+7|@")
_ADDRESS_HINT = re.compile(r"(?i)\bг\.|\bул\.|улица|\bд\.|\bофис|\bпом\.|\bкорп\.|адрес")
_STREET = re.compile(
    r"(?i:\b(?:ул\.|улица|пр-т|просп\.|проспект|пер\.|переулок|ш\.|шоссе|наб\.|набережная|б-р|бульвар|пл\.|площадь|проезд|"
    r"мкр\.?|микрорайон))\s*(?P<n>[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ0-9][а-яё0-9\-]*){0,2})")
_ADDRESS_CONTEXT = re.compile(r"(?i)\bг\.|город|\bул\.|улиц|проспект|\bпр-т|адрес|област|шоссе|переул|бульвар|(?<!\d)\d{6}(?!\d)")
_STREET_POST = re.compile(
    r"(?P<n>[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){0,2})\s+(?i:ул\.|улица|пр-т|просп\.|проспект|пер\.|переулок|ш\.|шоссе|наб\.|набережная|б-р|бульвар|пл\.|площадь)")
_BUILDING = re.compile(r"(?i:\b(?:д\.|дом|корп\.|корпус|кв\.|квартира|оф\.|офис|пом\.|помещение|стр\.|строение))\s*№?\s*(?P<n>\d[\w./\-]*)")
_POSTAL = re.compile(r"(?<![\d])\d{6}(?![\d])")
_DIGIT_RUN = re.compile(r"\d{2,}")

CORE_BLANK = {"creator", "lastModifiedBy", "title", "subject", "description", "keywords", "category", "contentStatus", "identifier"}
APP_BLANK = {"Company", "Manager", "HyperlinkBase"}
APP_DROP = {"TitlesOfParts", "HeadingPairs"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").casefold().replace("ё", "е")).strip()


_NOT_ORG = {_norm(x) for x in ("Компания", "Общество", "Организация", "Заказчик", "Исполнитель", "Стороны", "Договор", "Предприятие",
                               "Организатор", "Участник", "Оператор", "Клиент", "Партнёр", "Партнер", "Агент", "Принципал")}
_GENERIC_FIRST = {_norm(x) for x in (
    "Торговый", "Торговая", "Торговое", "Производственная", "Производственное", "Строительная", "Строительное", "Группа",
    "Компания", "Сервис", "Технологии", "Центр", "Международная", "Международный", "Российская", "Российский", "Первая", "Первый",
    "Главный", "Научно", "Научная", "Научный", "Транспортная", "Логистическая", "Региональная", "Региональный", "Городская",
    "Московская", "Московский", "Санкт", "Новая", "Новый", "Лучший", "Единая", "Единый", "Объединённая", "Центральная")}


def _flex(term: str) -> str:
    """Регулярка для названия: пробелы любые, кавычки не важны, ё = е."""
    out = []
    for ch in term.strip():
        if ch.isspace():
            out.append(r"\s+")
        elif ch in "её":
            out.append("[её]")
        elif ch in "ЕЁ":
            out.append("[ЕЁ]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _prefix(token: str) -> str:
    """Основа слова для поиска во всех падежах: без конечной гласной / й / ь."""
    return token[:-1] if token and token[-1].lower() in _VOWELS and len(token) > 4 else token


def _prefix_rx(token: str) -> str:
    p = _prefix(token)
    pat = _flex(p) + r"[а-яё]{0,3}"
    up = _flex(p.upper()) + r"[А-ЯЁ]{0,3}"
    return f"(?:{pat}|{up})"


@dataclass
class Person:
    surname: str = ""
    name: str = ""
    patronymic: str = ""
    female: bool = False
    fake: tuple[str, str, str] = ("", "", "")

    def keys(self) -> list[str]:
        return [t for t in (self.surname, self.name, self.patronymic) if t]


@dataclass
class Span:
    start: int
    end: int
    repl: str
    kind: str


@dataclass
class Anonymizer:
    authors: dict[str, str] = field(default_factory=dict)  # автор → заглушка («kandu» → «Мы»)
    terms: dict[str, str] = field(default_factory=dict)  # слово → заглушка (ручные добавления)
    seed: str = "pravki"
    orgs: dict[str, str] = field(default_factory=dict)  # нормализованное название → заглушка
    foreign: dict[str, str] = field(default_factory=dict)
    persons: list[Person] = field(default_factory=list)
    digits: dict[str, str] = field(default_factory=dict)
    emails: dict[str, str] = field(default_factory=dict)
    urls: dict[str, str] = field(default_factory=dict)
    originals: set[str] = field(default_factory=set)  # всё найденное: по нему идёт проверка утечек
    _compiled: list | None = field(default=None, repr=False)
    _fake_set: set = field(default_factory=set, repr=False)

    # ------------------------------------------------------------------ обучение
    def learn(self, text: str) -> None:
        self._compiled = None
        for m in _ORG_QUOTED.finditer(text):
            self._add_org(m.group("name"))
        for m in _NAME_FOREIGN.finditer(text):
            self._add_foreign(m.group(0))
        for m in _FIO.finditer(text):
            self._add_person(m.group(1), m.group(2), m.group(3))
        for m in _IP2.finditer(text):
            self._add_person(m.group(1), m.group(2), "")
        for m in _SURNAME_INIT.finditer(text):
            self._add_person(m.group(1), "", "")
        for m in _INIT_SURNAME.finditer(text):
            self._add_person(m.group(3), "", "")
        for m in _EMAIL.finditer(text):
            self.originals.add(m.group(0))
        for m in _URL.finditer(text):
            self.originals.add(m.group(0).rstrip(".,;"))

    def _add_org(self, name: str) -> None:
        name = re.sub(r"\s+", " ", name.split("«")[-1]).strip()  # «Компания «Тензор»» → Тензор
        key = _norm(name)
        if key in self.orgs:
            self.originals.add(name)  # ещё один вариант написания (регистр)
            return
        if len(key) < 2 or key.startswith(("организация-", "foreign ")) or not re.search(r"[A-Za-zА-Яа-яЁё]", name):
            return
        if is_known_role(name) or is_numbered_role(name) or key in _NOT_ORG or set(key) <= {"0", " "}:
            return  # роль («Перевозчик», «Сторона 1») — часть условий, а не название
        repl = f"Организация-{len(set(self.orgs.values())) + 1}"
        self.orgs[key] = repl
        self.originals.add(name)
        words = name.split()
        first = words[0] if words else ""
        # «Ромашка Софт» → в комментариях и письмах пишут просто «Ромашка»
        if len(words) >= 2 and len(first) >= 5 and _norm(first) not in _GENERIC_FIRST and _norm(first) not in self.orgs:
            self.orgs[_norm(first)] = repl
            self.originals.add(first)

    def _add_foreign(self, name: str) -> None:
        name = re.sub(r"\s+", " ", name).strip().rstrip(",")
        key = _norm(name)
        if key in self.foreign or key.startswith("foreign "):
            return
        n = len(self.foreign)
        self.foreign[key] = f"Foreign Trading {GREEK[n % len(GREEK)]}{'' if n < len(GREEK) else n} Ltd"
        self.originals.add(name)

    def _find_person(self, surname: str, name: str = "", patronymic: str = "") -> Person | None:
        for p in self.persons:
            if surname and p.surname and _prefix(p.surname).casefold() == _prefix(surname).casefold():
                return p
        if not surname:
            for p in self.persons:
                if name and patronymic and p.name and _prefix(p.name).casefold() == _prefix(name).casefold():
                    return p
        return None

    def _add_person(self, surname: str, name: str, patronymic: str) -> None:
        if len(surname) < 4 and not name:
            return
        p = self._find_person(surname, name, patronymic)
        if p is None:
            p = Person(surname=surname, name=name, patronymic=patronymic)
            self.persons.append(p)
        else:
            p.name = p.name or name
            p.patronymic = p.patronymic or patronymic
            p.surname = p.surname or surname
        p.female = p.female or bool(re.search(r"(?:овн|евн|ичн)а?$", patronymic) or re.search(r"(?:ова|ева|ина|ая)$", surname))
        for t in (surname, name, patronymic):
            if t:
                self.originals.add(t)
        self._compiled = None

    # ------------------------------------------------------------------ вымышленные значения
    def _assign_fakes(self) -> None:
        taken = [_prefix(t).casefold() for p in self.persons for t in p.keys()]

        def clash(word: str) -> bool:
            w = _prefix(word).casefold()
            return any(w.startswith(t) or t.startswith(w) for t in taken)

        counters = Counter()
        for p in self.persons:
            if p.fake[0]:
                continue
            pools = ((FEMALE_SURNAMES, FEMALE_NAMES, FEMALE_PATR) if p.female else (MALE_SURNAMES, MALE_NAMES, MALE_PATR))
            picked = []
            for i, pool in enumerate(pools):
                key = (p.female, i)
                while counters[key] < len(pool) + 50:
                    base = pool[counters[key] % len(pool)]
                    suffix = "" if counters[key] < len(pool) else str(counters[key] // len(pool) + 1)
                    counters[key] += 1
                    cand = base + suffix
                    if not clash(base):
                        picked.append(cand)
                        break
                else:
                    picked.append(pool[0])
            p.fake = (picked[0], picked[1], picked[2])
            taken.extend(_prefix(x).casefold() for x in picked)

    def _is_fake(self, value: str) -> bool:
        return value in self._fake_set

    def _fake_digits(self, orig: str) -> str:
        if orig in self.digits:
            return self.digits[orig]
        if self._is_fake(orig):
            return orig
        h = hashlib.sha256((self.seed + "|" + orig).encode()).hexdigest()
        digs = [str(int(c, 16) % 10) for c in h]
        out, k = [], 0
        for ch in orig:
            if ch.isdigit():
                d = digs[k % len(digs)]
                k += 1
                if len(out) == 0 and d == "0":
                    d = "1"
                out.append(d)
            else:
                out.append(ch)
        res = "".join(out)
        if set(orig) <= {"0", " ", "-"}:
            return orig
        if res == orig:  # цифры не должны совпасть с настоящими
            res = "".join(str((int(c) + 1) % 10) if c.isdigit() else c for c in orig)
        self.digits[orig] = res
        self._fake_set.add(res)
        self._fake_set.update(re.findall(r"\d+", res))
        self.originals.add(orig)
        return res

    def _fake_email(self, orig: str) -> str:
        if orig.lower().endswith("@example.com"):
            return orig
        return self.emails.setdefault(orig.lower(), f"user{len(self.emails) + 1}@example.com")

    def _fake_url(self, orig: str) -> str:
        orig = orig.rstrip(".,;")
        if "example.com" in orig.lower():
            return orig
        return self.urls.setdefault(orig.lower(), f"https://example.com/page{len(self.urls) + 1}")

    # ------------------------------------------------------------------ поиск
    def _person_patterns(self) -> list[tuple[re.Pattern, callable]]:
        out = []
        for p in self.persons:
            f_s, f_n, f_p = p.fake
            fi = (f_n[:1] + "." + f_p[:1] + ".") if f_n and f_p else ""
            S = _prefix_rx(p.surname) if p.surname else ""
            N = _prefix_rx(p.name) if p.name else ""
            P = _prefix_rx(p.patronymic) if p.patronymic else ""
            sep = r"\s+"
            if S and N and P:
                out.append((re.compile(rf"(?<![А-ЯЁа-яё]){S}{sep}{N}{sep}{P}(?![А-ЯЁа-яё])"),
                            lambda m, a=f_s, b=f_n, c=f_p: f"{a} {b} {c}"))
            if S:
                out.append((re.compile(rf"(?<![А-ЯЁа-яё]){S}\s+[А-ЯЁ]\.\s?[А-ЯЁ]?\.?"), lambda m, a=f_s, i=fi: f"{a} {i}"))
                out.append((re.compile(rf"(?<![А-ЯЁа-яё])[А-ЯЁ]\.\s?[А-ЯЁ]?\.?\s*{S}(?![А-ЯЁа-яё])"), lambda m, a=f_s, i=fi: f"{i} {a}"))
            if S and N:
                out.append((re.compile(rf"(?<![А-ЯЁа-яё]){S}{sep}{N}(?![А-ЯЁа-яё])"), lambda m, a=f_s, b=f_n: f"{a} {b}"))
            if N and P:
                out.append((re.compile(rf"(?<![А-ЯЁа-яё]){N}{sep}{P}(?![А-ЯЁа-яё])"), lambda m, b=f_n, c=f_p: f"{b} {c}"))
            if S:
                out.append((re.compile(rf"(?<![А-ЯЁа-яё]){S}(?![А-ЯЁа-яё])"), lambda m, a=f_s: a))
        return out

    def _compile(self) -> list:
        if self._compiled is not None:
            return self._compiled
        self._assign_fakes()
        pats: list[tuple[re.Pattern, callable]] = []
        by_norm = {_norm(o).rstrip(","): o for o in self.originals}
        for key, repl in sorted(self.foreign.items(), key=lambda kv: -len(kv[0])):
            pats.append((re.compile(r"(?<![A-Za-z])" + _flex(by_norm.get(key, key)), re.IGNORECASE), lambda m, r=repl: r))
        variants: dict[str, set[str]] = {}
        for o in self.originals:
            variants.setdefault(_norm(o).rstrip(","), set()).add(o)
        for key, repl in sorted(self.orgs.items(), key=lambda kv: -len(kv[0])):
            vs = variants.get(key) or {key}
            sample = max(vs, key=len)
            tail = r"[а-яё]{0,3}" if sample[-1:].lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" else ""
            if " " in key:  # несколько слов: регистр не важен
                body, flags = _flex(sample), re.IGNORECASE
            else:  # одно слово может быть и обычным словом («портал»): только встретившиеся написания
                body, flags = "|".join(_flex(x) for x in sorted({y for v in vs for y in (v, v.capitalize(), v.upper())}, key=len, reverse=True)), 0
            pats.append((re.compile(r"(?<![А-ЯЁа-яёA-Za-z])(?:" + body + r")" + tail + r"(?![А-ЯЁа-яёA-Za-z])", flags), lambda m, r=repl: r))
        for term, repl in sorted(self.terms.items(), key=lambda kv: -len(kv[0])):
            pats.append((re.compile(r"(?<![А-ЯЁа-яёA-Za-z])(?:" + _flex(term) + r")[а-яё]{0,3}(?![А-ЯЁа-яёA-Za-z])", re.IGNORECASE),
                         lambda m, r=repl: r))
        pats.extend(self._person_patterns())
        pats.append((_EMAIL, lambda m: self._fake_email(m.group(0))))
        pats.append((_URL, lambda m: self._fake_url(m.group(0))))
        pats.append((_DOMAIN, lambda m: self._fake_url(m.group(0)).removeprefix("https://")))
        self._compiled = pats
        return pats

    def find_spans(self, text: str, names_only: bool = False) -> list[Span]:
        spans: list[Span] = []
        for rx, fn in self._compile():
            for m in rx.finditer(text):
                if m.end() > m.start():
                    spans.append(Span(m.start(), m.end(), fn(m), "name"))
        if names_only:
            return self._pick(spans)
        for m in _LABELED_ID.finditer(text):
            spans.append(Span(m.start("d"), m.end("d"), self._fake_digits(m.group("d")), "id"))
        for m in _LONG_DIGITS.finditer(text):
            spans.append(Span(m.start(), m.end(), self._fake_digits(m.group(0)), "id"))
        for m in _PASSPORT.finditer(text):
            for d in _DIGIT_RUN.finditer(m.group(0)):
                spans.append(Span(m.start() + d.start(), m.start() + d.end(), self._fake_digits(d.group(0)), "id"))
        for m in _PHONE_EXPLICIT.finditer(text):
            spans.append(Span(m.start("rest"), m.end("rest"), self._fake_digits(m.group("rest")), "phone"))
        if len(text) <= 220 and _PHONE_CONTEXT.search(text):
            for chain in _PHONE_CHAIN.finditer(text):
                for d in _DIGIT_RUN.finditer(chain.group(0)):
                    spans.append(Span(chain.start() + d.start(), chain.start() + d.end(), self._fake_digits(d.group(0)), "phone"))
        for m in _STREET.finditer(text):
            spans.append(Span(m.start("n"), m.end("n"), "Образцовая", "address"))
        for m in _STREET_POST.finditer(text):
            spans.append(Span(m.start("n"), m.end("n"), "Образцовая", "address"))
        if _ADDRESS_CONTEXT.search(text):
            for m in _BUILDING.finditer(text):
                spans.append(Span(m.start("n"), m.end("n"), "1", "address"))
        if _ADDRESS_HINT.search(text):
            for m in _POSTAL.finditer(text):
                spans.append(Span(m.start(), m.end(), "000000", "address"))
        return self._pick(spans)

    @staticmethod
    def _pick(spans: list[Span]) -> list[Span]:
        spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
        chosen: list[Span] = []
        end = -1
        for s in spans:
            if s.start >= end:
                chosen.append(s)
                end = s.end
        return chosen

    def apply_text(self, text: str) -> str:
        out, last = [], 0
        for s in self.find_spans(text):
            out.append(text[last:s.start])
            out.append(s.repl)
            last = s.end
        out.append(text[last:])
        return "".join(out)

    def author(self, name: str) -> str:
        if not name:
            return name
        if name not in self.authors:
            self.authors[name] = f"Автор-{sum(1 for v in self.authors.values() if v.startswith('Автор-')) + 1}"
        self.originals.add(name)
        return self.authors[name]

    # ------------------------------------------------------------------ сохранение карты
    def to_json(self) -> str:
        data = {
            "seed": self.seed, "authors": self.authors, "terms": self.terms, "orgs": self.orgs, "foreign": self.foreign,
            "persons": [{"surname": p.surname, "name": p.name, "patronymic": p.patronymic, "female": p.female, "fake": list(p.fake)}
                        for p in self.persons],
            "digits": self.digits, "emails": self.emails, "urls": self.urls, "originals": sorted(self.originals),
        }
        return json.dumps(data, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "Anonymizer":
        d = json.loads(s)
        a = cls(authors=d.get("authors", {}), terms=d.get("terms", {}), seed=d.get("seed", "pravki"))
        a.orgs, a.foreign = d.get("orgs", {}), d.get("foreign", {})
        a.digits, a.emails, a.urls = d.get("digits", {}), d.get("emails", {}), d.get("urls", {})
        a.originals = set(d.get("originals", []))
        a._fake_set = set(a.digits.values())
        for v in list(a._fake_set):
            a._fake_set.update(re.findall(r"\d+", v))
        for p in d.get("persons", []):
            a.persons.append(Person(p["surname"], p["name"], p["patronymic"], p.get("female", False), tuple(p.get("fake", ("", "", "")))))
        return a


# --------------------------------------------------------------------------------------
# Работа с файлом
# --------------------------------------------------------------------------------------
def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


def _read_zip(path: str) -> dict[str, bytes]:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise DocxError(f"{path}: не docx ({e})")
    out: dict[str, bytes] = {}
    with zf:
        total = 0
        for info in zf.infolist():
            if info.file_size > MAX_PART:
                raise DocxError(f"{path}: часть {info.filename} слишком большая")
            total += info.file_size
            if total > 8 * MAX_PART:
                raise DocxError(f"{path}: файл слишком большой после распаковки")
            out[info.filename] = zf.read(info.filename)
    return out


def _nearest_p(el):
    for anc in el.iterancestors():
        if anc.tag == q("p"):
            return anc
    return None


def _paragraph_nodes(p, tags) -> list:
    return [n for n in p.iter(*tags) if _nearest_p(n) is p]


def _streams(p) -> list[list]:
    """Три потока текста абзаца: всё подряд, только действующий текст, только удалённый."""
    t, d = q("t"), q("delText")
    return [_paragraph_nodes(p, (t, d)), _paragraph_nodes(p, (t,)), _paragraph_nodes(p, (d,))]


def paragraph_streams_text(p) -> list[str]:
    return ["".join(n.text or "" for n in nodes) for nodes in _streams(p)]


def _iter_text_parts(parts: dict[str, bytes]):
    for name in sorted(parts):
        if TEXT_PARTS.match(name):
            yield name


def learn_docx(anon: Anonymizer, path: str) -> None:
    parts = _read_zip(path)
    for name in _iter_text_parts(parts):
        root = etree.fromstring(parts[name], _parser())
        for p in root.iter(q("p")):
            for s in paragraph_streams_text(p)[:1]:
                if s:
                    anon.learn(s)
        for n in root.iter(q("instrText")):
            if n.text:
                anon.learn(n.text)


def _apply_nodes(anon: Anonymizer, nodes: list, names_only: bool = False) -> int:
    texts = [n.text or "" for n in nodes]
    if not any(texts):
        return 0
    starts, pos = [], 0
    for t in texts:
        starts.append(pos)
        pos += len(t)
    full = "".join(texts)
    spans = anon.find_spans(full, names_only)
    for s in reversed(spans):
        first = True
        for i, t in enumerate(texts):
            a, b = starts[i], starts[i] + len(t)
            if b <= s.start or a >= s.end:
                continue
            lo, hi = max(s.start, a) - a, min(s.end, b) - a
            if first:
                texts[i] = t[:lo] + s.repl + t[hi:]
                first = False
            else:
                texts[i] = t[:lo] + t[hi:]
    for n, t in zip(nodes, texts):
        if (n.text or "") != t:
            n.text = t
            if t != t.strip() or "  " in t:
                n.set(XML_SPACE, "preserve")
    return len(spans)


def _anon_text_part(anon: Anonymizer, root) -> int:
    count = 0
    for p in root.iter(q("p")):
        for nodes in _streams(p):
            count += _apply_nodes(anon, nodes)
    for n in root.iter(q("instrText")):
        count += _apply_nodes(anon, [n], names_only=True)
    for el in root.iter():
        new_author = ""
        for attr in list(el.attrib):
            local = etree.QName(attr).localname
            if local == "author":
                new_author = anon.author(el.get(attr))
                el.set(attr, new_author)
            elif local in ("descr", "title") and etree.QName(el).localname in ("docPr", "cNvPr"):
                el.set(attr, "")
        for attr in list(el.attrib):
            if etree.QName(attr).localname == "initials":
                el.set(attr, ("".join(w[:1] for w in re.split(r"[\s\-]+", new_author) if w)[:3]) or "А")
    return count


def _anon_people(anon: Anonymizer, root) -> None:
    for el in root.iter():
        for attr in list(el.attrib):
            local = etree.QName(attr).localname
            if local == "author":
                el.set(attr, anon.author(el.get(attr)))
            elif local == "userId":
                el.set(attr, "")
            elif local == "providerId":
                el.set(attr, "None")


def _anon_rels(anon: Anonymizer, data: bytes) -> bytes:
    root = etree.fromstring(data, _parser())
    for rel in list(root):
        if rel.get("TargetMode") != "External":
            continue
        target = rel.get("Target", "")
        low = target.lower()
        if low.startswith("mailto:"):
            rel.set("Target", "mailto:" + anon._fake_email(target[7:].split("?")[0]))
        elif low.startswith(("http://", "https://")):
            rel.set("Target", anon._fake_url(target))
        else:
            rel.set("Target", "file:///anonymised")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _anon_docprops(name: str, data: bytes) -> bytes:
    root = etree.fromstring(data, _parser())
    if name.endswith("core.xml"):
        for el in root.iter():
            if etree.QName(el).localname in CORE_BLANK:
                el.text = "Автор" if etree.QName(el).localname in ("creator", "lastModifiedBy") else ""
    elif name.endswith("app.xml"):
        for el in list(root):
            local = etree.QName(el).localname
            if local in APP_BLANK:
                el.text = ""
            elif local in APP_DROP:
                root.remove(el)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _drop_parts(parts: dict[str, bytes], dropped: set[str]) -> None:
    for name in dropped:
        parts.pop(name, None)
    for name in [n for n in parts if n.endswith(".rels")]:
        base = name.replace("_rels/", "", 1)[:-5]  # часть, к которой относятся связи
        folder = base.rsplit("/", 1)[0] + "/" if "/" in base else ""
        root = etree.fromstring(parts[name], _parser())
        changed = False
        for rel in list(root):
            if rel.get("TargetMode") == "External":
                continue
            tgt = rel.get("Target", "")
            resolved = tgt.lstrip("/") if tgt.startswith("/") else _resolve(folder, tgt)
            if resolved in dropped or any(resolved.startswith(d) for d in dropped if d.endswith("/")):
                root.remove(rel)
                changed = True
        if changed:
            parts[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    ct = parts.get("[Content_Types].xml")
    if ct:
        root = etree.fromstring(ct, _parser())
        for el in list(root):
            if el.get("PartName", "").lstrip("/") in dropped or any(el.get("PartName", "").lstrip("/").startswith(d) for d in dropped if d.endswith("/")):
                root.remove(el)
        parts["[Content_Types].xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _resolve(folder: str, target: str) -> str:
    segs = (folder + target).split("/")
    out: list[str] = []
    for s in segs:
        if s == "..":
            if out:
                out.pop()
        elif s and s != ".":
            out.append(s)
    return "/".join(out)


def anonymize_docx(anon: Anonymizer, src: str, dst: str) -> dict:
    """Записать обезличенную копию src в dst. Возвращает сводку."""
    parts = _read_zip(src)
    summary = {"замен": 0, "картинок заменено": 0, "картинок не заменено": 0, "удалено частей": 0}
    dropped = {n for n in parts if any(n.startswith(p) for p in DROP_PREFIXES) or n.startswith("customXML/")}
    for name in sorted(parts):
        if name in dropped:
            continue
        data = parts[name]
        if TEXT_PARTS.match(name):
            root = etree.fromstring(data, _parser())
            summary["замен"] += _anon_text_part(anon, root)
            parts[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        elif PEOPLE_PARTS.match(name):
            root = etree.fromstring(data, _parser())
            _anon_people(anon, root)
            parts[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        elif name.endswith(".rels"):
            parts[name] = _anon_rels(anon, data)
        elif name.startswith("docProps/") and name.endswith(".xml"):
            parts[name] = _anon_docprops(name, data)
        elif name == "word/settings.xml":
            root = etree.fromstring(data, _parser())
            for el in list(root.iter(q("attachedTemplate"))):
                el.getparent().remove(el)
            parts[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        elif name.startswith("word/media/"):
            ext = name.rsplit(".", 1)[-1].lower()
            if ext == "png":
                parts[name] = PNG_1X1
                summary["картинок заменено"] += 1
            elif ext in ("jpg", "jpeg"):
                parts[name] = JPG_1X1
                summary["картинок заменено"] += 1
            else:
                summary["картинок не заменено"] += 1
    _drop_parts(parts, dropped)
    summary["удалено частей"] = len(dropped)
    order = ["[Content_Types].xml"] + [n for n in parts if n != "[Content_Types].xml"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            z.writestr(n, parts[n])
    with open(dst, "wb") as f:
        f.write(buf.getvalue())
    return summary


# --------------------------------------------------------------------------------------
# Проверка результата
# --------------------------------------------------------------------------------------
@dataclass
class Leak:
    part: str
    kind: str
    sample: str

    def __str__(self) -> str:
        return f"{self.part}: {self.kind}: {self.sample}"


def _search_forms(term: str) -> list[bytes]:
    return [term.encode("utf-8"), term.encode("utf-16-le")]


def scan_leaks(anon: Anonymizer, path: str) -> list[Leak]:
    """Что осталось в готовом файле. Пусто — программа ничего из найденного не пропустила.

    Ищет и по тексту абзацев (по тем же правилам, что при замене), и по сырым байтам всех частей файла,
    включая свойства, комментарии, ссылки и карту людей.
    """
    leaks: list[Leak] = []
    parts = _read_zip(path)
    person_tokens = {t for p in anon.persons for t in p.keys()}
    needles = {t for t in anon.originals if len(t) >= 4 and t not in person_tokens and t not in anon.authors.values()
               and t not in anon._fake_set}
    word_rx = [(t, re.compile(r"(?<![А-ЯЁа-яё])" + re.escape(t) + r"(?![А-ЯЁа-яё])")) for t in person_tokens if len(t) >= 3]
    for name, data in parts.items():
        raw = data
        for t in needles:
            for form in _search_forms(t):
                if form in raw:
                    leaks.append(Leak(name, "исходное значение", t[:60]))
                    break
        if name.endswith((".xml", ".rels")):
            decoded = data.decode("utf-8", "ignore")
            for t, rx in word_rx:
                if rx.search(decoded):
                    leaks.append(Leak(name, "имя или фамилия", t))
        if name.endswith((".xml", ".rels")):
            text = re.sub(r'xmlns(?::\w+)?="[^"]*"', "", data.decode("utf-8", "ignore"))
            for m in _EMAIL.finditer(text):
                if not m.group(0).endswith("@example.com"):
                    leaks.append(Leak(name, "e-mail", m.group(0)))
            for m in _URL.finditer(text):
                if "example.com" not in m.group(0) and "schemas." not in m.group(0) and "openxmlformats" not in m.group(0) \
                        and "w3.org" not in m.group(0) and "microsoft.com" not in m.group(0) and "purl.org" not in m.group(0):
                    leaks.append(Leak(name, "ссылка", m.group(0)[:80]))
    for name in parts:
        if TEXT_PARTS.match(name):
            root = etree.fromstring(parts[name], _parser())
            for p in root.iter(q("p")):
                for s in paragraph_streams_text(p):
                    for span in anon.find_spans(s):
                        if span.kind in ("name",) and span.repl != s[span.start:span.end]:
                            leaks.append(Leak(name, "найдено ещё раз", s[span.start:span.end][:60]))
                    for m in _LONG_DIGITS.finditer(s):
                        if m.group(0) not in anon._fake_set:
                            leaks.append(Leak(name, "длинное число", m.group(0)))
    for author in anon.authors:
        if author in anon.authors.values():
            continue
        for name, data in parts.items():
            if author.encode("utf-8") in data:
                leaks.append(Leak(name, "автор правок", author))
    return leaks


_STOP = {
    "Заказчик", "Исполнитель", "Поставщик", "Покупатель", "Подрядчик", "Сторона", "Стороны", "Стороной", "Сторон", "Договор",
    "Договора", "Договору", "Договоре", "Договором", "Российской", "Федерации", "Федерации.", "Гражданского", "Кодекса", "Кодекс",
    "Приложение", "Приложения", "Акт", "Акта", "Москва", "Москвы", "Арбитражного", "Арбитражный", "Суда", "Суд", "РФ", "ГК", "НДС",
    "Организатор", "Участник", "Арендодатель", "Арендатор", "Лицензиар", "Лицензиат", "Получающая", "Раскрывающая", "Услуги",
    "Услуг", "Работы", "Товар", "Товара", "Продавец", "Спецификация", "Спецификации", "Предмет", "Ответственность", "Форс-мажор",
    "Конфиденциальность", "Срок", "Цена", "Оплата", "Порядок", "Права", "Обязанности", "Прочие", "Заключительные", "Реквизиты",
    "Подписи", "Директор", "Генеральный", "Уставе", "Устава", "ИНН", "КПП", "ОГРН", "ОГРНИП", "БИК", "Банк", "Иностранная",
}


def residual_candidates(path: str, limit: int = 120) -> list[tuple[str, int]]:
    """Слова, которые могли остаться и называть что-то конкретное: с заглавной буквы не в начале предложения,
    латиницей, а также слова в кавычках. Нужно просмотреть глазами и добавить нужные в terms."""
    parts = _read_zip(path)
    cnt: Counter = Counter()
    for name in sorted(parts):
        if not TEXT_PARTS.match(name):
            continue
        root = etree.fromstring(parts[name], _parser())
        for p in root.iter(q("p")):
            s = paragraph_streams_text(p)[0]
            for m in re.finditer(r"(?<=[а-яёa-z,;:(«\"] )([А-ЯЁ][а-яё\-]{3,})", s):
                if m.group(1) not in _STOP:
                    cnt[m.group(1)] += 1
            for m in re.finditer(r"\b[A-Za-z][A-Za-z0-9\-]{2,}\b", s):
                if m.group(0).lower() not in ("example", "https", "http", "com", "foreign", "trading", "ltd", "user", "page"):
                    cnt[m.group(0)] += 1
            for m in re.finditer(r"[«\"“]([^»\"”]{2,40})[»\"”]", s):
                if not re.fullmatch(r"(?:Организация-\d+|Заказчик|Исполнитель|Поставщик|Покупатель|Подрядчик|Стороны?|Договор|Продавец|Мы)", m.group(1)):
                    cnt["«" + m.group(1) + "»"] += 1
    return cnt.most_common(limit)
