"""Конечная точка /parties: стороны договора и контрагент по преамбуле (для создания контрагента при загрузке первой версии)."""
from pravki import engine_api
from tests.helpers import make_docx, p, r
from tests.test_parties import ALFA, BETA, STD

TAIL = p(r("1. Предмет договора")) + p(r("1.1. Исполнитель оказывает Заказчику услуги."))


def _docx(tmp_path, preamble=STD, name="d.docx"):
    path = make_docx(tmp_path / name, p(r("ДОГОВОР № 1")) + p(r(preamble)) + TAIL)
    return open(path, "rb").read()


def test_counterparty_is_the_party_that_is_not_us(tmp_path):
    status, data = engine_api.detect_parties({"company": "7701234567"}, {"theirs": _docx(tmp_path)})
    assert status == 200
    assert [x["role"] for x in data["parties"]] == ["Исполнитель", "Заказчик"]
    assert data["counterparty"] == {"name": BETA, "inn": "7702345678", "role": "Заказчик"}


def test_counterparty_flips_with_our_company(tmp_path):
    # мы — вторая сторона: контрагент — первая
    status, data = engine_api.detect_parties({"company": "7702345678"}, {"theirs": _docx(tmp_path)})
    assert status == 200 and data["counterparty"]["name"] == ALFA and data["counterparty"]["inn"] == "7701234567"


def test_no_company_profile_means_no_counterparty_but_parties_are_listed(tmp_path):
    status, data = engine_api.detect_parties({}, {"theirs": _docx(tmp_path)})
    assert status == 200 and data["counterparty"] is None and len(data["parties"]) == 2


def test_our_company_not_in_preamble_means_no_counterparty(tmp_path):
    status, data = engine_api.detect_parties({"company": "7799999999"}, {"theirs": _docx(tmp_path)})
    assert status == 200 and data["counterparty"] is None


def test_contract_without_preamble_has_no_parties(tmp_path):
    status, data = engine_api.detect_parties({"company": "7701234567"}, {"theirs": _docx(tmp_path, "Просто текст без сторон.")})
    assert status == 200 and data["parties"] == [] and data["counterparty"] is None and data["ours"] is None
    assert data["title"] == "Договор № 1"


def test_missing_and_broken_file():
    assert engine_api.detect_parties({}, {})[0] == 400
    assert engine_api.detect_parties({}, {"theirs": b"not a document"})[0] == 400
