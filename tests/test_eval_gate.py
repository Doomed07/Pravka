"""Регрессионные пороги на синтетических договорах (цели из ТЗ). Не доказывают качество на реальных договорах."""
import os

from pravki.evaluate import run_synthetic
from pravki.playbook import load_playbook

PB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "playbooks")


def test_synthetic_gate():
    pbs = {"services": load_playbook(os.path.join(PB_DIR, "services_example.yaml")),
           "rent": load_playbook(os.path.join(PB_DIR, "rent_example.yaml"))}
    m = run_synthetic(30, 5000, pbs)["metrics"]
    assert m["полнота, все правки, %"] >= 99
    assert m["полнота, существенные правки, %"] >= 98
    assert m["полнота, тихие правки, %"] >= 99
    assert m["точность (доля найденного, что настоящее), %"] >= 98
    assert m["верная тема, %"] >= 92
    assert m["красные линии: ложное «принять», %"] <= 2
