"""Экспериментальный генератор черновиков на локальной Qwen3.5-4B. Не заменяет шаблонный генератор Sentra.

Контракт совпадает с хуком copilot.llm: pipeline вызывает polish(d, t, sig, cat, rb) и получает Draft обратно.
Что получает модель (и только это):
  * исходный текст обращения (до 500 символов);
  * достоверно извлечённые кодом факты: ник нарушителя, ID, наличие вложений и ссылок;
  * категорию и сценарий, которые выбрал код (needs_human модель не видит и не меняет);
  * цитаты правил: только пункты из d.cited, с текстом из rules.json;
  * наказание только в том виде, как его выбрал код по тексту пункта (sanction_from_rules);
  * язык ответа и ограничения на обещания.
После генерации текст проходит те же детерминированные проверки, что и любой ответ pipeline (copilot.llm.validate,
copilot.verify, copilot.guard). Любое нарушение или ошибка возвращают исходный черновик без изменений.
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from copilot import drafts, guard, i18n, sanctions, verify  # noqa: E402
from copilot.lang import detect  # noqa: E402
from copilot.llm import LLMPolisher  # noqa: E402

MODEL_ID = "Qwen/Qwen3.5-4B"
GEN_INTENTS = ("approve", "need_evidence", "appeal_reject", "question_unknown", "report_watch", "clarify")
LANG_NAMES = {"ru": "русский", "kk": "казахский", "uz": "узбекский (латиница)", "en": "английский"}

SYSTEM = """Ты помощник поддержки мобильной RP-игры Grand Mobile. Ты пишешь ЧЕРНОВИК ответа игроку, его проверит администратор.

Жёсткие правила:
1. Пиши только на языке из поля target_language. Не переходи на другой язык и не смешивай языки.
2. Используй только факты из блока FACTS. Не добавляй номера пунктов, сроки, суммы, ники, ссылки и названия, которых там нет.
3. На правила ссылайся только через cite_label из rule_quotes, дословно. Если rule_quotes пуст, номера пунктов не называй.
4. Нельзя обещать или сообщать о разбане, снятии наказания, возврате имущества или денег, компенсации. Нельзя писать, что игрока «накажут» или «забанят». Наказание можно назвать только как в sanction_from_rules.
5. Решение принимает администратор: ты не подтверждаешь и не отменяешь наказания от себя.
6. Сначала в одном коротком предложении покажи, что ты понял суть сообщения игрока, затем выполни сценарий из поля task.
7. Вежливо, как администратор поддержки. Без эмодзи, без markdown, без повторения оскорблений игрока. Не больше 450 символов.
Верни только текст ответа игроку, без пояснений и без кавычек."""

# что должен сделать ответ в каждом сценарии: смысл совпадает со смыслом шаблонов Sentra, формулировки модель выбирает сама
TASKS = {
    "approve": "Сообщи, что жалоба рассмотрена и по приложенным материалам нарушение соответствует указанному пункту; "
               "наказание и срок назначит администратор по правилам проекта. Закрой жалобу и поблагодари игрока.",
    "need_evidence": "Попроси видеозапись с моментом нарушения, на которой виден ник игрока, укажи ссылки на пункты из rule_quotes; "
                     "видео нужно загрузить на YouTube, imgur, Rutube, Яндекс Диск или Google Диск и подать новую жалобу.",
    "appeal_reject": "Сообщи, что обжалование рассмотрено, наказание выдано верно и оснований для снятия нет. "
                     "Если есть видео, опровергающее нарушение, нужно подать новую жалобу с видео. Ничего не обещай. Жалоба закрыта.",
    "question_unknown": "Сообщи, что ответ на вопрос можно узнать у игроков или на Discord-сервере игры (discord_url). "
                        "Не придумывай ответ по существу вопроса.",
    "report_watch": "Сообщи, что обращение передано администратору и он проследит за игроком (укажи player_id, если он есть). "
                    "Если есть видео нарушения, предложи оформить жалобу в лаунчере: по жалобе с доказательствами нарушителя можно наказать.",
    "clarify": "Попроси уточнить вопрос или жалобу: что произошло?",
}


def build_facts(d, t, sig, cat, rb) -> dict:
    quotes = []
    for c in d.cited:
        p = rb.get(c)
        if p:
            quotes.append({"cite_label": drafts.cite_text(rb, c, d.lang), "text": p.text[:350]})
    sanction = None
    if d.intent == "approve" and d.cited:
        p = rb.get(d.cited[0])
        if p:
            sanction = sanctions.render(sanctions.choose(p, t.player_text), d.lang) or None
    facts = {
        "target_language": d.lang,
        "scenario": d.intent,
        "category": cat,
        "player_message": t.player_text[:500],
        "reported_nickname": t.reported_nick or sig.nickname,
        "player_id": sig.player_id,
        "evidence": {"attachments": t.images, "has_link": bool(sig.has_url)},
        "rule_quotes": quotes,
        "sanction_from_rules": sanction,
        "discord_url": i18n.DISCORD_URL,
        "support_url": i18n.SUPPORT_URL,
    }
    return facts


def build_messages(facts: dict) -> list[dict]:
    block = json.dumps({k: v for k, v in facts.items() if k not in ("scenario",)}, ensure_ascii=False, indent=1)
    user = (f"target_language: {LANG_NAMES.get(facts['target_language'], facts['target_language'])}\n"
            f"task: {TASKS[facts['scenario']]}\n\nFACTS:\n{block}\n\nНапиши ответ игроку.")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


_URL = re.compile(r"https?://[^\s)]+|discord\.gg/\S+|t\.me/\S+", re.I)
_BAD_FORMAT = re.compile(r"</?think>|^#{1,6}\s|\*\*|[\U0001F300-\U0001FAFF☀-➿]", re.M)


def extra_checks(text: str, d, t, sig) -> list[str]:
    """Проверки сверх copilot.llm.validate: ссылки, ники, формат, обещания по расширенному списку."""
    issues = []
    allowed_urls = {i18n.DISCORD_URL, i18n.SUPPORT_URL}
    for u in _URL.findall(text):
        if not any(u.rstrip(".,") in a or a in u for a in allowed_urls if a):
            issues.append(f"ссылка вне списка: {u[:40]}")
    nick = t.reported_nick or sig.nickname
    for m in re.finditer(r"(?:ник\w*|nick\w*|нарушител\w*)\s*[:\-]?\s*([A-Za-z][\w.\-]{2,31})", text, re.I):
        if nick and m.group(1).lower() != nick.lower() and m.group(1).lower() not in {"игрока", "игрок"}:
            issues.append(f"ник не из фактов: {m.group(1)}")
    if _BAD_FORMAT.search(text):
        issues.append("служебная разметка, markdown или эмодзи")
    if re.search(r"\{[a-z_]+\}", text):
        issues.append("незаполненное поле")
    hit = verify.find_promise(text)
    if hit:
        issues.append(f"обещание: {hit}")
    return issues


class QwenGenerator:
    """Drop-in для Copilot(llm=...): тот же интерфейс, что у copilot.llm.LLMPolisher."""

    intents = set(GEN_INTENTS)

    def __init__(self, model_id: str = MODEL_ID, quant: str = "nf4", max_new_tokens: int = 170, warmup: bool = True,
                 repetition_penalty: float = 1.05):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        self.model_id, self.quant, self.max_new_tokens, self.rep = model_id, quant, max_new_tokens, repetition_penalty
        t0 = time.time()
        self.tok = AutoTokenizer.from_pretrained(model_id)
        kwargs = {"device_map": {"": 0}, "dtype": torch.bfloat16}
        if quant == "nf4":
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True)
        elif quant == "int8":
            kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs).eval()
        self.load_seconds = round(time.time() - t0, 1)
        self.stats = {"calls": 0, "ok": 0, "fallback": 0, "error": 0, "tokens_in": 0, "tokens_out": 0, "gen_seconds": 0.0}
        self.log: list[dict] = []
        if warmup:
            self.generate_text([{"role": "user", "content": "Привет"}], max_new_tokens=8)

    def generate_text(self, messages, max_new_tokens=None):
        torch = self.torch
        prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        enc = self.tok(prompt, return_tensors="pt").to(self.model.device)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.inference_mode():
            out = self.model.generate(**enc, max_new_tokens=max_new_tokens or self.max_new_tokens, do_sample=False,
                                      repetition_penalty=self.rep, pad_token_id=self.tok.eos_token_id)
        torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        new = out[0, enc["input_ids"].shape[1]:]
        text = self.tok.decode(new, skip_special_tokens=True).strip()
        return text, {"seconds": dt, "tokens_in": int(enc["input_ids"].shape[1]), "tokens_out": int(new.shape[0])}

    def polish(self, d, t, sig, cat, rb):
        self.stats["calls"] += 1
        facts = build_facts(d, t, sig, cat, rb)
        rec = {"ticket_id": t.ticket_id, "intent": d.intent, "lang": d.lang}
        try:
            text, info = self.generate_text(build_messages(facts))
        except Exception as e:                       # нехватка памяти, сбой CUDA: безопасный шаблон
            self.stats["error"] += 1
            rec.update(status="error", detail=f"{type(e).__name__}: {str(e)[:120]}")
            self.log.append(rec)
            return replace(d, reasons=d.reasons + [f"Qwen недоступна ({type(e).__name__}), отдан шаблон"])
        self.stats["tokens_in"] += info["tokens_in"]
        self.stats["tokens_out"] += info["tokens_out"]
        self.stats["gen_seconds"] += info["seconds"]
        text = text.strip().strip('"«»').strip()
        problems = LLMPolisher.validate(text, d, rb) + extra_checks(text, d, t, sig)
        if info["tokens_out"] >= self.max_new_tokens:
            problems.append("ответ обрезан по лимиту токенов")
        problems += verify.text_ref_issues(text, d.cited, rb) + [v.message for v in verify.verify_text(text, rb).violations]
        rec.update(info, raw_text=text, problems=problems)
        if problems:
            self.stats["fallback"] += 1
            rec["status"] = "rejected"
            self.log.append(rec)
            return replace(d, reasons=d.reasons + ["ответ Qwen отклонён проверкой: " + "; ".join(sorted(set(problems)))[:300]])
        self.stats["ok"] += 1
        rec["status"] = "ok"
        self.log.append(rec)
        hello = i18n.T[d.lang]["hello"]
        first_word = lambda s: re.split(r"[\s,!.]", s.strip(), maxsplit=1)[0].lower()   # noqa: E731
        final = text if first_word(text) == first_word(hello) else f"{hello} {text}"
        return replace(d, text=final, reasons=d.reasons + [f"текст сгенерирован Qwen3.5-4B за {info['seconds']:.1f} с"])
