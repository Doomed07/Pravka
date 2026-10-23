"""Веб-приложение на компьютере юриста: загрузить договор в браузере — получить отчёт.

Запуск: python -m pravki web (или двойной щелчок по «Правки.command»). Сервер слушает только этот компьютер
(127.0.0.1): договоры никуда не уходят. Без внешних библиотек — только стандартная библиотека Python.

Пояснения модели («ИИ») включаются, если задан адрес локальной модели: переменная окружения PRAVKI_LLM_URL
(например, http://localhost:11434/v1 для Ollama) и PRAVKI_LLM_MODEL. Решения по правкам всё равно принимает плейбук.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import shutil
import threading
import time
import traceback
import webbrowser
from email.parser import BytesParser
from email.policy import HTTP
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse

import yaml

from .docx_reader import DocxError
from .llm import Explainer, LLMError, OpenAICompatClient
from .parties import PartiesError, RoleCheckError, SideConfig, profile_from_args
from .pipeline import DISCLAIMER, review_files
from .playbook import PlaybookError, load_playbook
from .report import render_html, render_xlsx, write_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYBOOKS = os.path.join(ROOT, "playbooks")
STORE = os.path.join(ROOT, "projects", "web")
SETTINGS = os.path.join(ROOT, "data", "web_settings.json")
MAX_UPLOAD = 30 * 1024 * 1024
_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


# ----------------------------------------------------------------------------- данные
def list_playbooks() -> list[dict]:
    out = []
    for sub, label in (("private", ""), ("", " (учебный пример)")):
        d = os.path.join(PLAYBOOKS, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(d, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError):
                continue
            out.append({"key": os.path.join(sub, fn) if sub else fn, "name": str(data.get("name", fn)) + label,
                        "role": str(data.get("our_role", "")), "path": path})
    return out


def load_settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def history(limit: int = 30) -> list[dict]:
    if not os.path.isdir(STORE):
        return []
    items = []
    for rid in sorted(os.listdir(STORE), reverse=True):
        meta = os.path.join(STORE, rid, "meta.json")
        if _ID.match(rid) and os.path.exists(meta):
            try:
                with open(meta, encoding="utf-8") as f:
                    m = json.load(f)
                m["id"] = rid
                items.append(m)
            except (OSError, ValueError):
                pass
        if len(items) >= limit:
            break
    return items


def make_explainer():
    url = os.environ.get("PRAVKI_LLM_URL", "").strip()
    if not url:
        return None
    return Explainer(OpenAICompatClient(url, os.environ.get("PRAVKI_LLM_MODEL", "local")))


# ----------------------------------------------------------------------------- страницы
CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--mute:#667085;--line:#e3e6eb;--acc:#2f5597;--warn:#b54708;--warnbg:#fff4e5;--ok:#027a48}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
header{background:var(--acc);color:#fff;padding:14px 24px;display:flex;gap:16px;align-items:baseline}
header a{color:#fff;text-decoration:none;font-weight:600;font-size:18px}header span{opacity:.8;font-size:13px}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:18px}
h1{font-size:20px;margin:0 0 14px}h2{font-size:16px;margin:0 0 10px}
label{display:block;font-weight:600;margin:14px 0 6px}.hint{color:var(--mute);font-size:13px;font-weight:400}
input[type=text],select{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;font:inherit;background:#fff}
input[type=file]{width:100%;padding:10px;border:1px dashed #b8c0cc;border-radius:8px;background:#fafbfc}
.row{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:700px){.row{grid-template-columns:1fr}}
button,.btn{display:inline-block;background:var(--acc);color:#fff;border:0;border-radius:8px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
.btn.sec{background:#fff;color:var(--acc);border:1px solid var(--acc)}
.alert{background:var(--warnbg);border:1px solid #f5c38b;color:#7a2e0e;border-radius:8px;padding:12px 14px;margin-bottom:14px}
.okmsg{color:var(--ok)}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mute);font-weight:600}.num{font-size:26px;font-weight:700}.stats{display:flex;gap:28px;flex-wrap:wrap}
.stats div span{display:block;color:var(--mute);font-size:13px}iframe{width:100%;height:78vh;border:1px solid var(--line);border-radius:10px;background:#fff}
footer{color:var(--mute);font-size:13px;text-align:center;padding:16px}.check{display:flex;gap:8px;align-items:flex-start;font-weight:400}
"""


def page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html lang=ru><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
            f"<header><a href='/'>Правки</a><span>разбор правок контрагента · работает только на этом компьютере</span></header>"
            f"<main>{body}</main><footer>{html.escape(DISCLAIMER)}</footer></body></html>").encode("utf-8")


def e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def form_page(msg: str = "", values: dict | None = None, need_confirm: str = "") -> bytes:
    v = {**load_settings(), **(values or {})}
    pbs = list_playbooks()
    opts = "".join(f"<option value='{e(p['key'])}' data-role='{e(p['role'])}'{' selected' if p['key'] == v.get('playbook') else ''}>"
                   f"{e(p['name'])}</option>" for p in pbs)
    opts = "<option value=''>Без плейбука — только найти и показать правки</option>" + opts
    ai = ("<span class=okmsg>включены (локальная модель)</span>" if os.environ.get("PRAVKI_LLM_URL")
          else "выключены — решения принимает плейбук; подключение локальной модели настраивается отдельно")
    confirm = ""
    if need_confirm:
        confirm = (f"<label class=check><input type=checkbox name=confirm_role value='{e(need_confirm)}' checked> "
                   f"Подтверждаю: в этом договоре мы — «{e(need_confirm)}»</label>")
    hist = history()
    rows = "".join(
        f"<tr><td>{e(h.get('created', '')[:16].replace('T', ' '))}</td><td><a href='/r/{e(h['id'])}'>{e(h.get('theirs_name', ''))}</a></td>"
        f"<td>{e(h.get('playbook_name', '—'))}</td><td>{e(h.get('total', ''))}</td><td>{e(h.get('lawyer', ''))}</td></tr>" for h in hist)
    hist_html = (f"<div class=card><h2>Прошлые отчёты</h2><table><tr><th>Когда</th><th>Файл контрагента</th><th>Плейбук</th>"
                 f"<th>Правок</th><th>Решает юрист</th></tr>{rows}</table></div>") if hist else ""
    alert = f"<div class=alert>{msg}</div>" if msg else ""
    return page("Правки — новый разбор", f"""
<div class=card><h1>Новый разбор</h1>{alert}
<form method=post action=/review enctype=multipart/form-data>
<div class=row>
 <div><label>Версия контрагента <span class=hint>(.docx, что прислали)</span></label><input type=file name=theirs accept=.docx required></div>
 <div><label>Наша версия <span class=hint>(.docx, что отправляли; нужна, чтобы найти правки без режима рецензирования)</span></label>
 <input type=file name=base accept=.docx></div>
</div>
<label>Плейбук <span class=hint>(тип договора и наша сторона)</span></label><select name=playbook id=pb>{opts}</select>
{confirm}
<label class=check><input type=checkbox name=confirm_role_any value=1{' checked' if v.get('confirm_role_any') else ''}>
 Наша сторона в договоре называется иначе, чем в плейбуке (например, «Участник» вместо «Заказчика») — подтверждаю роль плейбука вручную</label>
<div class=row>
 <div><label>Авторы наших правок в Word <span class=hint>(через запятую)</span></label>
 <input type=text name=our_authors value='{e(v.get('our_authors', ''))}' placeholder='например: kandu, Zuev Pavel'></div>
 <div><label>ИНН или наименование нашей компании <span class=hint>(по ним программа найдёт нашу сторону)</span></label>
 <input type=text name=company value='{e(v.get('company', ''))}' placeholder='например: 7701234567'></div>
</div>
<p class=hint>Пояснения ИИ: {ai}.</p>
<button type=submit>Разобрать</button>
</form></div>{hist_html}""")


def report_page(rid: str) -> bytes:
    d = os.path.join(STORE, rid)
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        m = json.load(f)
    warns = "".join(f"<li>{e(w)}</li>" for w in m.get("warnings", []))
    c = m.get("counts", {})
    stat = "".join(f"<div><span>{e(k)}</span><b class=num>{e(c.get(k, 0))}</b></div>" for k in
                   ("всего", "нужно решение юриста", "красные линии", "тихие правки", "комментарии"))
    return page("Правки — отчёт", f"""
<div class=card><h1>{e(m.get('theirs_name'))}</h1>
<p class=hint>Наша версия: {e(m.get('base_name') or 'не загружена')} · Плейбук: {e(m.get('playbook_name') or 'без плейбука')} ·
Сторона: {e(m.get('side') or '—')}</p>
<div class=stats>{stat}</div>
{f'<div class=alert style="margin-top:14px"><b>Обратите внимание</b><ul>{warns}</ul></div>' if warns else ''}
<p><a class=btn href='/r/{rid}/report.html' target=_blank>Открыть отчёт в новой вкладке</a>
 <a class='btn sec' href='/r/{rid}/report.xlsx'>Скачать Excel</a> <a class='btn sec' href='/'>Новый разбор</a></p></div>
<iframe src='/r/{rid}/report.html' title='Отчёт'></iframe>""")


# ----------------------------------------------------------------------------- запросы
def parse_multipart(ctype: str, body: bytes) -> tuple[dict, dict]:
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body)
    fields, files = {}, {}
    if not msg.is_multipart():
        return fields, files
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        data = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            if data:
                files[name] = (filename, data)
        else:
            fields[name] = data.decode("utf-8", "replace").strip()
    return fields, files


def _display_name(raw: str) -> str:
    try:
        return raw.encode("latin-1").decode("utf-8")  # браузер прислал UTF-8 без кодировки в заголовке
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def run_review(fields: dict, files: dict) -> tuple[str | None, bytes | None]:
    """Вернуть (id отчёта, None) или (None, страница с сообщением)."""
    if "theirs" not in files:
        return None, form_page("Загрузите версию контрагента (.docx).", fields)
    authors = [a.strip() for a in re.split(r"[,;\n]", fields.get("our_authors", "")) if a.strip()]
    company = fields.get("company", "")
    inns = re.findall(r"\b\d{10}(?:\d{2})?\b", company)
    names = [] if inns else ([company] if company else [])
    settings = {"our_authors": fields.get("our_authors", ""), "company": company, "playbook": fields.get("playbook", ""),
                "confirm_role_any": fields.get("confirm_role_any", "")}
    save_settings(settings)

    pb = None
    pbinfo = next((p for p in list_playbooks() if p["key"] == fields.get("playbook")), None)
    if pbinfo:
        pb = load_playbook(pbinfo["path"])
    confirm = fields.get("confirm_role", "")
    if not confirm and fields.get("confirm_role_any") and pb is not None:
        confirm = pb.our_role

    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    d = os.path.join(STORE, rid)
    os.makedirs(d, exist_ok=True)
    theirs_name, theirs_data = files["theirs"]
    theirs_path = os.path.join(d, "theirs.docx")
    with open(theirs_path, "wb") as f:
        f.write(theirs_data)
    base_path, base_name = None, ""
    if "base" in files:
        base_name, base_data = files["base"]
        base_path = os.path.join(d, "base.docx")
        with open(base_path, "wb") as f:
            f.write(base_data)
    try:
        side = SideConfig(profile=profile_from_args(names, inns), confirm_role=confirm)
        rv = review_files(theirs_path, base_path, pb, our_authors=authors, explainer=make_explainer(), side=side)
    except RoleCheckError as ex:
        shutil.rmtree(d, ignore_errors=True)
        role = pb.our_role if pb else ""
        return None, form_page(f"<b>Сторона договора не подтверждена.</b> {e(ex)}<br>Если мы действительно «{e(role)}», "
                               f"отметьте подтверждение ниже и загрузите файлы ещё раз.", settings, need_confirm=role)
    except (DocxError, PlaybookError, PartiesError, LLMError) as ex:
        shutil.rmtree(d, ignore_errors=True)
        return None, form_page(f"Не удалось разобрать: {e(ex)}", settings)
    with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as f:
        f.write(render_html(rv, pb.priority_topics if pb else None))
    render_xlsx(rv, os.path.join(d, "report.xlsx"))
    write_json(rv, os.path.join(d, "changes.json"))
    c = rv.counts()
    meta = {"created": time.strftime("%Y-%m-%dT%H:%M"), "theirs_name": _display_name(theirs_name), "base_name": _display_name(base_name),
            "playbook_name": pb.name if pb else "", "side": rv.side.message if rv.side else "", "warnings": rv.warnings,
            "counts": c, "total": c.get("всего"), "lawyer": c.get("нужно решение юриста")}
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return rid, None


class Handler(BaseHTTPRequestHandler):
    server_version = "Pravki"

    def log_message(self, fmt, *args):  # без имён файлов в журнале терминала
        pass

    def _send(self, body: bytes, ctype="text/html; charset=utf-8", status=HTTPStatus.OK, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, url: str):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _local_only(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):  # защита от подмены адреса (DNS rebinding)
            self._send(page("Нет доступа", "<div class=card>Доступ только с этого компьютера.</div>"), status=HTTPStatus.FORBIDDEN)
            return False
        return True

    def do_GET(self):
        if not self._local_only():
            return
        path = urlparse(self.path).path
        if path == "/":
            return self._send(form_page())
        m = re.match(r"^/r/([0-9a-f-]+)(/report\.html|/report\.xlsx)?/?$", path)
        if m and _ID.match(m.group(1)) and os.path.isdir(os.path.join(STORE, m.group(1))):
            rid, part = m.group(1), m.group(2)
            if not part:
                return self._send(report_page(rid))
            fpath = os.path.join(STORE, rid, part.lstrip("/"))
            with open(fpath, "rb") as f:
                data = f.read()
            if part.endswith(".xlsx"):
                return self._send(data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  extra={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('Правки_' + rid + '.xlsx')}"})
            return self._send(data, extra={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})
        return self._send(page("Не найдено", "<div class=card>Страница не найдена. <a href='/'>На главную</a></div>"),
                          status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self._local_only():
            return
        if urlparse(self.path).path != "/review":
            return self._send(b"", status=HTTPStatus.NOT_FOUND)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            return self._send(form_page("Файлы слишком большие (больше 30 МБ) или не переданы."), status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        body = self.rfile.read(length)
        try:
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
            rid, err = run_review(fields, files)
        except Exception:  # noqa: BLE001 — показать ошибку юристу, а не оборвать соединение
            traceback.print_exc()
            return self._send(form_page("Внутренняя ошибка программы. Текст ошибки — в окне Терминала; пришлите его разработчику."),
                              status=HTTPStatus.INTERNAL_SERVER_ERROR)
        if err is not None:
            return self._send(err)
        return self._redirect(f"/r/{rid}")


def serve(port: int = 8765, open_browser: bool = True) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Правки запущены: {url}\nОкно Терминала не закрывайте; чтобы остановить — Ctrl+C.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        srv.server_close()
