"""Необязательный слой локальной модели: объясняет правку простым языком.

Модель НЕ принимает решения (их принимают правила плейбука) и в v0 только переписывает пояснение.
Защиты:
  * по умолчанию разрешены только локальные адреса: договоры содержат персональные данные и коммерческую тайну;
  * в ответе запрещены числа и ссылки на нормы, которых нет во входных данных — иначе ответ отбрасывается,
    остаётся шаблонное пояснение.

Статус: клиент проверен на заглушке; с реальной моделью (GigaChat 3.1 Lightning через llama.cpp/Ollama/vLLM) не запускался.
"""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .model import Change
from .textdiff import numbers

SYSTEM = (
    "Ты помощник юриста в российской компании. Объясни правку в договоре простым деловым языком, 2–3 предложения. "
    "Начни с того, что сделал контрагент, как сказано в поле «вид правки»: удалил, добавил или изменил. "
    "Пиши только об этой правке. Используй только факты из входных данных. Не придумывай числа, сроки и ссылки на "
    "законы. Не упоминай органы, организации и должности, которых нет во входных данных. "
    "Если данных не хватает, так и напиши. Не давай окончательных юридических заключений."
)


CLAUSE_SYSTEM = (
    "Ты помощник юриста в российской компании. Контрагент прислал первую версию договора. Объясни простым деловым языком, "
    "2–3 предложения, чем положение договора расходится с позицией нашей компании по плейбуку. Опирайся на поля "
    "«вывод по плейбуку», «основание» и «позиция компании». Используй только факты из входных данных. Не придумывай числа, "
    "сроки и ссылки на законы. Не упоминай органы, организации и должности, которых нет во входных данных. "
    "Не давай окончательных юридических заключений."
)


GRAMMAR_SYSTEM = (
    "Ты проверяешь правку в договоре. Ответь одним словом. ДА — если правка только исправляет грамматику, орфографию "
    "или пунктуацию и не меняет смысл условия: не меняет, кто, что, когда и сколько обязан сделать, и не позволяет "
    "трактовать условие иначе, в пользу одной из сторон. НЕТ — во всех остальных случаях и если сомневаешься."
)


SAME_SYSTEM = (
    "Ты сравниваешь две редакции договора. Абзац А удалён, на его место вставлен абзац Б. "
    "Определи, о чём каждый абзац (его предмет: оплата, неустойка, список участников, приёмка, подсудность и т. п.). "
    "Ответь одним словом: ДА — если предмет у А и Б один и тот же, даже если изменились сроки, способ, порядок "
    "или обязанная сторона; НЕТ — если абзацы о разном."
)


class LLMError(Exception):
    pass


def is_local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in ("localhost", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


class OpenAICompatClient:
    """Клиент для локального сервера с OpenAI-совместимым API (llama.cpp, Ollama, vLLM)."""

    def __init__(self, base_url: str, model: str, timeout: float = 120.0, allow_remote: bool = False):
        if not allow_remote and not is_local(base_url):
            raise LLMError(
                "адрес модели не локальный. Договоры содержат персональные данные и коммерческую тайну; "
                "чтобы всё же использовать внешний адрес, укажите --allow-remote осознанно"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": 400,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 (адрес проверен выше)
                data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as e:
            raise LLMError(f"модель не ответила: {e}")


    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Векторы текстов для поиска по смыслу (модель для векторов, например bge-m3, — не та, что пишет пояснения)."""
        body = json.dumps({"model": model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/embeddings", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 (адрес проверен выше)
                data = json.loads(r.read().decode("utf-8"))
            vectors = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
        except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as e:
            raise LLMError(f"модель для векторов не ответила: {e}")
        if len(vectors) != len(texts):
            raise LLMError("модель для векторов вернула не столько векторов, сколько текстов")
        return vectors


_ARTICLE = re.compile(r"(?:ст\.|статьи|статья|статье)\s*\d+(?:\.\d+)?", re.IGNORECASE)

# Направление правки: удаление описано как удаление, вставка — как вставка (а не «условия нет в текущей редакции»).
_SAYS_REMOVED = re.compile(r"удал|исключ|убра|убир|снят|снима|отказ|отмен|вычеркн", re.IGNORECASE)
_SAYS_ADDED = re.compile(r"добав|включ|введ|ввод|дополн|появ|предусм|устан|вставл", re.IGNORECASE)
# Удаление описано как появление нового текста («вместо этого добавлено…», «теперь указано…»): модель выдаёт соседний
# прежний текст за новый. Комментарий описан как сделанная правка («контрагент удалил пункт»), а он только просит.
_SAYS_NEW = re.compile(r"вместо (?:этого|него|неё|нее)|теперь (?:указано|предусмотрено|установлено)|добавлен|добавил|"
                       r"включен|включён|включил|введен|введён|ввёл|ввел", re.IGNORECASE)
_SAYS_DONE = re.compile(r"\b(?:удалил[аио]?|удален[аоы]?|удалён|исключил[аио]?|исключен[аоы]?|исключён|убрал[аио]?|убран[аоы]?|"
                        r"заменил[аио]?|заменен[аоы]?|заменён|добавил[аио]?|добавлен[аоы]?|изменил[аио]?|изменен[аоы]?|изменён)\b",
                        re.IGNORECASE)
_REMOVALS = ("delete", "para_delete")
_ADDITIONS = ("insert", "para_insert")

# Органы, организации и должности: в ответе только те, что есть во входных данных («налоговая служба» — выдумка).
_AUTHORITIES = [re.compile(p, re.IGNORECASE) for p in (
    r"налогов", r"\bфнс\b", r"инспекц", r"служб", r"прокурат", r"полиц", r"министерств", r"\bфас\b", r"антимонопольн",
    r"\bбанк", r"нотариус", r"бухгалтер", r"директор", r"\bсуд", r"арбитраж", r"роспотреб", r"казначейств", r"следств",
)]


def kind_words(ch: Change) -> str:
    """Вид правки человеческими словами — модели, чтобы не перепутать направление."""
    if ch.source == "clause":
        return "положение первой версии договора, предложенное контрагентом"
    if ch.detail.get("replaced_para"):
        what = "пункт заменён новой редакцией"
    else:
        what = {"delete": "удалено", "para_delete": "удалён абзац", "insert": "добавлено", "para_insert": "добавлен абзац",
                "replace": "заменено", "move": "перемещено", "comment": "комментарий контрагента"}.get(ch.kind, "изменено")
    return f"{what} без отметки в рецензировании" if ch.source in ("silent", "diff") else what


def _sentences(text: str, frag: str, limit: int = 600) -> str:
    """Предложения абзаца, в которых лежит правка: соседние правки того же абзаца в факты не попадают."""
    if not text:
        return ""
    if frag:
        hits = [s for s in re.split(r"(?<=[.;!?])\s+", text) if frag in s]
        if hits:
            return " ".join(hits)[:limit]
    return text[:limit]


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in re.findall(r"[^\W\d_]{5,}", text or "")}


def check_output(text: str, ch: Change, allowed_norms: list[str], neighbours=()) -> str | None:
    """Вернуть причину отказа или None, если ответ модели допустим.

    neighbours — другие правки того же абзаца: их слова и числа в пояснении к этой правке — признак путаницы.
    """
    if not text or len(text) > 900:
        return "пустой или слишком длинный ответ"
    if ch.kind in _REMOVALS and not ch.detail.get("replaced_para") and not _SAYS_REMOVED.search(text):
        return "удаление не описано как удаление"
    if ch.kind in _ADDITIONS and ch.source != "clause" and not ch.detail.get("replaced_para") and not _SAYS_ADDED.search(text):
        return "вставка не описана как добавление"
    if ch.kind in _REMOVALS and not ch.detail.get("replaced_para") and _SAYS_NEW.search(text):
        return "у удаления описан новый текст, которого контрагент не добавлял"
    if ch.kind == "comment" and _SAYS_DONE.search(text):
        return "комментарий описан как сделанная правка, а контрагент только пишет о ней"
    own = " ".join([ch.before, ch.after, ch.context, ch.context_after, ch.explanation, ch.suggested, ch.escalate_to,
                    ch.action, ch.rule_title, ch.topic, ch.clause])
    for rx in _AUTHORITIES:
        m = rx.search(text)
        if m and not rx.search(own):
            return f"в ответе орган или должность, которых нет во входных данных: «{m.group(0)}»"
    if neighbours:
        mine = _stems(" ".join([ch.before, ch.after, _sentences(ch.context, ch.before), _sentences(ch.context_after, ch.after)]))
        foreign = set().union(*(_stems(f"{o.before} {o.after}") for o in neighbours)) - mine
        leaked = sorted(_stems(text) & foreign)
        if leaked:
            return f"в ответе слова из соседней правки того же абзаца: {leaked[:3]}"
    facts = " ".join([ch.before, ch.after, ch.context, ch.context_after, ch.explanation, ch.suggested, ch.clause])
    allowed_nums = set(numbers(facts)) | set(numbers(" ".join(allowed_norms)))
    extra = [n for n in numbers(text) if n not in allowed_nums]
    if extra:
        return f"в ответе числа, которых нет во входных данных: {extra[:3]}"
    norms_text = " ".join(allowed_norms).lower()
    for m in _ARTICLE.findall(text):
        digits = re.sub(r"\D", "", m)
        if digits and digits not in re.sub(r"\D", " ", norms_text).split():
            return f"в ответе ссылка на норму, которой нет в плейбуке: {m}"
    return None


class Explainer:
    def __init__(self, client):
        self.client = client
        self.rejected = 0
        self.used = 0

    def same_condition(self, before: str, after: str) -> bool:
        """Модель распознаёт, что удалённый и вставленный абзацы — одно условие в новой редакции.
        Ответ влияет только на вид отчёта (одна правка вместо двух), не на решение."""
        try:
            text = self.client.complete(SAME_SYSTEM, json.dumps({"А": before[:1200], "Б": after[:1200]}, ensure_ascii=False))
        except LLMError:
            return False
        return re.sub(r"[^А-ЯЁA-Z]", "", text.strip().upper()[:5]).startswith("ДА")

    def confirms_technical(self, ch: Change) -> bool:
        """Модель подтверждает, что техническая правка не меняет смысл. Модель может только отменить решение правила:
        «НЕТ», неясный ответ или сбой проверки — правка уходит юристу как обычная."""
        facts = {"было": ch.before, "стало": ch.after, "абзац до правки": ch.context[:600],
                 "абзац после правки": ch.context_after[:600]}
        try:
            text = self.client.complete(GRAMMAR_SYSTEM, json.dumps(facts, ensure_ascii=False))
        except LLMError as e:
            ch.notes.append(f"Модель недоступна, грамматическую правку проверило только правило ({e})")
            return True  # без модели действует правило, как и без подключённой модели
        answer = re.sub(r"[^А-ЯЁA-Z]", "", text.strip().upper()[:5])
        return answer.startswith("ДА")

    def facts(self, ch: Change) -> dict:
        """Входные данные модели: вид правки и только предложения с правкой (без соседних правок абзаца)."""
        return {
            "пункт": ch.clause, "тема": ch.topic, "вид правки": kind_words(ch), "было": ch.before, "стало": ch.after,
            "предложение до правки": _sentences(ch.context, ch.before),
            "предложение после правки": _sentences(ch.context_after, ch.after),
            "вывод по плейбуку": ch.action, "основание": ch.explanation, "позиция компании": ch.suggested,
            "кого согласовать": ch.escalate_to,
        }

    def apply(self, ch: Change, neighbours=()) -> None:
        if ch.materiality == "техническая" or ch.kind == "comment" and not ch.rule_id:
            return
        facts = self.facts(ch)
        try:
            text = self.client.complete(CLAUSE_SYSTEM if ch.source == "clause" else SYSTEM,
                                        json.dumps(facts, ensure_ascii=False))
        except LLMError as e:
            ch.notes.append(f"Модель недоступна, пояснение шаблонное ({e})")
            return
        why = check_output(text, ch, ch.detail.get("norms", []), neighbours)
        if why:
            self.rejected += 1
            ch.notes.append(f"Ответ модели отброшен проверкой ({why}); оставлено шаблонное пояснение")
            return
        self.used += 1
        ch.detail["template_explanation"] = ch.explanation
        ch.explanation = text
