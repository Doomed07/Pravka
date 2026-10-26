"""Сквозной разбор: два docx → список правок с темой, областью, существенностью и рекомендацией."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime

from .classify import classify
from .compare import compare_versions, resolve_ours, without_new_ours
from .docx_reader import DocxError
from .intake import MAX_MODEL_CLAUSES, clause_changes
from .readers import read_document
from .model import Change
from .parties import (PARTY_TOPIC, RoleCheckError, SideConfig, SideResult, check_side, head_indices,
                      mark_head_changes, parties_of, party_changes)
from .playbook import Playbook, analyze, load_playbook, sort_key
from .unified import build_unified

DISCLAIMER = "Черновик — требует вашей проверки перед отправкой (draft — needs your review before sending)."


@dataclass
class Review:
    base_path: str
    theirs_path: str
    playbook_name: str
    our_role: str
    changes: list[Change]
    authors: list[str]
    mode: str  # 'tracked' | 'tracked+compare' | 'compare'
    warnings: list[str] = field(default_factory=list)
    created: str = ""
    llm_used: bool = False
    side: SideResult | None = None  # проверка нашей стороны договора (C9)
    document: list[dict] = field(default_factory=list)  # единая версия договора (unified.build_unified)

    def counts(self) -> dict:
        c = self.changes
        return {
            "всего": len(c),
            "в рецензировании": sum(1 for x in c if x.source == "tracked" and x.kind != "comment"),
            "комментарии": sum(1 for x in c if x.kind == "comment"),
            "тихие правки": sum(1 for x in c if x.source == "silent"),
            "найдено сравнением": sum(1 for x in c if x.source == "diff"),
            "нужно решение юриста": sum(1 for x in c if x.lawyer_decision_needed),
            "вне плейбука": sum(1 for x in c if x.out_of_playbook),
            "красные линии": sum(1 for x in c if x.level == "reject"),
            "технические": sum(1 for x in c if x.materiality == "техническая"),
            "стороны и реквизиты": sum(1 for x in c if x.topic == PARTY_TOPIC),
        }


def _mark_cells(changes: list[Change], doc) -> None:
    """Правке в ячейке таблицы — заголовок её столбца и текст строки: по ним классификатор узнаёт, о чём значение."""
    cells = {}
    for para in doc.paragraphs:
        if para.table:
            text = "".join(s.text for s in para.segments if s.kind in ("equal", "ins")).strip()
            key = (para.table[0], para.table[1], para.table[2])
            cells[key] = (cells[key] + " " + text).strip() if key in cells else text
    for c in changes:
        para = doc.paragraphs[c.paragraph_index] if 0 <= c.paragraph_index < len(doc.paragraphs) else None
        if para is None or not para.table or c.kind == "comment":
            continue
        t, row, col = para.table[0], para.table[1], para.table[2]
        if row > 0:
            c.detail["cell_head"] = cells.get((t, 0, col), "")
        c.detail["cell_row"] = " | ".join(v for (tt, rr, _), v in sorted(cells.items()) if tt == t and rr == row)


def review_files(
    theirs_path: str,
    base_path: str | None = None,
    playbook: Playbook | str | None = None,
    our_authors: list[str] | None = None,
    explainer=None,
    ordering: str = "priority",
    side: SideConfig | None = None,
    first_version: bool = False,
) -> Review:
    """Разобрать версию контрагента.

    Если задан плейбук, сначала проверяется наша сторона договора (C9): при несовпадении или невозможности её
    определить бросается RoleCheckError и разбор не выполняется. Затем сверяются стороны между версиями (C10).
    """
    theirs = read_document(theirs_path)
    base = read_document(base_path) if base_path else None
    if theirs.format == "pdf" and base is None and not first_version:
        raise DocxError("для PDF нужна ваша отправленная версия: в PDF нет рецензирования, правки находятся сравнением с ней")
    pb = load_playbook(playbook) if isinstance(playbook, str) else playbook
    warnings: list[str] = list(theirs.notes) + list(base.notes if base is not None else [])
    ours, ours_warnings = resolve_ours(our_authors, base)
    warnings.extend(ours_warnings)
    theirs, n_new_ours = without_new_ours(base, theirs, ours)
    if n_new_ours:
        clauses = sorted({p.clause for p in theirs.paragraphs if p.index in theirs.reworked and p.clause},
                         key=lambda c: [int(x) if x.isdigit() else 0 for x in c.split(".")])
        where = f", пункты: {', '.join(clauses)}" if clauses else ""
        warnings.append(f"В версии контрагента есть ваши правки, сделанные после отправленной версии (мест: {n_new_ours}{where}). "
                        "Это не правки контрагента: программа их не разбирает. Если вы отправляли более позднюю версию, "
                        "загрузите её как отправленную.")

    # C9: стороны берём из нашей версии текста: без правок контрагента, с нашими правками
    our_doc, our_mode = (base, "accepted") if base is not None else (theirs, "rejected")
    side_res = check_side(pb.our_role if pb else "", parties_of(our_doc, our_mode, ours), side or SideConfig())
    if pb is None:
        side_res.status = "not_checked"
        side_res.message = "Плейбук не указан: сторона договора не проверялась."
    if side_res.blocked:
        raise RoleCheckError(side_res)

    if first_version and base is None and not theirs.has_tracked:
        return _review_first_version(theirs, theirs_path, pb, explainer, side_res, warnings, ours)

    changes = compare_versions(base, theirs, our_authors, judge=explainer.same_condition if explainer else None)
    # C10: стороны и реквизиты между версиями — отдельные правки высшего приоритета
    changes = party_changes(base, theirs, ours) + changes
    if any(c.topic == PARTY_TOPIC for c in changes):
        warnings.append("Изменились стороны или реквизиты договора: проверьте их в первую очередь, "
                        "от этого зависит смысл всех остальных правок.")
    if base is None:
        mode = "tracked"
        if theirs.has_tracked:
            warnings.append(
                "Не указана отправленная нами версия: найдены только правки, отмеченные в рецензировании. "
                "«Тихие» правки без неё не обнаружить."
            )
        else:
            warnings.append("В файле нет правок в рецензировании, а отправленная версия не указана — сравнивать не с чем.")
    elif theirs.has_tracked:
        mode = "tracked+compare"
    else:
        mode = "compare"
        warnings.append("В файле контрагента нет рецензирования: все отличия найдены сравнением с отправленной версией.")
    n_carried = sum(1 for c in changes if c.detail.get("carried"))
    if n_carried:
        warnings.append(f"Правок контрагента из прошлого раунда, оставшихся нерешёнными в нашей версии: {n_carried} "
                        "(помечены «из прошлого раунда»).")
    if theirs.has_tracked and base is not None:
        n_silent = sum(1 for c in changes if c.source == "silent")
        if n_silent:
            warnings.append(f"Найдено правок без отметки в рецензировании: {n_silent}. Проверьте их в первую очередь.")

    regular = [c for c in changes if c.topic != PARTY_TOPIC]
    _mark_cells(regular, theirs)
    for c in regular:
        classify(c)
    mark_head_changes(regular, head_indices(theirs))
    from_base = [c for c in regular if c.detail.get("accepted_from_base")]
    for c in from_base:
        mark_accepted_from_base(c)
    regular = [c for c in regular if c.topic != PARTY_TOPIC and not c.detail.get("accepted_from_base")]
    if explainer is not None:
        for c in regular:
            if c.materiality == "техническая" and c.kind != "comment" and not explainer.confirms_technical(c):
                note_technical_doubt(c)
    if pb is not None:
        analyze(regular, pb)
    for c in regular:
        if c.detail.get("replaced_para") == "model":  # замену пункта распознала модель — решает юрист
            c.level, c.lawyer_decision_needed = "review", True
            c.action = "Нужно решение юриста: пункт заменён новой редакцией"
    if explainer is not None:
        for c in regular:
            # другие правки того же абзаца: их факты не должны попасть в пояснение к этой
            neighbours = [o for o in changes if o is not c and c.paragraph_index >= 0
                          and o.paragraph_index == c.paragraph_index]
            explainer.apply(c, neighbours)

    if ordering == "priority":
        changes.sort(key=lambda c: sort_key(c, pb))
    else:
        changes.sort(key=lambda c: c.order)

    return Review(
        base_path=base_path or "",
        theirs_path=theirs_path,
        playbook_name=pb.name if pb else "",
        our_role=pb.our_role if pb else "",
        changes=changes,
        authors=theirs.authors,
        mode=mode,
        warnings=warnings,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        llm_used=explainer is not None,
        side=side_res,
        document=build_unified(base, theirs, ours, changes),
    )


def _review_first_version(theirs, theirs_path, pb, explainer, side_res, warnings, ours) -> Review:
    """Первая версия договора (правок в ней ещё нет): положения проверяются по плейбуку как «предложенные контрагентом».
    Замечание появляется только там, где правило плейбука сработало и не «принять»; решает плейбук, модель поясняет."""
    warnings = list(warnings)
    flagged: list[Change] = []
    if pb is None:
        warnings.append("Плейбук не указан: положения договора по плейбуку не проверялись.")
    else:
        clauses = clause_changes(theirs)
        for c in clauses:
            classify(c)
        analyze(clauses, pb)
        flagged = [c for c in clauses if c.detail.get("rule_applied") and c.level in ("reject", "fallback", "review")]
        for n, c in enumerate(flagged, 1):
            c.id = f"E{n:03d}"
        if explainer is not None:
            for c in flagged[:MAX_MODEL_CLAUSES]:
                explainer.apply(c)
        warnings.append(f"Первая версия договора: правок в ней нет. Положения проверены по плейбуку «{pb.name}»: "
                        f"замечаний {len(flagged)}. Пункты без замечаний не «одобрены»: проверка идёт только по правилам плейбука.")
    return Review(
        base_path="", theirs_path=theirs_path, playbook_name=pb.name if pb else "", our_role=pb.our_role if pb else "",
        changes=flagged, authors=theirs.authors, mode="first", warnings=warnings,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"), llm_used=explainer is not None, side=side_res,
        document=build_unified(None, theirs, ours, flagged),
    )


def note_technical_doubt(ch: Change) -> None:
    """Модель усомнилась, что правка только техническая. Решает правило (по словарю): правка остаётся технической,
    сомнение — заметкой в карточке (решение владельца, 2026-10-24)."""
    ch.notes.append("Модель усомнилась, что правка только грамматическая или техническая; по правилу и словарю — "
                    "техническая. При желании проверьте смысл условия")


def mark_accepted_from_base(ch: Change) -> None:
    """Правка из нашей отправленной версии, которую контрагент принял: решить, чья она, может только юрист.

    Автор правки не указан как наш, поэтому программа не знает, наша это правка (коллега юриста) или чужая правка
    прошлого раунда, которую контрагент принял сам. Плейбук и модель к ней не применяются.
    """
    authors = ", ".join(ch.detail["accepted_from_base"])
    ch.level, ch.rule_id, ch.rule_title = "review", "", ""
    ch.action = "Нужно решение юриста: принята правка из нашей версии"
    ch.explanation = (f"В отправленной нами версии это была правка в рецензировании (автор: {authors}), "
                      "контрагент её принял. Если автор — ваш сотрудник, добавьте его в «Авторы ваших правок»: "
                      "тогда такие правки не попадут в разбор. Если это чужая правка прошлого раунда, проверьте условие.")
    ch.suggested = ""
    ch.lawyer_decision_needed = True


def file_label(path: str) -> str:
    return os.path.basename(path) if path else ""
