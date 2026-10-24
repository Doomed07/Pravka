"""Чтение PDF с текстом (не скан): абзацы восстанавливаются из строк страниц.

В PDF нет рецензирования и нет абзацев: есть строки на страницах. Поэтому все различия находит только сравнение с нашей
отправленной версией, а границы абзацев и номера пунктов определяются по виду текста — это приблизительно, и разбор
предупреждает об этом. Сканы (картинки) не поддерживаются: для них нужен распознаватель текста.
Файл недоверенный: число страниц и объём текста ограничены.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .docx_reader import DocxError
from .model import DocxDoc, Paragraph, Segment
from .readers import finish_labels

MAX_PAGES = 300
MAX_CHARS = 2_000_000
EDGE_LINES = 2  # сколько строк сверху и снизу страницы проверяем на колонтитул и номер страницы

PDF_NOTE = ("PDF: правки найдены сравнением с вашей версией; границы абзацев и номера пунктов восстановлены по тексту, "
            "проверьте их в первую очередь. Word с примечаниями и ответ в Word для PDF недоступны.")

_PAGE_NO = re.compile(r"^\s*(?:[-–—]\s*)?(?:(?:стр\.?|страница|page)\s*)?\d{1,4}(?:\s*(?:из|/|of)\s*\d{1,4})?(?:\s*[-–—])?\s*$", re.IGNORECASE)
_START = re.compile(
    r"^\s*(?:\d+(?:\.\d+)+[.)]?\s|\d+[.)]\s|[а-яa-z]\)\s|(?:приложение|статья|раздел|глава)\b|[-–—•]\s)", re.IGNORECASE)
_END = re.compile(r"[.;:!?»”)]\s*$")


def _squash(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text).strip()


def _edge_key(line: str) -> str:
    return re.sub(r"\d+", "#", _squash(line).lower())


def _strip_page_furniture(pages: list[list[str]]) -> list[list[str]]:
    """Убрать номера страниц и колонтитулы: строки сверху/снизу, повторяющиеся не меньше чем на половине страниц."""
    keys: Counter = Counter()
    for lines in pages:
        edge = lines[:EDGE_LINES] + lines[-EDGE_LINES:] if len(lines) > EDGE_LINES * 2 else lines
        for k in {_edge_key(x) for x in edge}:
            keys[k] += 1
    repeated = set()
    if len(pages) >= 3:
        need = max(3, math.ceil(len(pages) / 2))
        repeated = {k for k, n in keys.items() if n >= need and k}
    out = []
    for lines in pages:
        keep = []
        for i, line in enumerate(lines):
            at_edge = i < EDGE_LINES or i >= len(lines) - EDGE_LINES
            outermost = i == 0 or i == len(lines) - 1  # номер страницы — самая верхняя или самая нижняя строка
            if (outermost and _PAGE_NO.match(line)) or (at_edge and _edge_key(line) in repeated):
                continue
            keep.append(line)
        out.append(keep)
    return out


def _is_caps_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return 3 <= len(line) <= 80 and bool(letters) and all(c.isupper() for c in letters) and not _START.match(line)


def paragraphs_from_pages(pages: list[str]) -> list[str]:
    """Тексты страниц → абзацы: без колонтитулов и номеров страниц, со склеенными переносами строк."""
    lines_by_page = [[_squash(x) for x in text.splitlines() if _squash(x)] for text in pages]
    lines: list[tuple[str, bool]] = []  # (строка, первая на странице)
    for page in _strip_page_furniture(lines_by_page):
        lines += [(x, i == 0) for i, x in enumerate(page)]
    if not lines:
        return []
    lengths = sorted(len(x) for x, _ in lines)
    full = lengths[int(len(lengths) * 0.9)]  # длина «полной» строки: у короткой строки абзац, скорее всего, закончился
    out: list[str] = []
    prev = ""
    for line, first_on_page in lines:
        starts = bool(_START.match(line)) or _is_caps_heading(line) or (bool(prev) and _is_caps_heading(prev))
        # абзац кончился, если предложение закончено и строка короткая — или это начало страницы с заглавной буквы/цифры
        page_break = first_on_page and bool(prev) and bool(_END.search(prev)) and (line[:1].isupper() or line[:1].isdigit())
        short_end = bool(prev) and bool(_END.search(prev)) and (len(prev) < 0.8 * full or page_break)
        # очень короткая строка без точки («г. Москва 01.10.2026», «Поставщик:»): абзац кончился, если дальше не строчная буква
        short_line = bool(prev) and len(prev) < 0.6 * full and not line[:1].islower()
        if not prev or starts or short_end or short_line:
            if prev:
                out.append(prev)
            prev = line
        elif prev.endswith("-") and len(prev) >= 0.8 * full and line[:1].islower():
            prev = prev[:-1] + line  # перенос слова: «постав-» + «ка» → «поставка»
        else:
            prev = prev + " " + line
    if prev:
        out.append(prev)
    return out


def read_pdf(path: str) -> DocxDoc:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover
        raise DocxError("для чтения PDF нужна библиотека pypdf (pip install pypdf)")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocxError("PDF защищён паролем: снимите защиту и загрузите файл ещё раз")
        n = len(reader.pages)
        if n > MAX_PAGES:
            raise DocxError(f"в PDF {n} страниц: больше {MAX_PAGES} не разбираем")
        pages, empty = [], 0
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:  # одна неразборчивая страница не должна ронять разбор
                text = ""
            if not text.strip():
                empty += 1
            pages.append(text)
    except DocxError:
        raise
    except FileNotFoundError:
        raise DocxError(f"файл не найден: {path}")
    except (PdfReadError, Exception) as e:  # noqa: B014 — pypdf бросает разные исключения на повреждённых файлах
        raise DocxError(f"не удалось прочитать PDF: файл повреждён или не поддерживается ({e.__class__.__name__})")
    if sum(len(t) for t in pages) > MAX_CHARS:
        raise DocxError("в PDF слишком много текста")
    texts = paragraphs_from_pages(pages)
    if not texts:
        raise DocxError("в PDF нет текста: похоже, это скан. Распознавание сканов не поддерживается; загрузите .docx или PDF с текстом")
    paragraphs = [Paragraph(index=i, segments=[Segment(kind="equal", text=t)]) for i, t in enumerate(texts)]
    finish_labels(paragraphs)
    notes = [PDF_NOTE]
    if empty:
        notes.append(f"В PDF {empty} из {n} страниц без текста (картинки или сканы): они не разобраны. Сверьте договор с оригиналом.")
    return DocxDoc(path=path, paragraphs=paragraphs, comments={}, authors=[], format="pdf", notes=notes)
