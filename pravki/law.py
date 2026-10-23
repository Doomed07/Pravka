"""Нормы ГК РФ для подсказок к правкам: разбор официального текста на статьи и пункты.

Источник — официальный интернет-портал правовой информации (pravo.gov.ru, ИПС «Законодательство России»), текст
действующей редакции (страница документа с fulltext=1, кодировка windows-1251). Берётся только текст закона:
заголовки (раздел, глава, параграф, статья) и абзацы. Пометки «(В редакции Федерального закона от …)» в текст пункта
не входят, но последняя дата редакции статьи сохраняется. Утратившие силу статьи помечаются и в поиск не идут.

Пункт — единица поиска: «1. …» вместе со следующими абзацами без номера (подпункты, продолжение) до следующего пункта.
Статья без нумерованных пунктов — один пункт с номером "".
"""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import asdict, dataclass, field

_P = re.compile(r"<p(?:\s+class=\"(?P<cls>[^\"]*)\")?[^>]*>(?P<body>.*?)</p>", re.S | re.I)
_MARK = re.compile(r"<span class=\"mark\"[^>]*>.*?</a>\)?</span>", re.S)
_TAG = re.compile(r"<[^>]+>")
_SUP = re.compile(r"<span class=\"W9\"[^>]*>\s*(\d+)\s*</span>")  # надстрочный номер: «406<sup>1</sup>» = 406.1
_DATE = re.compile(r"от\s+(\d\d)\.(\d\d)\.(\d{4})")
_ARTICLE = re.compile(r"^Статья\s+(\d+(?:\.\d+)*)\.\s*(.*)$")
_CHAPTER = re.compile(r"^Глава\s+(\d+(?:\.\d+)*)\.\s*(.*)$")
_PARA = re.compile(r"^§\s*(\d+(?:\.\d+)*)\.\s*(.*)$")
_SECTION = re.compile(r"^Раздел\s+([IVXLC]+)\.?\s*(.*)$")
_POINT = re.compile(r"^(\d+(?:\.\d+)*)\.\s")
_LOST = re.compile(r"утратил[аи]?\s+силу", re.I)
# пометка портала о редакции: «(В редакции Федерального закона от …)», «(Дополнение пунктом - Федеральный закон …)»,
# «(Пункт утратил силу - …)» — в скобках со ссылкой на федеральный закон
_NOTE = re.compile(r"\s*\((?:[^()]|\([^()]*\))*?Федеральн\w*\s+закон(?:[^()]|\([^()]*\))*\)")


@dataclass
class Point:
    number: str  # "1", "2.1" или "" — статья без пунктов
    text: str


@dataclass
class Article:
    code: str  # "ГК РФ"
    number: str  # "506", "783.1"
    title: str
    section: str = ""  # «Раздел IV. Отдельные виды обязательств»
    chapter: str = ""  # «Глава 30. Купля-продажа»
    paragraph: str = ""  # «§ 3. Поставка товаров»
    edited: str = ""  # последняя дата редакции статьи, ГГГГ-ММ-ДД
    lost: bool = False  # утратила силу
    points: list[Point] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"ст. {self.number} {self.code}"


def _clean(fragment: str) -> str:
    text = html_lib.unescape(_TAG.sub("", _SUP.sub(r".\1", fragment))).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_ips(page: str, code: str = "ГК РФ") -> list[Article]:
    """Статьи из HTML страницы документа ИПС (уже раскодированного из windows-1251)."""
    out: list[Article] = []
    section = chapter = paragraph = ""
    art: Article | None = None
    for m in _P.finditer(page):
        cls, body = (m.group("cls") or "").lower(), m.group("body")
        marks = _MARK.findall(body)
        for mk in marks:  # даты редакций — у текущей статьи
            if art is not None:
                for d, mo, y in _DATE.findall(_clean(mk)):
                    art.edited = max(art.edited, f"{y}-{mo}-{d}")
        text = _clean(_MARK.sub("", body))
        notes = _NOTE.findall(text)
        text = _NOTE.sub("", text).strip()
        if art is not None:
            for d, mo, y in _DATE.findall(" ".join(notes)):
                art.edited = max(art.edited, f"{y}-{mo}-{d}")
        if cls == "h" and _ARTICLE.match(text + " ") and any(_LOST.search(n) for n in notes):
            text += " Утратила силу"  # «Статья 5. (Утратила силу - …)»: номер остаётся, статья помечается
        if not text or (_POINT.match(text + " ") and not _POINT.sub("", text + " ").strip()):
            continue  # пустой абзац или «3.» от пункта, утратившего силу
        if cls == "h":
            if a := _ARTICLE.match(text + " " if text.endswith(".") else text):
                art = Article(code, a.group(1), a.group(2).strip(), section, chapter, paragraph)
                art.lost = bool(_LOST.search(art.title))
                out.append(art)
            elif c := _CHAPTER.match(text):
                chapter, paragraph, art = text, "", None
            elif p := _PARA.match(text):
                paragraph, art = text, None
            elif _SECTION.match(text):
                section, chapter, paragraph, art = text, "", "", None
            continue
        if art is None:
            continue
        if _LOST.fullmatch(text.strip(" .()")) or re.fullmatch(r"\(?Утратил[аи]? силу.*", text):
            if not art.points:
                art.lost = True
            continue
        pm = _POINT.match(text)
        if pm or not art.points:
            art.points.append(Point(pm.group(1) if pm else "", text))
        else:
            art.points[-1].text += "\n" + text
    for a in out:  # пункт «утратил силу» в поиск не идёт
        a.points = [p for p in a.points if not _LOST.fullmatch(_POINT.sub("", p.text).strip(" .()"))]
        if not a.points:
            a.lost = True
    return out


def save_jsonl(articles: list[Article], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for a in articles:
            f.write(json.dumps(asdict(a), ensure_ascii=False) + "\n")


def load_jsonl(path: str) -> list[Article]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            d["points"] = [Point(**p) for p in d["points"]]
            out.append(Article(**d))
    return out


# Части ГК РФ в ИПС «Законодательство России» (pravo.gov.ru): номер документа nd
GK_PARTS = {1: "102033239", 2: "102039276", 3: "102073578", 4: "102110716"}
IPS = "http://pravo.gov.ru/proxy/ips/"


def _get(url: str, tries: int = 4) -> bytes:
    """Портал иногда отвечает пустым 204: повторяем с паузой."""
    import time
    import urllib.request

    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=600) as r:
            data = r.read()
        if data:
            return data
        time.sleep(5 * (i + 1))
    raise OSError(f"портал не отдал страницу: {url}")


def fetch_gk(out_dir: str) -> list[str]:
    """Скачать действующую редакцию четырёх частей ГК РФ с pravo.gov.ru в out_dir (partN.html). Номер последней
    редакции (rdk) берётся со страницы документа: без него портал отдаёт первоначальный текст 1994 года."""
    import os

    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for n, nd in GK_PARTS.items():
        info = _get(f"{IPS}?docbody=&nd={nd}").decode("cp1251", "replace")
        rdk = max((int(x) for x in re.findall(r"rdk=(\d+)", info)), default=0)
        if not rdk:
            raise OSError(f"не найден номер редакции части {n}")
        page = _get(f"{IPS}?doc_itself=&nd={nd}&page=1&rdk={rdk}&fulltext=1")
        path = os.path.join(out_dir, f"part{n}.html")
        with open(path, "wb") as f:
            f.write(page)
        paths.append(path)
    return paths


def build_gk(html_dir: str, out: str) -> list[Article]:
    """Разобрать скачанные части (partN.html) и сохранить статьи в jsonl."""
    import os

    arts: list[Article] = []
    for n in GK_PARTS:
        with open(os.path.join(html_dir, f"part{n}.html"), encoding="cp1251", errors="replace") as f:
            arts += parse_ips(f.read())
    save_jsonl(arts, out)
    return arts
