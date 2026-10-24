"""Чтение договора любого поддерживаемого формата: docx, odt, PDF с текстом. Формат определяется по содержимому файла.

Все читалки отдают одну и ту же модель (`DocxDoc`: абзацы, правки, комментарии), поэтому сравнение, плейбук и отчёты
не знают, откуда пришёл текст. Word с примечаниями и ответ в Word собираются из XML самого docx и для других форматов
недоступны.
"""
from __future__ import annotations

import zipfile

from .docx_reader import (DocxError, _APPENDIX_START, _LABEL_RE, _clean_label, _is_heading, read_docx)
from .model import DocxDoc, Paragraph

ODT_MIME = "application/vnd.oasis.opendocument.text"


def sniff_format(path: str) -> str:
    """'docx', 'odt' или 'pdf' по содержимому файла; DocxError, если формат не поддерживается."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except FileNotFoundError:
        raise DocxError(f"файл не найден: {path}")
    except (IsADirectoryError, PermissionError) as e:
        raise DocxError(f"не удалось открыть {path}: {e.__class__.__name__}")
    if head.startswith(b"%PDF-"):
        return "pdf"
    if not head.startswith(b"PK"):
        raise DocxError("неизвестный формат файла: поддерживаются .docx, .odt и PDF с текстом")
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "content.xml" in names:
                mime = zf.read("mimetype").decode("ascii", "ignore").strip() if "mimetype" in names else ""
                if mime in ("", ODT_MIME):
                    return "odt"
                raise DocxError(f"это документ OpenDocument другого вида ({mime}): поддерживается только текстовый .odt")
    except zipfile.BadZipFile:
        raise DocxError("не удалось открыть файл: он повреждён")
    raise DocxError("неизвестный формат файла: поддерживаются .docx, .odt и PDF с текстом")


def read_document(path: str) -> DocxDoc:
    fmt = sniff_format(path)
    if fmt == "docx":
        return read_docx(path)
    if fmt == "odt":
        from .odt_reader import read_odt

        return read_odt(path)
    from .pdf_reader import read_pdf

    return read_pdf(path)


def finish_labels(paragraphs: list[Paragraph], auto: dict[int, str] | None = None) -> None:
    """Номер пункта (`label`), ближайший номер выше (`near`) и заголовок раздела (`heading`) — теми же правилами, что в
    read_docx. auto — номера, которые показывает сам редактор (автонумерация): абзац → номер; иначе номер ищется в тексте."""
    auto = auto or {}
    last_label = ""
    last_heading = ""
    for para in paragraphs:
        visible = "".join(s.text for s in para.segments if s.kind in ("equal", "ins"))
        full = "".join(s.text for s in para.segments)
        shown = auto.get(para.index, "")
        label = _clean_label(shown) if shown else ""
        if not label:
            m = _LABEL_RE.match(visible or full)
            if m:
                label = next(g for g in m.groups() if g)
                para.label_in_text = True
        para.label = label
        appendix = _APPENDIX_START.match(visible or full) if not label else None
        if appendix:
            last_label = f"Приложение {appendix.group(1)}"
        para.near = last_label
        if label:
            last_label = label
        text_for_head = (visible or full).strip()
        text_for_head = _LABEL_RE.sub("", text_for_head, count=1).strip() if not shown else text_for_head
        if appendix or _is_heading(para, text_for_head, para.style):
            last_heading = text_for_head[:200]
        para.heading = last_heading
