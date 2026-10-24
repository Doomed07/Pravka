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
  POST /parties    — multipart: theirs (docx/odt/pdf), company. 200 — {"parties": [{"role","name","inn"}],
                     "counterparty": {"name","inn","role"} | null}: стороны из преамбулы и контрагент (сторона, не совпавшая
                     с вашей компанией). Быстро: ни плейбука, ни модели.
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
from urllib.parse import parse_qs, urlparse

import yaml

from .annotate import annotate_docx
from .answer import build_answer
from .docx_reader import DocxError
from .llm import Explainer, LLMError, OpenAICompatClient, is_local
from .parties import (PartiesError, RoleCheckError, SideConfig, detect_our_party, parties_of, profile_from_args)
from .readers import read_document, sniff_format
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


LAW_FILE = os.environ.get("PRAVKI_LAW", os.path.join(os.path.dirname(__file__), "law", "gk.jsonl"))
MAX_EMBED = 64  # текстов за один запрос векторов


def _model_url_allowed(url: str) -> bool:
    trusted = {h.strip() for h in os.environ.get("PRAVKI_LLM_TRUSTED_HOSTS", "ollama,host.docker.internal").split(",") if h.strip()}
    return is_local(url) or (urlparse(url).hostname or "") in trusted


def make_embedder():
    """Клиент модели для векторов (по умолчанию bge-m3 на том же сервере Ollama, что и GigaChat). None — не настроена."""
    url = (os.environ.get("PRAVKI_EMBED_URL") or os.environ.get("PRAVKI_LLM_URL", "")).strip()
    if not url:
        return None
    return OpenAICompatClient(url, "", allow_remote=_model_url_allowed(url))


def embed_model() -> str:
    return os.environ.get("PRAVKI_EMBED_MODEL", "bge-m3")


_LAW_CACHE: dict = {}


def law_points() -> tuple[str, list[dict]]:
    """Действующие пункты ГК РФ для загрузки в базу и версия набора (меняется вместе с текстом)."""
    import hashlib

    from .law import load_jsonl

    if not _LAW_CACHE:
        with open(LAW_FILE, "rb") as f:
            version = hashlib.sha256(f.read()).hexdigest()[:16]
        points = []
        for a in load_jsonl(LAW_FILE):
            if a.lost:
                continue
            for seq, p in enumerate(a.points):
                points.append({"code": a.code, "article": a.number, "seq": seq, "point": p.number, "title": a.title, "section": a.section,
                               "chapter": a.chapter, "paragraph": a.paragraph, "edited": a.edited, "text": p.text})
        _LAW_CACHE.update(version=version, points=points)
    return _LAW_CACHE["version"], _LAW_CACHE["points"]


def law_page(query: str) -> tuple[int, dict]:
    """GET /law?offset=0&limit=500 — часть пунктов ГК РФ и версия набора."""
    q = parse_qs(query)
    try:
        offset, limit = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["500"])[0])
    except ValueError:
        return 400, {"error": "bad_request", "message": "offset и limit — числа."}
    if offset < 0 or not 0 < limit <= 1000:
        return 400, {"error": "bad_request", "message": "offset ≥ 0, limit от 1 до 1000."}
    version, points = law_points()
    return 200, {"version": version, "total": len(points), "points": points[offset:offset + limit]}


def embed(body: bytes) -> tuple[int, dict]:
    """POST /embed {"texts": [...]} — векторы для поиска по смыслу. 503 — модель для векторов не настроена."""
    try:
        texts = json.loads(body.decode("utf-8")).get("texts")
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return 400, {"error": "bad_request", "message": "Нужен JSON {\"texts\": [...]}."}
    if not isinstance(texts, list) or not 0 < len(texts) <= MAX_EMBED or not all(isinstance(t, str) and t.strip() for t in texts):
        return 400, {"error": "bad_request", "message": f"texts — от 1 до {MAX_EMBED} непустых строк."}
    client = make_embedder()
    if client is None:
        return 503, {"error": "no_model", "message": "Модель для векторов не настроена (PRAVKI_EMBED_URL или PRAVKI_LLM_URL)."}
    try:
        vectors = client.embed([t[:4000] for t in texts], embed_model())
    except LLMError as ex:
        return 502, {"error": "llm", "message": str(ex)}
    return 200, {"model": embed_model(), "vectors": vectors}


def make_explainer():
    url = os.environ.get("PRAVKI_LLM_URL", "").strip()
    if not url:
        return None
    return Explainer(OpenAICompatClient(url, os.environ.get("PRAVKI_LLM_MODEL", "local"), allow_remote=_model_url_allowed(url)))


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
            source_format = sniff_format(theirs)  # docx, odt или pdf: по содержимому, имя файла движку не передаётся
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
        unified = ""  # Word с примечаниями собирается из XML файла контрагента: только для docx
        if source_format == "docx":
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
        "contract_type": pb.contract_type if pb else "",  # для «как решали раньше»: подсказки только того же типа
        "report_html": render_html(rv, pb.priority_topics if pb else None),
        "report_xlsx": xlsx,
        "changes": [c.to_dict() for c in rv.changes],
        "document": rv.document,
        "unified_docx": unified,
        "source_format": source_format,
        "disclaimer": DISCLAIMER,
    }


def company_profile(company: str):
    """Профиль нашей компании из строки «ИНН или наименование» (как в форме разбора)."""
    inns = re.findall(r"\b\d{10}(?:\d{2})?\b", company)
    names = [] if inns else ([company] if company else [])
    return profile_from_args(names, inns)


def _pretty(name: str) -> str:
    """Разбор приводит кавычки к прямым; в названии контрагента возвращаем «ёлочки»."""
    return re.sub(r'"([^"]+)"', r"«\1»", name)


def detect_parties(fields: dict, files: dict) -> tuple[int, dict]:
    """Стороны договора и контрагент по преамбуле. Контрагент — сторона, не совпавшая с нашей компанией;
    нашу сторону определить не удалось (нет профиля, не найдена, найдена дважды) — контрагента нет (None),
    юрист выбирает или вводит его сам."""
    if "theirs" not in files:
        return 400, {"error": "bad_request", "message": "Не передан файл договора (theirs)."}
    with tempfile.TemporaryDirectory(prefix="pravki-") as d:
        path = os.path.join(d, "theirs.docx")
        with open(path, "wb") as f:
            f.write(files["theirs"])
        try:
            doc = read_document(path)
            parties = parties_of(doc, "rejected")
        except (DocxError, PartiesError) as ex:
            return 400, {"error": "bad_file", "message": str(ex)}
    ours, _, _ = detect_our_party(parties, company_profile(fields.get("company", "")))
    other = [p for p in parties if p is not ours]
    counterparty = None
    if ours is not None and len(other) == 1:
        counterparty = {"name": _pretty(other[0].name), "inn": other[0].inn, "role": other[0].role}
    return 200, {"parties": [{"role": p.role, "name": _pretty(p.name), "inn": p.inn} for p in parties], "counterparty": counterparty}


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
        if path == "/law":
            return self._json(*law_page(urlparse(self.path).query))
        return self._json(404, {"error": "not_found", "message": "Нет такого адреса."})

    def do_POST(self):
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path == "/embed":
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 1024 * 1024:
                return self._json(413, {"error": "too_large", "message": "Запрос пустой или больше 1 МБ."})
            return self._json(*embed(self.rfile.read(length)))
        if path not in ("/review", "/answer", "/parties"):
            return self._json(404, {"error": "not_found", "message": "Нет такого адреса."})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            return self._json(413, {"error": "too_large", "message": "Файлы не переданы или больше 30 МБ."})
        body = self.rfile.read(length)
        try:
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
            handler = {"/review": review, "/answer": answer, "/parties": detect_parties}[path]
            status, data = handler(fields, files)
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
