"""Нормализация текста, пословное сравнение и признаки значимых изменений."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_QUOTES = {"«": '"', "»": '"', "„": '"', "“": '"', "”": '"', "‟": '"', "’": "'", "‘": "'"}
_DASHES = {"–": "-", "—": "-", "−": "-", "‑": "-"}
_TOKEN_RE = re.compile(r"\s+|\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*|\w+|[^\w\s]", re.UNICODE)

_DATE_RE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")
_NUM_RE = re.compile(r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
_MONEY_RE = re.compile(r"руб|₽|usd|eur|евро|доллар|\$|€|копе", re.IGNORECASE)
_TERM_RE = re.compile(r"дн(?:ей|я|ь)\b|месяц|недел|год|лет\b|рабоч|календарн|час", re.IGNORECASE)
_NEG_RE = re.compile(r"\b(?:не|нет|ни|без|кроме|запрещ\w*|исключ\w*)\b", re.IGNORECASE)


def normalize(text: str) -> str:
    """Привести текст к виду, пригодному для сравнения: пробелы, кавычки, тире."""
    if not text:
        return ""
    text = text.replace(" ", " ").replace("​", "").replace("­", "")
    for src, dst in _QUOTES.items():
        text = text.replace(src, dst)
    for src, dst in _DASHES.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _slide(ops, ta, tb):
    """Сдвинуть чистые вставки/удаления вправо до границы слова/предложения, чтобы правка не начиналась со «случайной» точки."""
    for idx in range(1, len(ops) - 1):
        tag, i1, i2, j1, j2 = ops[idx]
        if tag not in ("delete", "insert"):
            continue
        prev, nxt = ops[idx - 1], ops[idx + 1]
        if prev[0] != "equal" or nxt[0] != "equal":
            continue
        # для вставки блок живёт в tb, для удаления — в ta; сравниваем с токенами соответствующей стороны
        seq = ta if tag == "delete" else tb
        a, b = (i1, i2) if tag == "delete" else (j1, j2)
        while b < len(seq) and a < b and seq[a] == seq[b] and nxt[2] > nxt[1] and nxt[4] > nxt[3]:
            a += 1
            b += 1
            prev[2] += 1
            prev[4] += 1
            nxt[1] += 1
            nxt[3] += 1
            if tag == "delete":
                ops[idx][1:5] = [a, b, ops[idx][3] + 1, ops[idx][4] + 1]
            else:
                ops[idx][1:5] = [ops[idx][1] + 1, ops[idx][2] + 1, a, b]
    return ops


def diff_ops(a: str, b: str) -> list[tuple[str, str, str]]:
    ta, tb = tokens(a), tokens(b)
    sm = SequenceMatcher(None, ta, tb, autojunk=False)
    ops = [list(o) for o in sm.get_opcodes()]
    ops = _slide(ops, ta, tb)
    return [
        (tag, "".join(ta[i1:i2]), "".join(tb[j1:j2]))
        for tag, i1, i2, j1, j2 in ops
        if tag == "equal" or i2 > i1 or j2 > j1
    ]


def strip_label(text: str, label: str) -> str:
    """Убрать номер пункта, напечатанный в начале текста («4.3. Текст» → «Текст»)."""
    if not label or not text:
        return text
    m = re.match(r"^\s*" + re.escape(label) + r"[.)]?\s+", text)
    return text[m.end():] if m else text


def _small_gap(gap: str) -> bool:
    """Короткий общий кусок между двумя правками: не больше одного слова, без конца предложения."""
    g = gap.strip()
    if len(g) > 12 or re.search(r"[.;!?]", g):
        return False
    return len(re.findall(r"\w+", g)) <= 1


def diff_changes(a: str, b: str) -> list[tuple[str, str]]:
    """Список пар (было, стало) для двух вариантов текста.

    Соседние изменения, разделённые коротким общим куском (не более одного слова), склеиваются в одно.
    """
    cur: list[str] | None = None
    gap = ""
    result: list[list[str]] = []
    for tag, x, y in diff_ops(a, b):
        if tag == "equal":
            if cur is not None:
                gap += x
            continue
        if cur is None:
            cur = ["", ""]
        elif gap:
            if _small_gap(gap):
                cur[0] += gap
                cur[1] += gap
            else:
                result.append(cur)
                cur = ["", ""]
            gap = ""
        cur[0] += x
        cur[1] += y
    if cur is not None:
        result.append(cur)
    out: list[tuple[str, str]] = []
    for before, after in result:
        before, after = before.strip(), after.strip()
        if before != after:
            out.append((before, after))
    return out


def numbers(text: str) -> list[str]:
    """Числа и суммы из текста в канонической записи (без пробелов, точка вместо запятой)."""
    text = _DATE_RE.sub(" ", text)
    found = []
    for m in _NUM_RE.findall(text):
        found.append(re.sub(r"[  ]", "", m).replace(",", "."))
    return found


def dates(text: str) -> list[str]:
    return [d.replace("/", ".") for d in _DATE_RE.findall(text)]


def flags_for_change(before: str, after: str) -> list[str]:
    """Признаки значимых изменений: числа, даты, суммы, сроки, проценты, отрицания."""
    flags: list[str] = []
    both = f"{before} {after}"
    nb, na = sorted(numbers(before)), sorted(numbers(after))
    db, da = sorted(dates(before)), sorted(dates(after))
    if nb != na:
        flags.append("число")
        if "%" in both or re.search(r"процент", both, re.IGNORECASE):
            flags.append("процент")
        if _MONEY_RE.search(both):
            flags.append("сумма")
        if _TERM_RE.search(both):
            flags.append("срок")
    if db != da:
        flags.append("дата")
    nneg_b = len(_NEG_RE.findall(before))
    nneg_a = len(_NEG_RE.findall(after))
    if nneg_b != nneg_a:
        flags.append("отрицание")
    seen = set()
    return [f for f in flags if not (f in seen or seen.add(f))]
