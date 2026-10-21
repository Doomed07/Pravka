"""Журнал раундов по проекту договора: что менял контрагент, что решил юрист, что вернулось повторно."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from .model import Change
from .pipeline import Review

STATUSES = ("new", "repeated", "accepted", "rejected", "counter")
DECISIONS = ("accepted", "rejected", "counter")
STATUS_RU = {"new": "новая", "repeated": "повторная", "accepted": "принята", "rejected": "отклонена", "counter": "встречная"}


class JournalError(Exception):
    pass


def _path(project_dir: str) -> str:
    return os.path.join(project_dir, "journal.json")


def init_project(project_dir: str, name: str) -> dict:
    os.makedirs(project_dir, exist_ok=True)
    p = _path(project_dir)
    if os.path.exists(p):
        raise JournalError(f"проект уже существует: {project_dir}")
    data = {"name": name, "created": datetime.now().isoformat(timespec="seconds"), "rounds": []}
    save(project_dir, data)
    return data


def load(project_dir: str) -> dict:
    p = _path(project_dir)
    if not os.path.exists(p):
        raise JournalError(f"нет журнала: {p}. Создайте проект командой init или укажите --project с новой папкой")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(project_dir: str, data: dict) -> None:
    tmp = _path(project_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(project_dir))


def mark_repeats(data: dict, changes: list[Change]) -> None:
    """Правка, которая уже встречалась в прошлых раундах, помечается как повторная."""
    seen: dict[str, tuple[int, str]] = {}
    for rnd in data["rounds"]:
        for c in rnd["changes"]:
            seen[c["fingerprint"]] = (rnd["n"], c["status"])
    for ch in changes:
        fp = ch.fingerprint()
        if fp in seen and ch.materiality != "техническая":
            n, st = seen[fp]
            ch.status = "repeated"
            ch.repeat_note = (
                f"Повторная правка: уже была в раунде {n} (статус там: {STATUS_RU.get(st, st)}). "
                + ("Раньше вы её отклоняли — контрагент настаивает." if st in ("rejected", "counter") else "")
            ).strip()


def add_round(project_dir: str, rv: Review, copy_files: bool = True) -> int:
    data = load(project_dir)
    mark_repeats(data, rv.changes)
    n = len(data["rounds"]) + 1
    rdir = os.path.join(project_dir, "rounds", f"{n:02d}")
    os.makedirs(rdir, exist_ok=True)
    if copy_files:
        for src, name in ((rv.theirs_path, "theirs"), (rv.base_path, "base")):
            if src and os.path.exists(src):
                shutil.copy2(src, os.path.join(rdir, f"{name}{os.path.splitext(src)[1]}"))
    data["rounds"].append({
        "n": n,
        "date": datetime.now().isoformat(timespec="seconds"),
        "theirs": os.path.basename(rv.theirs_path),
        "base": os.path.basename(rv.base_path) if rv.base_path else "",
        "counts": rv.counts(),
        "changes": [
            {
                "id": c.id, "fingerprint": c.fingerprint(), "clause": c.clause, "topic": c.topic, "kind": c.kind,
                "source": c.source, "before": c.before[:300], "after": c.after[:300], "level": c.level,
                "status": c.status, "note": "",
            }
            for c in rv.changes
        ],
    })
    save(project_dir, data)
    return n


def round_dir(project_dir: str, n: int) -> str:
    return os.path.join(project_dir, "rounds", f"{n:02d}")


def decide(project_dir: str, change_id: str, status: str, note: str = "", round_n: int | None = None) -> dict:
    if status not in DECISIONS:
        raise JournalError(f"статус должен быть одним из: {', '.join(DECISIONS)}")
    data = load(project_dir)
    if not data["rounds"]:
        raise JournalError("в проекте ещё нет раундов")
    rnd = data["rounds"][-1] if round_n is None else next((r for r in data["rounds"] if r["n"] == round_n), None)
    if rnd is None:
        raise JournalError(f"нет раунда {round_n}")
    for c in rnd["changes"]:
        if c["id"] == change_id:
            c["status"] = status
            c["note"] = note
            c["decided"] = datetime.now().isoformat(timespec="seconds")
            save(project_dir, data)
            return c
    raise JournalError(f"в раунде {rnd['n']} нет правки {change_id}")


def history_text(project_dir: str) -> str:
    data = load(project_dir)
    lines = [f"Проект: {data['name']}"]
    for r in data["rounds"]:
        cnt = r["counts"]
        lines.append(
            f"Раунд {r['n']} ({r['date'][:10]}): {r['theirs']} — правок {cnt.get('всего', 0)}, "
            f"тихих {cnt.get('тихие правки', 0)}, красных линий {cnt.get('красные линии', 0)}"
        )
        by = {}
        for c in r["changes"]:
            by[c["status"]] = by.get(c["status"], 0) + 1
        lines.append("  статусы: " + ", ".join(f"{STATUS_RU.get(k, k)} {v}" for k, v in sorted(by.items())))
    return "\n".join(lines)
