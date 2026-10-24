"""Внутренний HTTP-сервис движка: разбор по запросу Go-сервиса, отказ без подтверждённой стороны, токен."""
import base64
import http.client
import json
import threading
import uuid

import pytest

from pravki import engine_api
from pravki.synth import generate_case


@pytest.fixture()
def engine(monkeypatch):
    monkeypatch.setenv("ENGINE_TOKEN", "secret")
    monkeypatch.delenv("PRAVKI_LLM_URL", raising=False)
    srv = engine_api.ThreadingHTTPServer(("127.0.0.1", 0), engine_api.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def _req(port, method, path, fields=None, files=None, token="secret"):
    headers = {"X-Engine-Token": token} if token else {}
    body = None
    if fields is not None or files is not None:
        b = uuid.uuid4().hex
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in (fields or {}).items()]
        parts += [f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{k}.docx"\r\n\r\n'.encode() + data + b"\r\n"
                  for k, data in (files or {}).items()]
        body = b"".join(parts) + f"--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request(method, path, body, headers)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"null")


def test_health_playbooks_and_token(engine):
    assert _req(engine, "GET", "/health")[1]["ok"] is True
    status, pbs = _req(engine, "GET", "/playbooks")
    assert status == 200 and any(p["key"] == "services_example.yaml" and p["role"] for p in pbs)
    assert all("path" not in p for p in pbs)  # путь на диске наружу не отдаём
    assert _req(engine, "GET", "/health", token="wrong")[0] == 401


def test_review_roundtrip(engine, tmp_path):
    case = generate_case(str(tmp_path / "c"), "services", 5)
    files = {"theirs": open(case["paths"]["tracked"], "rb").read(), "base": open(case["paths"]["base"], "rb").read()}
    status, data = _req(engine, "POST", "/review", {"playbook": "services_example.yaml", "company": "7701234567"}, files)
    assert status == 200, data
    assert data["counts"]["всего"] == len(data["changes"]) > 0
    assert "Черновик" in data["report_html"] and base64.b64decode(data["report_xlsx"])[:2] == b"PK"
    assert base64.b64decode(data["unified_docx"])[:2] == b"PK" and data["document"]
    assert {i for para in data["document"] for i in para["changes"]} == {c["id"] for c in data["changes"]}
    assert data["our_role"] == "Исполнитель"
    assert data["contract_type"] == "services"  # «как решали раньше» ищет по типу договора


def test_role_not_confirmed_and_bad_file(engine, tmp_path):
    case = generate_case(str(tmp_path / "c"), "services", 5)
    files = {"theirs": open(case["paths"]["tracked"], "rb").read()}
    status, data = _req(engine, "POST", "/review", {"playbook": "services_customer_example.yaml", "company": "7701234567"}, files)
    assert status == 422 and data["error"] == "role_not_confirmed" and data["role"] == "Заказчик"
    status, data = _req(engine, "POST", "/review", {"playbook": "services_customer_example.yaml", "company": "7701234567",
                                                    "confirm_role": "Заказчик"}, files)
    assert status == 200
    status, data = _req(engine, "POST", "/review", {}, {"theirs": b"not a docx"})
    assert status == 400 and data["error"] == "bad_file"
    status, data = _req(engine, "POST", "/review", {"playbook": "../etc/passwd"}, files)
    assert status == 400


def test_llm_trusted_docker_host(monkeypatch):
    monkeypatch.setenv("PRAVKI_LLM_URL", "http://ollama:11434/v1")
    assert engine_api.make_explainer() is not None
    monkeypatch.setenv("PRAVKI_LLM_URL", "https://api.example.com/v1")
    with pytest.raises(engine_api.LLMError):
        engine_api.make_explainer()


def test_focus_playbooks_come_first(tmp_path):
    from pravki.engine_api import list_playbooks

    (tmp_path / "private").mkdir()
    for name, kind in (("a_rent.yaml", "lease"), ("b_services.yaml", "services"), ("c_supply.yaml", "supply")):
        (tmp_path / "private" / name).write_text(f"name: {name}\ncontract_type: {kind}\nour_role: X\n", encoding="utf-8")
    (tmp_path / "z_supply.yaml").write_text("name: z\ncontract_type: supply\nour_role: Y\n", encoding="utf-8")
    keys = [p["key"] for p in list_playbooks(str(tmp_path))]
    assert keys == ["private/c_supply.yaml", "private/b_services.yaml", "private/a_rent.yaml", "z_supply.yaml"]


def test_answer_roundtrip(engine, tmp_path):
    case = generate_case(str(tmp_path / "c"), "services", 5)
    files = {"theirs": open(case["paths"]["tracked"], "rb").read(), "base": open(case["paths"]["base"], "rb").read()}
    status, data = _req(engine, "POST", "/review", {"playbook": "services_example.yaml", "company": "7701234567"}, files)
    assert status == 200
    tracked = [c for c in data["changes"] if c["revs"]]
    choices = {c["id"]: {"choice": "reject"} for c in tracked}
    status, ans = _req(engine, "POST", "/answer", {"changes": json.dumps(data["changes"]), "choices": json.dumps(choices),
                                                    "author": "Юрист"}, {"unified": base64.b64decode(data["unified_docx"])})
    assert status == 200, ans
    assert base64.b64decode(ans["answer_docx"])[:2] == b"PK" and ans["stats"]["reject"] == len(tracked)
    status, bad = _req(engine, "POST", "/answer", {"changes": "не json"}, {"unified": b"PK"})
    assert status == 400


def _post_json(port, path, data, token="secret"):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("POST", path, json.dumps(data).encode(), {"X-Engine-Token": token, "Content-Type": "application/json"})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"null")


def test_law_pages_skip_lost_articles(engine):
    status, first = _req(engine, "GET", "/law?offset=0&limit=3")
    assert status == 200 and len(first["points"]) == 3 and first["total"] > 4000 and len(first["version"]) == 16
    _, all_points = _req(engine, "GET", f"/law?offset=0&limit=1000")
    assert all(p["text"] and p["article"] for p in all_points["points"])
    status, tail = _req(engine, "GET", f"/law?offset={first['total'] - 1}&limit=10")
    assert status == 200 and len(tail["points"]) == 1 and tail["version"] == first["version"]
    arts = {p["article"] for p in engine_api.law_points()[1]}
    assert "506" in arts and "91" not in arts  # ст. 91 утратила силу
    assert _req(engine, "GET", "/law?limit=5000")[0] == 400
    assert _req(engine, "GET", "/law", token="wrong")[0] == 401


def test_embed_uses_local_model_and_needs_one(engine, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    got = {}

    class FakeOllama(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            got.update(path=self.path, body=json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data = [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(got["body"]["input"]))][::-1]
            out = json.dumps({"data": data}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    assert _post_json(engine, "/embed", {"texts": ["a"]})[0] == 503  # модель не настроена
    fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    monkeypatch.setenv("PRAVKI_EMBED_URL", f"http://127.0.0.1:{fake.server_address[1]}/v1")
    try:
        status, data = _post_json(engine, "/embed", {"texts": ["срок поставки", "неустойка"]})
        assert status == 200 and data["vectors"] == [[0.0, 1.0], [1.0, 1.0]]  # по порядку текстов
        assert got["path"] == "/v1/embeddings" and got["body"]["model"] == "bge-m3"
        assert _post_json(engine, "/embed", {"texts": []})[0] == 400
        assert _post_json(engine, "/embed", {"texts": ["x"] * (engine_api.MAX_EMBED + 1)})[0] == 400
        assert _post_json(engine, "/embed", {"texts": ["x"]}, token="wrong")[0] == 401
    finally:
        fake.shutdown()
    monkeypatch.setenv("PRAVKI_EMBED_URL", "http://8.8.8.8/v1")  # внешний адрес — нельзя (запрос не отправляется)
    with pytest.raises(engine_api.LLMError):
        engine_api.make_embedder()
