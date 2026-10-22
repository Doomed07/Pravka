"""Веб-приложение: загрузка договора через форму, отчёт, защита от доступа не с этого компьютера."""
import http.client
import os
import threading
import uuid

import pytest

from pravki import web
from pravki.synth import generate_case


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "STORE", str(tmp_path / "store"))
    monkeypatch.setattr(web, "SETTINGS", str(tmp_path / "settings.json"))
    srv = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def _post(port, fields, files, host="127.0.0.1"):
    b = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (name, data) in files.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                     f'Content-Type: application/octet-stream\r\n\r\n'.encode("utf-8") + data + b"\r\n")
    body = b"".join(parts) + f"--{b}--\r\n".encode()
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("POST", "/review", body, {"Content-Type": f"multipart/form-data; boundary={b}", "Host": host})
    return c.getresponse()


def _get(port, path, host="127.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", path, headers={"Host": host})
    return c.getresponse()


def test_upload_and_report(server, tmp_path):
    case = generate_case(str(tmp_path / "case"), "services", 3)
    files = {"theirs": ("версия контрагента.docx", open(case["paths"]["tracked"], "rb").read()),
             "base": ("наша.docx", open(case["paths"]["base"], "rb").read())}
    r = _post(server, {"playbook": "services_example.yaml", "company": "7701234567", "our_authors": ""}, files)
    assert r.status == 303
    loc = r.getheader("Location")
    page = _get(server, loc).read().decode()
    assert "Обратите внимание" in page or "всего" in page
    assert "версия контрагента.docx" in page
    rep = _get(server, loc + "/report.html")
    assert rep.status == 200 and "Черновик" in rep.read().decode()
    x = _get(server, loc + "/report.xlsx")
    assert x.status == 200 and x.read()[:2] == b"PK"
    home = _get(server, "/").read().decode()
    assert "Прошлые отчёты" in home


def test_role_not_confirmed_asks_lawyer(server, tmp_path):
    case = generate_case(str(tmp_path / "case"), "services", 3)
    files = {"theirs": ("t.docx", open(case["paths"]["tracked"], "rb").read())}
    # учебный договор: мы Исполнитель по ИНН, а плейбук — Заказчика
    r = _post(server, {"playbook": "services_customer_example.yaml", "company": "7701234567"}, files)
    body = r.read().decode()
    assert r.status == 200 and "Сторона договора не подтверждена" in body and "name=confirm_role" in body


def test_bad_file_and_foreign_host(server):
    r = _post(server, {"playbook": ""}, {"theirs": ("x.docx", b"not a docx")})
    assert "Не удалось разобрать" in r.read().decode()
    assert _get(server, "/", host="evil.example").status == 403
    assert _get(server, "/r/../../etc/passwd").status == 404


def test_confirmed_role_runs(server, tmp_path):
    case = generate_case(str(tmp_path / "case"), "services", 3)
    files = {"theirs": ("t.docx", open(case["paths"]["tracked"], "rb").read())}
    r = _post(server, {"playbook": "services_customer_example.yaml", "company": "7701234567", "confirm_role": "Заказчик"}, files)
    assert r.status == 303
