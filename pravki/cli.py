"""Командная строка: python -m pravki <команда>."""
from __future__ import annotations

import argparse
import os
import sys

from . import journal
from .docx_reader import DocxError
from .evaluate import print_report, run_synthetic
from .llm import Explainer, LLMError, OpenAICompatClient
from .pipeline import DISCLAIMER, review_files
from .playbook import PlaybookError, load_playbook
from .report import render_html, render_xlsx, write_json
from .synth import generate_case

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYBOOK_DIR = os.path.join(os.path.dirname(HERE), "playbooks")


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def cmd_review(a) -> int:
    pb = load_playbook(a.playbook) if a.playbook else None
    explainer = None
    if a.llm_url:
        explainer = Explainer(OpenAICompatClient(a.llm_url, a.llm_model, allow_remote=a.allow_remote))
    rv = review_files(a.theirs, a.base, pb, our_authors=a.our_author, explainer=explainer, ordering=a.order)
    out = a.out
    round_n = None
    if a.project:
        if not os.path.exists(os.path.join(a.project, "journal.json")):
            journal.init_project(a.project, a.name or os.path.basename(os.path.abspath(a.project)))
        round_n = journal.add_round(a.project, rv)
        out = out or journal.round_dir(a.project, round_n)
    out = out or "."
    os.makedirs(out, exist_ok=True)
    prio = pb.priority_topics if pb else None
    _write(os.path.join(out, "report.html"), render_html(rv, prio))
    render_xlsx(rv, os.path.join(out, "report.xlsx"))
    write_json(rv, os.path.join(out, "changes.json"))
    c = rv.counts()
    print(f"Правок: {c['всего']} (в рецензировании {c['в рецензировании']}, комментариев {c['комментарии']}, "
          f"тихих {c['тихие правки']}, найдено сравнением {c['найдено сравнением']})")
    print(f"Нужно решение юриста: {c['нужно решение юриста']}; красные линии: {c['красные линии']}; вне плейбука: {c['вне плейбука']}")
    for w in rv.warnings:
        print("Внимание:", w)
    if round_n:
        print(f"Раунд {round_n} записан в журнал проекта {a.project}")
    print(f"Отчёты: {os.path.join(out, 'report.html')}, {os.path.join(out, 'report.xlsx')}, {os.path.join(out, 'changes.json')}")
    print(DISCLAIMER)
    return 0


def cmd_decide(a) -> int:
    c = journal.decide(a.project, a.change_id, a.status, a.note or "", a.round)
    print(f"{c['id']}: {journal.STATUS_RU[c['status']]}")
    return 0


def cmd_history(a) -> int:
    print(journal.history_text(a.project))
    return 0


def cmd_eval(a) -> int:
    pbs = {
        "services": load_playbook(os.path.join(PLAYBOOK_DIR, "services_example.yaml")),
        "rent": load_playbook(os.path.join(PLAYBOOK_DIR, "rent_example.yaml")),
    }
    res = run_synthetic(a.pairs, a.seed, pbs)
    print(print_report(res, a.errors))
    return 0


def cmd_synth(a) -> int:
    case = generate_case(a.out, a.template, a.seed, a.numbering)
    for k, v in case["paths"].items():
        print(f"{k}: {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pravki", description="Разбор правок контрагента в договоре (docx)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="разобрать версию контрагента")
    r.add_argument("theirs", help="docx, который прислал контрагент")
    r.add_argument("--base", help="docx, который отправили мы (нужен для поиска «тихих» правок)")
    r.add_argument("--playbook", help="файл плейбука .yaml")
    r.add_argument("--our-author", action="append", default=[], help="автор наших правок в рецензировании (можно несколько раз)")
    r.add_argument("--out", help="папка для отчётов")
    r.add_argument("--project", help="папка проекта: раунд запишется в журнал")
    r.add_argument("--name", help="название проекта (при первом раунде)")
    r.add_argument("--order", choices=["priority", "doc"], default="priority", help="порядок правок в отчёте")
    r.add_argument("--llm-url", help="адрес локальной модели, например http://localhost:8080/v1")
    r.add_argument("--llm-model", default="local", help="имя модели на сервере")
    r.add_argument("--allow-remote", action="store_true", help="разрешить нелокальный адрес модели (осознанно!)")
    r.set_defaults(fn=cmd_review)

    d = sub.add_parser("decide", help="записать решение юриста по правке")
    d.add_argument("project")
    d.add_argument("change_id")
    d.add_argument("status", choices=list(journal.DECISIONS))
    d.add_argument("--note")
    d.add_argument("--round", type=int)
    d.set_defaults(fn=cmd_decide)

    h = sub.add_parser("history", help="показать журнал раундов")
    h.add_argument("project")
    h.set_defaults(fn=cmd_history)

    e = sub.add_parser("eval", help="проверить качество на синтетических договорах")
    e.add_argument("--pairs", type=int, default=40)
    e.add_argument("--seed", type=int, default=1000)
    e.add_argument("--errors", type=int, default=20)
    e.set_defaults(fn=cmd_eval)

    s = sub.add_parser("synth", help="создать пример: наша версия + версия контрагента с правками")
    s.add_argument("out")
    s.add_argument("--template", choices=["services", "rent"], default="services")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--numbering", choices=["auto", "manual"])
    s.set_defaults(fn=cmd_synth)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (DocxError, PlaybookError, journal.JournalError, LLMError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"Ошибка: файл не найден: {e.filename}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
