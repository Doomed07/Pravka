"""Сравнение версии, которую отправили мы, с версией контрагента.

Находит:
  * правки, отмеченные в рецензировании (source = 'tracked');
  * «тихие» правки — изменения текста без отметки в рецензировании (source = 'silent');
  * все отличия, если контрагент вернул чистую версию без рецензирования (source = 'diff').
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .classify import topic_scores
from .docx_reader import view_paragraphs
from .extract import _short, extract_tracked
from .model import ANNOTATOR, Change, DocxDoc
from .textdiff import diff_changes, flags_for_change, normalize, strip_label

PAIR_THRESHOLD = 0.5


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def _align(base: list[str], theirs: list[str]) -> list[tuple[int | None, int | None]]:
    """Сопоставить абзацы двух версий. Возвращает пары индексов (в base, в theirs); None — нет пары."""
    a = [normalize(t) for t in base]
    b = [normalize(t) for t in theirs]
    pairs: list[tuple[int | None, int | None]] = []
    sm = SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            pairs.extend((i, j) for i, j in zip(range(i1, i2), range(j1, j2)))
        elif tag == "delete":
            pairs.extend((i, None) for i in range(i1, i2))
        elif tag == "insert":
            pairs.extend((None, j) for j in range(j1, j2))
        else:
            pairs.extend(_pair_block(a, b, i1, i2, j1, j2))
    return pairs


def _pair_block(a, b, i1, i2, j1, j2):
    out: list[tuple[int | None, int | None]] = []
    j_cursor = j1
    for i in range(i1, i2):
        best_j, best = None, PAIR_THRESHOLD
        for j in range(j_cursor, j2):
            r = _ratio(a[i], b[j])
            if r > best:
                best_j, best = j, r
        if best_j is None:
            out.append((i, None))
            continue
        out.extend((None, j) for j in range(j_cursor, best_j))
        out.append((i, best_j))
        j_cursor = best_j + 1
    out.extend((None, j) for j in range(j_cursor, j2))
    return out


def resolve_ours(our_authors: list[str] | None, base: DocxDoc | None) -> tuple[set[str], list[str]]:
    """Какие авторы правок считать нашими. Возвращает (авторы, предупреждения).

    Если наши авторы указаны явно, наши только они: в отправленной версии могут остаться ещё не решённые правки
    контрагента прошлого раунда, и принимать их автора за своего нельзя (его новые правки пропали бы из отчёта).
    Без явного указания нашим считается единственный автор отправленной версии; если авторов несколько,
    нашим не считается никто, а юристу показывается предупреждение: лучше лишние правки в отчёте, чем пропущенная.
    """
    explicit = {a for a in (our_authors or []) if a}
    authors = [a for a in (base.authors if base else []) if a and a != ANNOTATOR]
    if explicit:
        extra = [a for a in authors if a not in explicit]
        warn = []
        if extra:
            warn.append("В отправленной версии есть авторы правок, не указанные как наши: " + ", ".join(extra) +
                        ". Их правки считаются правками контрагента.")
        return explicit | {ANNOTATOR}, warn
    if len(authors) <= 1:
        return set(authors) | {ANNOTATOR}, []
    return {ANNOTATOR}, ["В отправленной версии правки нескольких авторов (" + ", ".join(authors) + "), а наши авторы не указаны "
                   "(--our-author): ни один не считается нашим, поэтому наши прежние правки могут попасть в отчёт как правки "
                   "контрагента. Укажите, кто из авторов наш."]


def _tracked_key(c: Change) -> tuple:
    return (c.kind, c.author, c.date, normalize(c.before), normalize(c.after))


def _types_labels(doc: DocxDoc) -> bool:
    """Номера пунктов напечатаны в самом тексте (так в PDF и в договорах без автонумерации)."""
    labeled = [p for p in doc.paragraphs if p.label]
    return bool(labeled) and sum(p.label_in_text for p in labeled) / len(labeled) >= 0.5


def label_policy(base: DocxDoc, theirs: DocxDoc) -> tuple[bool, bool]:
    """Нужно ли убрать напечатанные номера пунктов из текста нашей версии / версии контрагента при сравнении.

    Если в одной версии номера напечатаны (PDF, ручная нумерация), а в другой их показывает редактор (автонумерация),
    «1.», «2.1.» в начале каждого абзаца были бы «вставками». Когда номера напечатаны в обеих версиях, они сравниваются
    как обычный текст: изменённый номер пункта виден как правка."""
    bt, tt = _types_labels(base), _types_labels(theirs)
    return bt and not tt, tt and not bt


def paired_views(base: DocxDoc, theirs: DocxDoc, ours, mode: str = "rejected"):
    """Тексты абзацев обеих версий для сравнения: [(абзац, текст)], с учётом label_policy."""
    strip_base, strip_theirs = label_policy(base, theirs)

    def view(doc, strip):
        return [(p, strip_label(t, p.label) if strip and p.label_in_text else t) for p, t in view_paragraphs(doc, mode, ours)]

    return view(base, strip_base), view(theirs, strip_theirs)


def find_untracked(base: DocxDoc, theirs: DocxDoc, ours: set[str], label: str) -> list[Change]:
    """Отличия текста, не отмеченные в рецензировании.

    Сравнивается наша отправленная версия с версией контрагента. В обеих версиях наши правки приняты,
    а чужие отклонены: так не мешают нерешённые правки контрагента прошлых раундов, которые остались
    в файле и в отправленной нами версии. Если ничего не менялось втихую, тексты совпадают.
    """
    base_view, their_view = paired_views(base, theirs, ours)
    base_view = [(p, t) for p, t in base_view if normalize(t)]
    their_view = [(p, t) for p, t in their_view if normalize(t)]
    # наша версия со всеми правками принятыми: так видно, что контрагент просто принял правку из рецензирования
    base_accepted = {p.index: normalize(t) for p, t in paired_views(base, theirs, ours, "accepted")[0]}
    pairs = _align([t for _, t in base_view], [t for _, t in their_view])
    changes: list[Change] = []
    last_order = -1.0
    for i, j in pairs:
        if j is not None:
            tp, ttext = their_view[j]
            last_order = float(tp.index)
        if i is not None and j is not None:
            bp, btext = base_view[i]
            if normalize(btext) == normalize(ttext):
                continue
            accepted_by = []
            if base_accepted.get(bp.index) == normalize(ttext):
                accepted_by = sorted({s.author or "без имени" for s in bp.segments if s.kind != "equal" and s.author not in ours})
            for before, after in diff_changes(normalize(btext), normalize(ttext)):
                kind = "replace" if before and after else ("insert" if after else "delete")
                ch = Change(
                    source=label, kind=kind, clause=tp.clause, heading=tp.heading,
                    paragraph_index=tp.index, order=float(tp.index) + 0.1, before=before, after=after,
                    context=_short(btext), context_after=_short(ttext),
                )
                ch.flags = flags_for_change(before, after)
                if accepted_by:
                    ch.detail["accepted_from_base"] = accepted_by
                changes.append(ch)
        elif i is not None:
            bp, btext = base_view[i]
            if bp.label_in_text:
                btext = strip_label(btext, bp.label)
            ch = Change(
                source=label, kind="para_delete", clause=bp.clause, heading=bp.heading,
                paragraph_index=-1, order=last_order + 0.2, before=normalize(btext),
                context=_short(btext), context_after="",
            )
            ch.flags = flags_for_change(btext, "")
            if bp.label:
                ch.detail["labeled"] = True
            changes.append(ch)
        else:
            tp, ttext = their_view[j]
            if tp.label_in_text:
                ttext = strip_label(ttext, tp.label)
            ch = Change(
                source=label, kind="para_insert", clause=tp.clause, heading=tp.heading,
                paragraph_index=tp.index, order=float(tp.index) + 0.1, after=normalize(ttext),
                context="", context_after=_short(ttext),
            )
            ch.flags = flags_for_change("", ttext)
            if tp.label:
                ch.detail["labeled"] = True
            changes.append(ch)
    return changes


def _replaced(d: Change, i: Change, by_model: bool) -> Change:
    """Удалённый абзац и вставленный на его место — одна правка: пункт в новой редакции."""
    ch = Change(
        source=d.source, kind="replace", clause=i.clause or d.clause, heading=i.heading or d.heading,
        paragraph_index=i.paragraph_index, order=min(d.order, i.order), before=d.before, after=i.after,
        context=d.context, context_after=i.context_after, author=i.author or d.author, date=i.date or d.date,
    )
    ch.flags = flags_for_change(ch.before, ch.after) + [f for f in d.flags + i.flags if f == "из прошлого раунда"]
    ch.detail.update(d.detail)
    ch.detail.update(i.detail)
    ch.detail["revs"] = sorted(set(d.detail.get("revs", [])) | set(i.detail.get("revs", [])), key=lambda x: (len(x), x))
    ch.detail.pop("move", None)
    ch.detail.pop("labeled", None)
    ch.detail["replaced_para"] = "model" if by_model else "clause"
    if d.paragraph_index >= 0:
        ch.detail["replaced_index"] = d.paragraph_index
    ch.notes.extend(d.notes + i.notes)
    ch.notes.append("Пункт заменён целиком: прежняя и новая редакция показаны одной правкой"
                    + (" (замену распознала модель — проверьте)" if by_model else ""))
    return ch


def _same_topic(before: str, after: str) -> bool:
    """Темы абзацев по классификатору не противоречат друг другу: одна и та же или у одного не определена.
    Защита от ошибки модели: абзацы на разные темы (субподряд и НДС) не объединяются, что бы она ни ответила."""
    tb = topic_scores(Change(kind="para_delete", before=before, context=before))
    ta = topic_scores(Change(kind="para_insert", after=after, context_after=after))
    return not tb or not ta or tb[0][1].name == ta[0][1].name


def merge_replaced(changes: list[Change], judge=None) -> list[Change]:
    """Пункт удалён и на его место вставлен новый — одна правка.

    Собственный номер пункта у обоих абзацев совпадает — объединяет правило. Номера нет или он разный — решает judge(было, стало) (модель):
    объединение только меняет вид отчёта, а такая правка всегда уходит юристу (pipeline).
    """
    out: list[Change] = []
    i = 0
    while i < len(changes):
        a = changes[i]
        b = changes[i + 1] if i + 1 < len(changes) else None
        if b is not None and {a.kind, b.kind} == {"para_delete", "para_insert"} and a.source == b.source \
                and a.author == b.author and a.detail.get("move") is None and b.detail.get("move") is None:
            d, n = (a, b) if a.kind == "para_delete" else (b, a)
            # номер свой у обоих абзацев (а не ближайший выше) и совпадает
            same = bool(d.clause) and d.clause == n.clause and d.detail.get("labeled") and n.detail.get("labeled")
            by_model = not same and judge is not None and _same_topic(d.before, n.after) and judge(d.before, n.after)
            if same or by_model:
                out.append(_replaced(d, n, by_model))
                i += 2
                continue
        out.append(a)
        i += 1
    return out


def compare_versions(base: DocxDoc | None, theirs: DocxDoc, our_authors: list[str] | None = None,
                     judge=None) -> list[Change]:
    """Все правки контрагента. base — версия, которую отправили мы (может отсутствовать).

    judge(было, стало) -> bool — необязательная проверка моделью, что удалённый и вставленный абзацы — одно условие.
    """
    ours, _ = resolve_ours(our_authors, base)
    changes = extract_tracked(theirs, ours)
    if base is not None:
        # правки контрагента, которые уже были в отправленной нами версии и не решены: это не новый раунд
        seen = {_tracked_key(x) for x in extract_tracked(base, ours)}
        for ch in changes:
            if ch.source == "tracked" and _tracked_key(ch) in seen:
                ch.detail["carried"] = True
                ch.flags.append("из прошлого раунда")
                ch.notes.append("Правка уже была в отправленной нами версии и осталась нерешённой")
        label = "silent" if theirs.has_tracked else "diff"
        changes.extend(find_untracked(base, theirs, ours, label))
    changes.sort(key=lambda c: (c.order, c.source != "tracked"))
    changes = merge_replaced(changes, judge)
    for n, c in enumerate(changes, 1):
        c.id = f"E{n:03d}"
        if c.detail.get("accepted_from_base"):
            c.notes.append("В отправленной версии эта правка была в рецензировании (автор: "
                           + ", ".join(c.detail["accepted_from_base"]) + "), контрагент её принял")
        elif c.source == "silent":
            c.notes.append("Правка не отмечена в рецензировании (найдена сравнением с отправленной версией)")
        if c.source == "diff":
            c.notes.append("Версия без рецензирования: правка найдена сравнением с отправленной версией")
    return changes
