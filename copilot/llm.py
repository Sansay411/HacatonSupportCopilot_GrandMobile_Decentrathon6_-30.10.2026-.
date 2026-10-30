"""Необязательный LLM-слой: делает шаблонный черновик живее, не меняя фактов.

Включается переменными окружения (любой OpenAI-совместимый API: OpenRouter,
Gemini OpenAI-compat, OpenAI, локальный vLLM/Ollama):
    COPILOT_LLM_BASE_URL   например https://openrouter.ai/api/v1
    COPILOT_LLM_API_KEY
    COPILOT_LLM_MODEL      например google/gemini-2.5-flash-lite
    COPILOT_LLM_INTENTS    сценарии, где разрешена переформулировка (через запятую)
    COPILOT_LLM_TIMEOUT    секунды, по умолчанию 2.5 (p95 сервиса должен быть < 5 с)

Модель получает готовый черновик, список разрешённых пунктов с их текстом
(RAG) и сообщение игрока. Ответ проверяется кодом: язык, длина, только
разрешённые номера пунктов, нет обещаний. Любая ошибка или таймаут -> шаблон.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace

import httpx

from . import guard
from .lang import detect

DEFAULT_INTENTS = ("approve", "need_evidence", "appeal_reject", "question_unknown", "report_watch", "clarify")
LANG_NAMES = {"ru": "русском", "kk": "казахском", "uz": "узбекском (латиница)", "en": "английском", "es": "испанском",
              "pt": "португальском"}

SYSTEM = """Ты помогаешь администратору мобильной RP-игры Grand Mobile отвечать игрокам.
Тебе дают черновик ответа, сообщение игрока и тексты пунктов правил, на которые можно ссылаться.
Перепиши черновик так, чтобы он отвечал именно на это сообщение, коротко и вежливо, в стиле администратора.
Строгие правила:
- Пиши на языке, который указан. Не больше 450 символов.
- Ссылайся только на пункты из списка, в том же написании. Не придумывай пункты, сроки и факты.
- Не обещай разбан, снятие наказания, возврат имущества или денег, компенсацию.
- Наказание и сроки бери только из черновика, если они там есть.
- Не повторяй оскорбления игрока, не используй эмодзи.
Верни только JSON: {"text": "..."}"""


class LLMPolisher:
    def __init__(self, base_url: str, api_key: str, model: str, intents=DEFAULT_INTENTS, timeout: float = 2.5,
                 price_in_per_m: float = 0.0, price_out_per_m: float = 0.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.intents = set(intents)
        self.timeout = timeout
        self.price_in = price_in_per_m
        self.price_out = price_out_per_m
        self.client = httpx.Client(timeout=timeout)
        self.stats = {"calls": 0, "ok": 0, "fallback": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}

    def _messages(self, d, t, cat, rb):
        rules_ctx = []
        for c in d.cited:
            p = rb.get(c)
            if p:
                rules_ctx.append(f"[{c}] {p.text[:500]}")
        user = (f"Язык ответа: {LANG_NAMES.get(d.lang, d.lang)}\nКатегория: {cat}\n"
                f"Сообщение игрока: {t.player_text[:500]}\n"
                f"Разрешённые пункты:\n" + ("\n".join(rules_ctx) or "(нет, номера пунктов не упоминай)") +
                f"\nЧерновик:\n{d.text}")
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]

    def polish(self, d, t, sig, cat, rb):
        self.stats["calls"] += 1
        t0 = time.perf_counter()
        try:
            r = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": self._messages(d, t, cat, rb), "temperature": 0.2,
                      "max_tokens": 300, "response_format": {"type": "json_object"}},
            )
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            self.stats["tokens_in"] += usage.get("prompt_tokens", 0)
            self.stats["tokens_out"] += usage.get("completion_tokens", 0)
            self.stats["cost_usd"] += (usage.get("prompt_tokens", 0) * self.price_in +
                                       usage.get("completion_tokens", 0) * self.price_out) / 1e6
            content = data["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", content, re.S)
            text = json.loads(m.group(0))["text"].strip() if m else ""
        except Exception as e:  # сеть, таймаут, невалидный JSON
            self.stats["fallback"] += 1
            return replace(d, reasons=d.reasons + [f"LLM недоступна ({type(e).__name__}), отдан шаблон"])
        problems = self.validate(text, d, rb)
        if problems:
            self.stats["fallback"] += 1
            return replace(d, reasons=d.reasons + ["LLM-ответ отклонён проверкой: " + "; ".join(problems)])
        self.stats["ok"] += 1
        return replace(d, text=text, reasons=d.reasons + [f"текст переформулирован LLM за {time.perf_counter() - t0:.1f} с"])

    @staticmethod
    def validate(text: str, d, rb) -> list[str]:
        problems = []
        if not text or len(text) > 600:
            problems.append("пустой или слишком длинный текст")
        got = detect(text)
        if got != d.lang and not (d.lang == "ru" and got == "uk"):
            problems.append(f"язык {got} вместо {d.lang}")
        allowed_nums = {c.split(" ")[-1] for c in d.cited}
        for num in re.findall(r"(?<![\d.])\d{1,2}(?:\.\d{1,2}){1,2}(?![\d])", text):
            if num not in allowed_nums:
                problems.append(f"пункт {num} не из списка")
        _, reasons = guard.check(text, d.cited, rb)
        problems += reasons
        draft_nums = set(re.findall(r"\d+", d.text))
        for n in re.findall(r"\b\d+\b", text):
            if n not in draft_nums and n not in allowed_nums and not any(n in c for c in d.cited):
                problems.append(f"число {n} отсутствует в черновике")
                break
        # срок наказания: число вместе с единицей («30 минут» нельзя превратить в «30 дней»)
        extra_terms = _terms(text) - _terms(d.text)
        if extra_terms:
            problems.append("срок или единица измерения не из черновика: " + ", ".join(f"{n} {u}" for n, u in sorted(extra_terms)))
        extra_types = _sanction_types(text) - _sanction_types(d.text)
        if extra_types:
            problems.append("вид наказания не из черновика: " + ", ".join(sorted(extra_types)))
        return problems


_UNIT_CANON = (("мин", "m"), ("min", "m"), ("daqiqa", "m"), ("час", "h"), ("сағат", "h"), ("soat", "h"), ("hour", "h"),
               ("сут", "d"), ("дн", "d"), ("ден", "d"), ("күн", "d"), ("kun", "d"), ("day", "d"),
               ("нед", "w"), ("hafta", "w"), ("week", "w"), ("мес", "mo"), ("oy", "mo"), ("month", "mo"))
_TERM = re.compile(r"(\d+)\s*(?:(?:[–—-]|до|gacha|дейін|to)\s*(\d+)\s*)?([a-zа-яәғқңөұүһі]+)", re.I)
_SANCTION_TYPES = (("ban", "бан"), ("бан", "бан"), ("блокиров", "бан"), ("bloklash", "бан"), ("бұғатт", "бан"),
                   ("деморган", "деморган"), ("demorgan", "деморган"), ("варн", "варн"), ("warn", "варн"),
                   ("мут", "мут"), ("mute", "мут"), ("jail", "джайл"), ("джайл", "джайл"))


def _terms(text: str) -> set[tuple[str, str]]:
    out = set()
    for a, b, word in _TERM.findall(text.lower()):
        unit = next((c for stem, c in _UNIT_CANON if word.startswith(stem)), None)
        if unit:
            out.update((n, unit) for n in (a, b) if n)
    return out


def _sanction_types(text: str) -> set[str]:
    words = re.findall(r"[a-zа-яәғқңөұүһі]+", text.lower())
    return {canon for w in words for stem, canon in _SANCTION_TYPES if w.startswith(stem)}


def from_env():
    base = os.environ.get("COPILOT_LLM_BASE_URL")
    key = os.environ.get("COPILOT_LLM_API_KEY")
    model = os.environ.get("COPILOT_LLM_MODEL")
    if not (base and key and model):
        return None
    intents = [x.strip() for x in os.environ.get("COPILOT_LLM_INTENTS", ",".join(DEFAULT_INTENTS)).split(",") if x.strip()]
    return LLMPolisher(base, key, model, intents=intents, timeout=float(os.environ.get("COPILOT_LLM_TIMEOUT", "2.5")),
                       price_in_per_m=float(os.environ.get("COPILOT_LLM_PRICE_IN", "0")),
                       price_out_per_m=float(os.environ.get("COPILOT_LLM_PRICE_OUT", "0")))
