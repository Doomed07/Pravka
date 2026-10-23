"""Командная строка: python -m pravki <команда>."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import journal
from .anonymize import Anonymizer, anonymize_docx, learn_docx, residual_candidates, scan_leaks
from .docx_reader import DocxError
from .evaluate import print_report, run_synthetic
from .llm import Explainer, LLMError, OpenAICompatClient
from .parties import PartiesError, RoleCheckError, SideConfig, canon_role, profile_from_args
from .pipeline import DISCLAIMER, review_files
from .playbook import PlaybookError, load_playbook
from .report import render_html, render_xlsx, write_json
from .synth import generate_case
from .worksheet import add_positions_sheet, build_worksheet, group_changes, load_labels

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
    side = SideConfig(profile=profile_from_args(a.our_name, a.our_inn, a.company), confirm_role=a.confirm_role or "")
    if a.project and pb is not None and not a.confirm_role:
        prev = journal.last_role(a.project)
        if prev and canon_role(prev) != canon_role(pb.our_role):
            print(f"Роль не совпала с предыдущими раундами проекта: раньше разбирали за «{prev}», сейчас плейбук роли "
                  f"«{pb.our_role}». Отчёт не создан. Если роль сменилась намеренно, подтвердите её: --confirm-role {pb.our_role}",
                  file=sys.stderr)
            return 3
    rv = review_files(a.theirs, a.base, pb, our_authors=a.our_author, explainer=explainer, ordering=a.order, side=side)
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
    if rv.side is not None:
        print(f"Сторона договора: {rv.side.message}")
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


def _pairs(items: list[str], what: str) -> dict[str, str]:
    out = {}
    for it in items:
        if "=" not in it:
            raise DocxError(f"{what}: ожидается «исходное=замена», получено «{it}»")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_anonymize(a) -> int:
    """Обезличить набор docx одной картой замен, чтобы пары версий остались парами."""
    anon = Anonymizer.from_json(open(a.map, encoding="utf-8").read()) if a.map and os.path.exists(a.map) else Anonymizer()
    anon.authors.update(_pairs(a.author, "--author"))
    anon.terms.update(_pairs(a.term, "--term"))
    anon._compiled = None
    for path in a.files:
        learn_docx(anon, path)
    os.makedirs(a.out, exist_ok=True)
    index, bad = {}, 0
    for n, path in enumerate(a.files, 1):
        dst = os.path.join(a.out, f"{a.prefix}{n:02d}.docx")
        summary = anonymize_docx(anon, path, dst)
        leaks = scan_leaks(anon, dst)
        index[os.path.basename(dst)] = path
        bad += len(leaks)
        print(f"{os.path.basename(dst)}: замен {summary['замен']}, картинок {summary['картинок заменено']}, "
              f"остатков {len(leaks)}" + ("" if not leaks else " — ПРОВЕРЬТЕ:"))
        for lk in leaks[:15]:
            print(f"   {lk}")
    if anon.pruned:
        print("Не приняты за фамилии (обычные слова в договоре): " + ", ".join(sorted(set(anon.pruned))))
    if a.map:
        _write(a.map, anon.to_json())
        _write(os.path.splitext(a.map)[0] + ".index.json", json.dumps(index, ensure_ascii=False, indent=1))
        print(f"Карта замен и список исходных файлов сохранены ({a.map}): в них настоящие данные, хранить только у себя.")
    if a.residual:
        agg: dict[str, int] = {}
        for n in range(1, len(a.files) + 1):
            for w, c in residual_candidates(os.path.join(a.out, f"{a.prefix}{n:02d}.docx"), 400):
                agg[w] = agg.get(w, 0) + c
        print("\nМогло остаться (слово — сколько раз). Названия, брендов и мероприятий здесь быть не должно; "
              "лишнее добавьте через --term «слово=замена»:")
        for w, c in sorted(agg.items(), key=lambda kv: -kv[1])[:a.residual]:
            print(f"  {c:3d}  {w}")
    return 4 if bad else 0


def cmd_worksheet(a) -> int:
    """Анкета разметки: правки контрагента из одного или нескольких раундов → xlsx для юриста."""
    from .docx_reader import read_docx, view_paragraphs
    from .parties import parse_parties

    rows, contracts = [], []
    kinds = _pairs(a.kind, "--kind")
    for spec in a.pair:
        if "=" not in spec:
            raise DocxError(f"--pair: ожидается «Название=версия_контрагента.docx[:наша_версия.docx]», получено «{spec}»")
        name, files = spec.split("=", 1)
        theirs, _, base = files.partition("::")
        rv = review_files(theirs, base or None, None, our_authors=a.our_author, ordering="doc")
        rows += group_changes(rv.changes, name.strip())
        try:
            text = "\n".join(t for _, t in view_paragraphs(read_docx(theirs), "accepted"))
            ps = [p for p in parse_parties(text) if p.name]
            seen, parties = set(), []
            for p in ps:
                if (p.role, p.name) not in seen:
                    seen.add((p.role, p.name))
                    parties.append(f"{p.role}: {p.name}")
            parties_txt = "; ".join(parties[:4])
        except DocxError:
            parties_txt = ""
        c = rv.counts()
        contracts.append({"name": name.strip(), "kind": kinds.get(name.strip(), ""), "parties": parties_txt,
                          "note": ("сравнение с нашей версией; " if base else "без нашей версии; ") +
                                  f"правок {c['всего']}, комментариев {c['комментарии']}, тихих {c['тихие правки']}"})
    n = build_worksheet(rows, a.out, contracts)
    print(f"Анкета: {n} строк → {a.out}")
    if a.positions:
        with open(a.positions, encoding="utf-8") as fh:
            m = add_positions_sheet(a.out, json.load(fh))
        print(f"Лист «Позиции (черновик)»: {m} строк")
    print(DISCLAIMER)
    return 0


def cmd_labels(a) -> int:
    labels = load_labels(a.xlsx)
    filled = [x for x in labels if x["decision"] or x["topic_ok"]]
    text = json.dumps(labels, ensure_ascii=False, indent=1)
    if a.out:
        _write(a.out, text)
    print(f"Строк в анкете: {len(labels)}, размечено: {len(filled)}" + (f" → {a.out}" if a.out else ""))
    return 0


def cmd_web(a) -> int:
    from .web import serve
    serve(a.port, not a.no_browser)
    return 0


def cmd_engine(a) -> int:
    from .engine_api import serve as serve_engine
    serve_engine(a.host, a.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pravki", description="Разбор правок контрагента в договоре (docx)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="разобрать версию контрагента")
    r.add_argument("theirs", help="docx, который прислал контрагент")
    r.add_argument("--base", help="docx, который отправили мы (нужен для поиска «тихих» правок)")
    r.add_argument("--playbook", help="файл плейбука .yaml")
    r.add_argument("--our-author", action="append", default=[], help="автор наших правок в рецензировании (можно несколько раз)")
    r.add_argument("--company", help="профиль нашей компании .yaml (names, inn): по нему определяется наша сторона в договоре")
    r.add_argument("--our-name", action="append", default=[], help="наименование нашей компании, как в договоре (можно несколько раз)")
    r.add_argument("--our-inn", action="append", default=[], help="ИНН нашей компании (можно несколько раз)")
    r.add_argument("--confirm-role", help="подтвердить нашу роль вручную, например «Исполнитель»; без этого при "
                                          "несовпадении или неопределённости стороны разбор не запускается")
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

    z = sub.add_parser("anonymize", help="обезличить договоры (названия, ФИО, реквизиты, авторы правок, свойства файла)")
    z.add_argument("files", nargs="+", help="исходные docx")
    z.add_argument("--out", required=True, help="папка для обезличенных копий")
    z.add_argument("--map", help="файл карты замен (json); если есть, подхватывается, чтобы замены не менялись между запусками")
    z.add_argument("--author", action="append", default=[], help="автор правок=замена, например «Иванов=Мы» (можно несколько раз)")
    z.add_argument("--term", action="append", default=[], help="слово=замена для того, что программа сама не находит (бренд, мероприятие)")
    z.add_argument("--prefix", default="doc", help="начало имени обезличенных файлов (имена исходных не сохраняются)")
    z.add_argument("--residual", type=int, nargs="?", const=60, default=0, help="показать слова, которые могли остаться")
    z.set_defaults(fn=cmd_anonymize)

    w = sub.add_parser("worksheet", help="анкета для разметки правок (xlsx), чтобы юрист указал тему и решение")
    w.add_argument("--pair", action="append", required=True,
                   help="«Название=версия_контрагента.docx::наша_версия.docx» (наша версия необязательна; можно несколько раз)")
    w.add_argument("--our-author", action="append", default=[], help="автор наших правок (можно несколько раз)")
    w.add_argument("--kind", action="append", default=[], help="«Название=вид договора» для листа «Договоры»")
    w.add_argument("--positions", help="json с выводами из ваших правок: добавит лист «Позиции (черновик)»")
    w.add_argument("--out", required=True, help="куда записать xlsx")
    w.set_defaults(fn=cmd_worksheet)

    lb = sub.add_parser("labels", help="прочитать заполненную анкету и сохранить ответы юриста в json")
    lb.add_argument("xlsx")
    lb.add_argument("--out")
    lb.set_defaults(fn=cmd_labels)

    wb = sub.add_parser("web", help="веб-приложение на этом компьютере: загрузить договор в браузере и получить отчёт")
    wb.add_argument("--port", type=int, default=8765)
    wb.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    wb.set_defaults(fn=cmd_web)

    en = sub.add_parser("engine", help="внутренний HTTP-сервис движка для веб-сервиса (Docker)")
    en.add_argument("--host", default="0.0.0.0")
    en.add_argument("--port", type=int, default=8000)
    en.set_defaults(fn=cmd_engine)

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
    except RoleCheckError as e:
        print(f"Сторона договора не подтверждена. {e}\nОтчёт не создан.", file=sys.stderr)
        return 3
    except (DocxError, PlaybookError, PartiesError, journal.JournalError, LLMError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"Ошибка: файл не найден: {e.filename}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
