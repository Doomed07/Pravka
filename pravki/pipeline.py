"""Сквозной разбор: два docx → список правок с темой, областью, существенностью и рекомендацией."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime

from .classify import classify
from .compare import compare_versions
from .docx_reader import read_docx
from .model import Change
from .parties import PARTY_TOPIC, RoleCheckError, SideConfig, SideResult, check_side, parties_of, party_changes
from .playbook import Playbook, analyze, load_playbook, sort_key

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


def review_files(
    theirs_path: str,
    base_path: str | None = None,
    playbook: Playbook | str | None = None,
    our_authors: list[str] | None = None,
    explainer=None,
    ordering: str = "priority",
    side: SideConfig | None = None,
) -> Review:
    """Разобрать версию контрагента.

    Если задан плейбук, сначала проверяется наша сторона договора (C9): при несовпадении или невозможности её
    определить бросается RoleCheckError и разбор не выполняется. Затем сверяются стороны между версиями (C10).
    """
    theirs = read_docx(theirs_path)
    base = read_docx(base_path) if base_path else None
    pb = load_playbook(playbook) if isinstance(playbook, str) else playbook
    warnings: list[str] = []
    ours = {a for a in (set(our_authors or []) | set(base.authors if base else [])) if a}

    # C9: стороны берём из нашей версии текста: без правок контрагента, с нашими правками
    our_doc, our_mode = (base, "accepted") if base is not None else (theirs, "rejected")
    side_res = check_side(pb.our_role if pb else "", parties_of(our_doc, our_mode, ours), side or SideConfig())
    if pb is None:
        side_res.status = "not_checked"
        side_res.message = "Плейбук не указан: сторона договора не проверялась."
    if side_res.blocked:
        raise RoleCheckError(side_res)

    changes = compare_versions(base, theirs, our_authors)
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
    if theirs.has_tracked and base is not None:
        n_silent = sum(1 for c in changes if c.source == "silent")
        if n_silent:
            warnings.append(f"Найдено правок без отметки в рецензировании: {n_silent}. Проверьте их в первую очередь.")

    regular = [c for c in changes if c.topic != PARTY_TOPIC]
    for c in regular:
        classify(c)
    if pb is not None:
        analyze(regular, pb)
    if explainer is not None:
        for c in regular:
            explainer.apply(c)

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
    )


def file_label(path: str) -> str:
    return os.path.basename(path) if path else ""
