"""Оценка качества разбора на синтетических парах документов (и на вашем золотом наборе в том же формате)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict

from .pipeline import review_files
from .synth import generate_case, side_config
from .textdiff import normalize

IMPORTANT = {"высокая", "средняя"}


def _n(s: str) -> str:
    return normalize(s).lower()


def _side(truth_side: str, pred_side: str) -> bool:
    """Совпадение одной стороны правки (было/стало): пустая сторона найденной правки допустима отдельно."""
    if not truth_side or not pred_side:
        return False
    return truth_side in pred_side or pred_side in truth_side


def _text_match(truth: dict, ch) -> bool:
    tb, ta = _n(truth["before"]), _n(truth["after"])
    pb, pa = _n(ch.before), _n(ch.after)
    if truth["kind"] == "comment":
        return ch.kind == "comment" and ta in pa
    if ch.kind == "comment":
        return False
    if tb and ta:
        # замена: найденная правка может быть меньше (только вставка слова) или шире
        return _side(tb, pb) or _side(ta, pa)
    if tb:
        return _side(tb, pb) and not pa
    return _side(ta, pa) and not pb


def match_changes(truth_edits: list[dict], changes: list, source_key: str):
    """Жадное сопоставление: каждая настоящая правка — не более чем с одной найденной."""
    used: set[int] = set()
    pairs: list[tuple[dict, object | None]] = []
    for t in truth_edits:
        want = t[source_key]
        if want is None:
            continue
        cands = [
            (i, c) for i, c in enumerate(changes)
            if i not in used and (c.source == want or (t["kind"] == "comment" and c.kind == "comment"))
            and _text_match(t, c)
        ]
        cands.sort(key=lambda ic: 0 if ic[1].clause == t["clause"] else 1)
        if cands:
            used.add(cands[0][0])
            pairs.append((t, cands[0][1]))
        else:
            pairs.append((t, None))
    extras = [c for i, c in enumerate(changes) if i not in used]
    return pairs, extras


def expected_level(t: dict, ch) -> str:
    exp = t.get("expect") or ""
    if exp == "accept" and not t.get("important", True):
        return "accept"
    if exp == "accept" and ch is not None and ch.source != "tracked":
        return "review"  # тихая правка не принимается автоматически
    return exp


def run_synthetic(n_pairs: int = 40, seed0: int = 1000, playbooks: dict | None = None, workdir: str | None = None,
                  templates: tuple[str, ...] = ("services", "rent", "supply")) -> dict:
    playbooks = playbooks or {}
    stats = defaultdict(int)
    errors: list[dict] = []
    cm = tempfile.TemporaryDirectory() if workdir is None else None
    root = workdir or cm.name  # type: ignore[union-attr]
    try:
        for k in range(n_pairs):
            template = templates[k % len(templates)]
            case = generate_case(os.path.join(root, f"case{k:03d}"), template, seed0 + k)
            truth = case["truth"]
            pb = playbooks.get(template)
            for variant, key in (("tracked", "source_tracked"), ("clean", "source_clean")):
                rv = review_files(case["paths"][variant], case["paths"]["base"], pb, side=side_config(case))
                pairs, extras = match_changes(truth["edits"], rv.changes, key)
                for t, ch in pairs:
                    stats["truth"] += 1
                    imp = t["important"] and t["kind"] != "comment"
                    stats["truth_important"] += 1 if t["important"] else 0
                    is_silent = t[key] == "silent"
                    stats["truth_silent"] += 1 if is_silent else 0
                    if ch is None:
                        errors.append({"case": k, "variant": variant, "type": "missed", "edit": t["key"]})
                        continue
                    stats["found"] += 1
                    stats["found_important"] += 1 if t["important"] else 0
                    stats["found_silent"] += 1 if is_silent else 0
                    if ch.clause == t["clause"]:
                        stats["clause_ok"] += 1
                    if t["topic"]:
                        stats["topic_total"] += 1
                        if ch.topic == t["topic"]:
                            stats["topic_ok"] += 1
                        else:
                            errors.append({"case": k, "variant": variant, "type": "topic", "edit": t["key"],
                                           "got": ch.topic, "want": t["topic"]})
                    stats["imp_total"] += 1
                    flagged = ch.materiality in IMPORTANT
                    if flagged == bool(t["important"]):
                        stats["imp_ok"] += 1
                    elif t["important"]:
                        errors.append({"case": k, "variant": variant, "type": "important_missed", "edit": t["key"],
                                       "got": ch.materiality})
                    if pb is not None and t.get("expect"):
                        want = expected_level(t, ch)
                        stats["level_total"] += 1
                        if ch.level == want:
                            stats["level_ok"] += 1
                        else:
                            errors.append({"case": k, "variant": variant, "type": "level", "edit": t["key"],
                                           "got": ch.level, "want": want, "src": ch.source})
                        if t["expect"] == "reject":
                            stats["redline_total"] += 1
                            if ch.level == "accept":
                                stats["redline_false_accept"] += 1
                            if ch.level in ("accept", "fallback"):
                                stats["redline_soft_accept"] += 1
                stats["extra"] += len(extras)
                stats["pred_total"] += len(pairs) + len(extras)
                for e in extras:
                    errors.append({"case": k, "variant": variant, "type": "extra", "before": e.before[:60],
                                   "after": e.after[:60], "src": e.source})
    finally:
        if cm is not None:
            cm.cleanup()

    def pct(a, b):
        return round(100.0 * a / b, 2) if b else None

    metrics = {
        "пар документов": n_pairs,
        "правок в эталоне (оба варианта)": stats["truth"],
        "полнота, все правки, %": pct(stats["found"], stats["truth"]),
        "полнота, существенные правки, %": pct(stats["found_important"], stats["truth_important"]),
        "полнота, тихие правки, %": pct(stats["found_silent"], stats["truth_silent"]),
        "точность (доля найденного, что настоящее), %": pct(stats["found"], stats["pred_total"]),
        "лишних срабатываний": stats["extra"],
        "верный пункт, %": pct(stats["clause_ok"], stats["found"]),
        "верная тема, %": pct(stats["topic_ok"], stats["topic_total"]),
        "верная существенность (важно/неважно), %": pct(stats["imp_ok"], stats["imp_total"]),
        "верный уровень рекомендации, %": pct(stats["level_ok"], stats["level_total"]),
        "красные линии: ложное «принять», %": pct(stats["redline_false_accept"], stats["redline_total"]),
        "красные линии: «принять» или «уступка», %": pct(stats["redline_soft_accept"], stats["redline_total"]),
    }
    return {"metrics": metrics, "errors": errors, "raw": dict(stats)}


def print_report(result: dict, max_errors: int = 25) -> str:
    lines = ["Метрики на синтетических договорах:"]
    for k, v in result["metrics"].items():
        lines.append(f"  {k}: {v}")
    errs = result["errors"]
    by_type = defaultdict(int)
    for e in errs:
        by_type[e["type"]] += 1
    lines.append("Ошибки по типам: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    for e in errs[:max_errors]:
        lines.append("  " + json.dumps(e, ensure_ascii=False))
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Золотой набор: разметка юриста на реальных (обезличенных) договорах
# --------------------------------------------------------------------------------------
# В отчёт попадают только категории и цифры: тема, уровень, номер пункта, итог. Тексты правок и примечания юриста —
# никогда: разметка и договоры лежат только у владельца.

_APPENDIX = re.compile(r"приложени\w*\s*(?:№\s*)?(\d+)", re.IGNORECASE)


def clause_matches(row_clause: str, ch) -> bool:
    """Правка программы относится к пункту из разметки: «4.12 и 6.1», «10 (реквизиты)» (весь раздел), «Приложение 1»."""
    app = _APPENDIX.search(row_clause or "")
    if app:
        m = _APPENDIX.search(f"{ch.heading} {ch.clause}")
        return bool(m) and m.group(1) == app.group(1)
    for num in re.findall(r"\d+(?:\.\d+)*", row_clause or ""):
        if ch.clause == num or ch.clause.startswith(num + "."):
            return True
    return False


def lawyer_decision(text: str) -> str:
    """Решение юриста из анкеты → none (решение не нужно) | accept | counter (встречное предложение) | '' (нет)."""
    t = (text or "").lower()
    if not t:
        return ""
    if "не нужно" in t:
        return "none"
    if "встречн" in t or "с изменени" in t or "отклон" in t:
        return "counter"
    if "принять" in t:
        return "accept"
    return ""


def compare_decision(lawyer: str, levels: list[str]) -> str:
    """совпало | осторожнее (ушло юристу) | строже (отклонить вместо принять) | опасно (принять вместо встречного)."""
    accepting = {"accept", "fallback"}
    if lawyer == "counter":
        if any(lv in accepting for lv in levels):
            return "опасно"
        return "совпало" if "reject" in levels else "осторожнее"
    ok = {"accept"} if lawyer == "none" else accepting
    if all(lv in ok for lv in levels):
        return "совпало"
    if any(lv == "reject" for lv in levels):
        return "строже"
    return "осторожнее"


def run_golden(labels_path: str, anon_dir: str, config: dict) -> dict:
    """Сравнить разбор программы с разметкой юриста. config: {"pairs": {theirs: {playbook, role, our_authors}},
    "playbooks_dir": путь к плейбукам}."""
    from .parties import SideConfig  # noqa: PLC0415 (только здесь)
    from .playbook import load_playbook  # noqa: PLC0415

    with open(labels_path, encoding="utf-8") as f:
        rows = json.load(f)["rows"]
    pb_dir = config.get("playbooks_dir", "playbooks")
    reviews: dict[tuple, list] = {}
    for key in {(r.get("base") or "", r["theirs"]) for r in rows}:
        base, theirs = key
        cfg = config.get("pairs", {}).get(theirs, {})
        pb = load_playbook(os.path.join(pb_dir, cfg["playbook"])) if cfg.get("playbook") else None
        rv = review_files(os.path.join(anon_dir, theirs), os.path.join(anon_dir, base) if base else None, pb,
                          our_authors=cfg.get("our_authors") or None, side=SideConfig(confirm_role=cfg.get("role", "")))
        reviews[key] = rv.changes

    table, stats = [], defaultdict(int)
    for r in rows:
        found = [c for c in reviews[(r.get("base") or "", r["theirs"])] if clause_matches(r["clause"], c)]
        ours = r.get("author_side", "").startswith("мы")
        line = {"n": r["n"], "файл": r["theirs"], "пункт": r["clause"], "правок программы": len(found)}
        if ours:
            stats["ours_total"] += 1
            stats["ours_ok"] += 0 if found else 1
            line["итог"] = "правка наша — в разборе нет" if not found else "правка наша — показана как чужая"
            table.append(line)
            continue
        stats["rows"] += 1
        stats["found"] += 1 if found else 0
        topics = sorted({c.topic for c in found})
        line["тема юриста"], line["темы программы"] = r.get("topic", ""), ", ".join(topics)
        if found and r.get("topic", "").lower() in {t.lower() for t in topics}:
            stats["topic_ok"] += 1
        lawyer = lawyer_decision(r.get("decision", ""))
        if lawyer:
            levels = [c.level or "review" for c in found] or ["review"]
            verdict = compare_decision(lawyer, levels) if found else "пункт не найден"
            stats["dec_total"] += 1
            stats["dec_" + verdict] += 1
            line["решение юриста"], line["уровни программы"], line["итог"] = lawyer, ", ".join(levels), verdict
        table.append(line)

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else 0.0

    metrics = {
        "строк с правками контрагента": stats["rows"],
        "правка найдена в этом пункте, %": pct(stats["found"], stats["rows"]),
        "тема совпала с юристом, %": pct(stats["topic_ok"], stats["rows"]),
        "строк с решением юриста": stats["dec_total"],
        "решение: совпало": stats["dec_совпало"],
        "решение: осторожнее (ушло юристу)": stats["dec_осторожнее"],
        "решение: строже (отклонить вместо принять)": stats["dec_строже"],
        "решение: опасно (принять вместо встречного)": stats["dec_опасно"],
        "решение: пункт не найден": stats["dec_пункт не найден"],
        "наши правки не выданы за чужие": f'{stats["ours_ok"]} из {stats["ours_total"]}',
    }
    return {"metrics": metrics, "table": table}


def print_golden(result: dict) -> str:
    lines = ["Метрики на разметке юриста (золотой набор):"]
    lines += [f"  {k}: {v}" for k, v in result["metrics"].items()]
    lines.append("По строкам (только категории, без текста правок):")
    lines += ["  " + json.dumps(t, ensure_ascii=False) for t in result["table"]]
    return "\n".join(lines)
