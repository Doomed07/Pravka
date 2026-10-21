"""Независимый «диалект» docx: файлы пересохраняются в LibreOffice, разбор должен дать тот же результат.

Это ближайшее, что у нас есть к файлам из чужих редакторов. Файлы из настоящего Word нужно добавлять в золотой набор.
"""
import os
import shutil
import subprocess

import pytest

from pravki.pipeline import review_files
from pravki.synth import side_config
from pravki.synth import generate_case

PB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playbooks")
pytestmark = pytest.mark.skipif(shutil.which("soffice") is None, reason="нет LibreOffice")


def _key(c):
    return (c.source, c.kind, c.before, c.after)


@pytest.mark.parametrize("template,seed,numbering", [("services", 11, "auto"), ("services", 12, "manual"),
                                                      ("rent", 13, "auto"), ("rent", 14, "manual")])
def test_roundtrip_through_libreoffice(tmp_path, template, seed, numbering):
    case = generate_case(str(tmp_path / "src"), template, seed, numbering)
    out = tmp_path / "lo"
    out.mkdir()
    subprocess.run(
        ["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{tmp_path}/profile",
         "--convert-to", "docx:MS Word 2007 XML", "--outdir", str(out),
         case["paths"]["base"], case["paths"]["tracked"]],
        check=True, capture_output=True, timeout=180,
    )
    pb = os.path.join(PB, f"{template}_example.yaml")
    a = review_files(case["paths"]["tracked"], case["paths"]["base"], pb, side=side_config(case))
    b = review_files(str(out / "theirs_tracked.docx"), str(out / "base.docx"), pb, side=side_config(case))
    assert sorted(map(_key, a.changes)) == sorted(map(_key, b.changes))
    assert [c.level for c in sorted(a.changes, key=_key)] == [c.level for c in sorted(b.changes, key=_key)]
