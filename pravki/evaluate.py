"""Оценка качества разбора на синтетических парах документов (и на вашем золотом наборе в том же формате)."""
from __future__ import annotations

import json
import os
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


def run_synthetic(n_pairs: int = 40, seed0: int = 1000, playbooks: dict | None = None, workdir: str | None = None) -> dict:
    playbooks = playbooks or {}
    stats = defaultdict(int)
    errors: list[dict] = []
    cm = tempfile.TemporaryDirectory() if workdir is None else None
    root = workdir or cm.name  # type: ignore[union-attr]
    try:
        for k in range(n_pairs):
            template = "services" if k % 2 == 0 else "rent"
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
