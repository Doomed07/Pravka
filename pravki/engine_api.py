"""Внутренний HTTP-сервис движка «Правки» для веб-сервиса на Go.

Запускается в отдельном контейнере (`python -m pravki engine`) и доступен только из внутренней сети Docker.
Принимает договор, возвращает разбор: сводку, HTML-отчёт, Excel (base64), список правок, единую версию
(абзацы с правками) и её docx с примечаниями (base64). Хранением, входом
и пользователями занимается Go-сервис; движок ничего не сохраняет на диск дольше одного запроса.

Эндпоинты:
  GET  /health     — {"ok": true, "llm": bool}
  GET  /playbooks  — [{"key", "name", "role"}]
  POST /review     — multipart: theirs (docx), base (docx, необязательно), playbook, our_authors, company,
                     confirm_role. 200 — разбор; 422 — сторона договора не подтверждена; 400 — файл не разобран.
  POST /answer     — multipart: unified (docx единой версии), changes (JSON), choices (JSON), author,
                     document (JSON единой версии, необязательно: нужен, чтобы вернуть удалённый без отметки абзац).
                     200 — ответ контрагенту в Word (base64) по решениям юриста.

Если задан ENGINE_TOKEN, каждый запрос должен нести заголовок X-Engine-Token с тем же значением.
Модель для пояснений: PRAVKI_LLM_URL и PRAVKI_LLM_MODEL; имена хостов внутренней сети (ollama,
host.docker.internal) перечисляются в PRAVKI_LLM_TRUSTED_HOSTS — только для них снимается запрет нелокального адреса.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import tempfile
import traceback
from email.parser import BytesParser
from email.policy import HTTP
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import yaml

from .annotate import annotate_docx
from .answer import build_answer
from .docx_reader import DocxError
from .llm import Explainer, LLMError, OpenAICompatClient, is_local
from .parties import PartiesError, RoleCheckError, SideConfig, profile_from_args
from .pipeline import DISCLAIMER, review_files
from .playbook import PlaybookError, load_playbook
from .report import render_html, render_xlsx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYBOOKS = os.environ.get("PRAVKI_PLAYBOOKS", os.path.join(ROOT, "playbooks"))
MAX_UPLOAD = 30 * 1024 * 1024


# Сейчас в работе договоры поставки и оказания услуг: их плейбуки идут в списке первыми (решение владельца 2026-10-23).
FOCUS_TYPES = ("supply", "services")


def _focus_rank(data: dict) -> int:
    kind = str(data.get("contract_type", ""))
    return FOCUS_TYPES.index(kind) if kind in FOCUS_TYPES else len(FOCUS_TYPES)


def list_playbooks(root: str | None = None) -> list[dict]:
    root = root or PLAYBOOKS
    out = []
    for sub, label in (("private", ""), ("", " (учебный пример)")):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        group = []
        for fn in sorted(os.listdir(d)):
            if not fn.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(d, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError):
                continue
            group.append((_focus_rank(data), {"key": f"{sub}/{fn}" if sub else fn, "name": str(data.get("name", fn)) + label,
                                              "role": str(data.get("our_role", "")), "path": path}))
        out.extend(item for _, item in sorted(group, key=lambda g: g[0]))  # sorted устойчив: внутри типа — по имени файла
    return out


def make_explainer():
    url = os.environ.get("PRAVKI_LLM_URL", "").strip()
    if not url:
        return None
    trusted = {h.strip() for h in os.environ.get("PRAVKI_LLM_TRUSTED_HOSTS", "ollama,host.docker.internal").split(",") if h.strip()}
    host = urlparse(url).hostname or ""
    allow = is_local(url) or host in trusted
    return Explainer(OpenAICompatClient(url, os.environ.get("PRAVKI_LLM_MODEL", "local"), allow_remote=allow))


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
        if part.get_filename() is not None:
            if data:
                files[name] = data
        else:
            fields[name] = data.decode("utf-8", "replace").strip()
    return fields, files


def review(fields: dict, files: dict, playbooks_root: str | None = None) -> tuple[int, dict]:
    """Разобрать договор. Возвращает (HTTP-статус, тело ответа)."""
    if "theirs" not in files:
        return 400, {"error": "bad_request", "message": "Не передан файл версии контрагента (theirs)."}
    authors = [a.strip() for a in re.split(r"[,;\n]", fields.get("our_authors", "")) if a.strip()]
    company = fields.get("company", "")
    inns = re.findall(r"\b\d{10}(?:\d{2})?\b", company)
    names = [] if inns else ([company] if company else [])
    pb = None
    key = fields.get("playbook", "")
    if key:
        info = next((p for p in list_playbooks(playbooks_root) if p["key"] == key), None)
        if info is None:
            return 400, {"error": "bad_request", "message": f"Плейбук «{key}» не найден."}
        pb = load_playbook(info["path"])
    confirm = fields.get("confirm_role", "")
    with tempfile.TemporaryDirectory(prefix="pravki-") as d:
        theirs = os.path.join(d, "theirs.docx")
        with open(theirs, "wb") as f:
            f.write(files["theirs"])
        base = None
        if "base" in files:
            base = os.path.join(d, "base.docx")
            with open(base, "wb") as f:
                f.write(files["base"])
        try:
            side = SideConfig(profile=profile_from_args(names, inns), confirm_role=confirm)
            rv = review_files(theirs, base, pb, our_authors=authors, explainer=make_explainer(), side=side)
        except RoleCheckError as ex:
            return 422, {"error": "role_not_confirmed", "message": str(ex), "role": pb.our_role if pb else ""}
        except (DocxError, PlaybookError, PartiesError) as ex:
            return 400, {"error": "bad_file", "message": str(ex)}
        except LLMError as ex:
            return 502, {"error": "llm", "message": f"Модель для пояснений недоступна: {ex}"}
        xlsx_path = os.path.join(d, "report.xlsx")
        render_xlsx(rv, xlsx_path)
        with open(xlsx_path, "rb") as f:
            xlsx = base64.b64encode(f.read()).decode("ascii")
        unified_path = os.path.join(d, "unified.docx")
        annotate_docx(theirs, unified_path, rv.changes, rv.document)
        with open(unified_path, "rb") as f:
            unified = base64.b64encode(f.read()).decode("ascii")
    return 200, {
        "counts": rv.counts(),
        "warnings": rv.warnings,
        "side": rv.side.message if rv.side else "",
        "playbook_name": pb.name if pb else "",
        "our_role": pb.our_role if pb else "",
        "report_html": render_html(rv, pb.priority_topics if pb else None),
        "report_xlsx": xlsx,
        "changes": [c.to_dict() for c in rv.changes],
        "document": rv.document,
        "unified_docx": unified,
        "disclaimer": DISCLAIMER,
    }


def answer(fields: dict, files: dict) -> tuple[int, dict]:
    """Ответ контрагенту: единая версия (unified) + правки разбора (changes, JSON) + выбор юриста (choices, JSON)
    + автор наших правок (author). 200 — {"answer_docx": base64, "stats": {...}}."""
    if "unified" not in files:
        return 400, {"error": "bad_request", "message": "Не передана единая версия договора (unified)."}
    try:
        changes = json.loads(fields.get("changes") or "[]")
        choices = json.loads(fields.get("choices") or "{}")
        document = json.loads(fields.get("document") or "[]")
    except json.JSONDecodeError:
        return 400, {"error": "bad_request", "message": "Правки или выбор юриста переданы не в формате JSON."}
    if not isinstance(changes, list) or not isinstance(choices, dict):
        return 400, {"error": "bad_request", "message": "Правки — список, выбор юриста — словарь."}
    with tempfile.TemporaryDirectory(prefix="pravki-") as d:
        src, out = os.path.join(d, "unified.docx"), os.path.join(d, "answer.docx")
        with open(src, "wb") as f:
            f.write(files["unified"])
        try:
            stats = build_answer(src, out, changes, choices, fields.get("author", ""), document if isinstance(document, list) else None)
        except DocxError as ex:
            return 400, {"error": "bad_file", "message": str(ex)}
        with open(out, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    return 200, {"answer_docx": data, "stats": stats, "disclaimer": DISCLAIMER}


class Handler(BaseHTTPRequestHandler):
    server_version = "PravkiEngine"

    def log_message(self, fmt, *args):  # без имён файлов и текста договоров в журнале
        pass

    def _json(self, status: int, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = os.environ.get("ENGINE_TOKEN", "")
        if token and not hmac.compare_digest(self.headers.get("X-Engine-Token", ""), token):
            self._json(401, {"error": "unauthorized", "message": "Неверный токен движка."})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"ok": True, "llm": bool(os.environ.get("PRAVKI_LLM_URL"))})
        if path == "/playbooks":
            return self._json(200, [{k: p[k] for k in ("key", "name", "role")} for p in list_playbooks()])
        return self._json(404, {"error": "not_found", "message": "Нет такого адреса."})

    def do_POST(self):
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path not in ("/review", "/answer"):
            return self._json(404, {"error": "not_found", "message": "Нет такого адреса."})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            return self._json(413, {"error": "too_large", "message": "Файлы не переданы или больше 30 МБ."})
        body = self.rfile.read(length)
        try:
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
            status, data = review(fields, files) if path == "/review" else answer(fields, files)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            status, data = 500, {"error": "internal", "message": "Внутренняя ошибка движка."}
        self._json(status, data)


def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Движок «Правки» слушает {host}:{port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
