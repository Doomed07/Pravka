from pravki.classify import TECH_NOTE, classify, grammar_only
from pravki.model import Change
from pravki.parties import SideConfig
from pravki.pipeline import review_files
from pravki.playbook import analyze, load_playbook
from tests.helpers import make_docx, p, r

PB = load_playbook("playbooks/services_example.yaml")


def _ch(before, after, source="tracked"):
    return classify(Change(kind="replace", before=before, after=after, source=source,
                           context="Содержание услуги закреплён в Приложении № 1.",
                           context_after="Содержание услуги, закреплено в Приложении № 1."))


def test_word_ending_fix_is_grammar_and_accepted_with_short_note():
    ch = _ch("закреплён", ", закреплено", source="silent")
    analyze([ch], PB)
    assert ch.materiality == "техническая" and ch.level == "accept" and not ch.lawyer_decision_needed
    assert ch.explanation.startswith("Грамматическая") and TECH_NOTE in ch.explanation
    assert "плейбук" not in ch.explanation.lower()


def test_agreement_of_adjectives_and_participles_is_grammar():
    for before, after in [("закреплён", "закреплено"), ("оказанные", "оказанных"), ("подписал", "подписала"),
                          ("письменной", "письменную"), ("передаётся", "передаеться")]:
        assert grammar_only(Change(kind="replace", before=before, after=after)), (before, after)


def test_typo_fix_gets_the_same_short_note():
    ch = _ch("Прилжения", "Приложения")
    analyze([ch], PB)
    assert ch.level == "accept" and TECH_NOTE in ch.explanation and "плейбук" not in ch.explanation.lower()


def test_endings_that_change_meaning_are_not_grammar():
    for before, after in [("Заказчика", "Заказчику"), ("обязан", "обязана"), ("вправе", "не вправе"),
                          ("Стороны", "Сторон"), ("10 дней", "10 днями"), ("всех услуг", "услуг"),
                          ("услуги", "услуг"), ("оплаты", "оплате"), ("акта", "актов")]:
        assert not grammar_only(Change(kind="replace", before=before, after=after)), (before, after)


class _Model:
    def __init__(self, answer):
        self.answer = answer

    def complete(self, system, user):
        return self.answer


def _review(tmp_path, answer):
    from pravki.llm import Explainer

    clause = p(r("1. Предмет договора"))
    base = clause + p(r("1.2. Содержание услуги закреплён в Приложении № 1."))
    theirs = clause + p(r("1.2. Содержание услуги закреплено в Приложении № 1."))
    rv = review_files(str(make_docx(tmp_path / "t.docx", theirs)), str(make_docx(tmp_path / "b.docx", base)), PB,
                      explainer=Explainer(_Model(answer)), side=SideConfig(confirm_role="Исполнитель"))
    return next(c for c in rv.changes if c.after == "закреплено")


def test_model_confirms_grammar(tmp_path):
    ch = _review(tmp_path, "ДА")
    assert ch.level == "accept" and ch.explanation.startswith("Грамматическая")


def test_model_doubt_sends_to_lawyer(tmp_path):
    for answer in ("НЕТ", "Возможно, смысл меняется"):
        ch = _review(tmp_path, answer)
        assert ch.lawyer_decision_needed and ch.level == "review" and ch.materiality != "техническая", answer
        assert "смысл может меняться" in ch.action, answer


def test_role_word_and_noun_endings_are_not_typos():
    for before, after in [("Заказчика", "Заказчику"), ("услуги", "услуг"), ("оплаты", "оплате")]:
        assert _ch(before, after).materiality != "техническая", (before, after)
