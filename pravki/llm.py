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
    "Используй только факты из входных данных. Не придумывай числа, сроки и ссылки на законы. "
    "Если данных не хватает, так и напиши. Не давай окончательных юридических заключений."
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


_ARTICLE = re.compile(r"(?:ст\.|статьи|статья|статье)\s*\d+(?:\.\d+)?", re.IGNORECASE)


def check_output(text: str, ch: Change, allowed_norms: list[str]) -> str | None:
    """Вернуть причину отказа или None, если ответ модели допустим."""
    if not text or len(text) > 900:
        return "пустой или слишком длинный ответ"
    facts = " ".join([ch.before, ch.after, ch.context, ch.context_after, ch.explanation, ch.suggested])
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

    def apply(self, ch: Change) -> None:
        if ch.materiality == "техническая" or ch.kind == "comment" and not ch.rule_id:
            return
        facts = {
            "пункт": ch.clause, "тема": ch.topic, "было": ch.before, "стало": ch.after,
            "абзац после правки": ch.context_after[:600], "вывод по плейбуку": ch.action,
            "основание": ch.explanation, "позиция компании": ch.suggested,
        }
        try:
            text = self.client.complete(SYSTEM, json.dumps(facts, ensure_ascii=False))
        except LLMError as e:
            ch.notes.append(f"Модель недоступна, пояснение шаблонное ({e})")
            return
        why = check_output(text, ch, ch.detail.get("norms", []))
        if why:
            self.rejected += 1
            ch.notes.append(f"Ответ модели отброшен проверкой ({why}); оставлено шаблонное пояснение")
            return
        self.used += 1
        ch.detail["template_explanation"] = ch.explanation
        ch.explanation = text
