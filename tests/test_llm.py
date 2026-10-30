"""LLM-слой на подменённом HTTP: проверка, что плохой ответ модели не проходит."""
import json

import httpx

from copilot.drafts import Draft
from copilot.llm import LLMPolisher
from copilot.ticket import from_dict


def make(text, status=200):
    def handler(request):
        body = {"choices": [{"message": {"content": json.dumps({"text": text}, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 600, "completion_tokens": 120}}
        return httpx.Response(status, json=body)
    p = LLMPolisher("http://llm.test/v1", "k", "m", price_in_per_m=0.1, price_out_per_m=0.4)
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    return p


DRAFT = Draft(lang="ru", text="Здравствуйте! Нарушение п. 2.1 Общих правил. Наказание: мут чата от 15 до 30 минут.",
              cited=["2.1"], intent="approve")
T = from_dict({"kind": "complaint", "messages": [{"role": "player", "text": "оск в чате"}]})


def test_good_rewrite_accepted(rb):
    p = make("Здравствуйте! По скриншоту видно нарушение п. 2.1 Общих правил. Наказание: мут чата от 15 до 30 минут.")
    out = p.polish(DRAFT, T, None, "complaint.insult", rb)
    assert out.text.startswith("Здравствуйте! По скриншоту") and p.stats["ok"] == 1
    assert abs(p.stats["cost_usd"] - (600 * 0.1 + 120 * 0.4) / 1e6) < 1e-12


def test_invented_rule_rejected(rb):
    p = make("Здравствуйте! Нарушение п. 2.7 Общих правил, бан 30 дней.")
    out = p.polish(DRAFT, T, None, "complaint.insult", rb)
    assert out.text == DRAFT.text and p.stats["fallback"] == 1


def test_promise_rejected(rb):
    p = make("Здравствуйте! Наказание будет снято, извините.")
    assert p.polish(DRAFT, T, None, "complaint.insult", rb).text == DRAFT.text


def test_wrong_language_rejected(rb):
    p = make("Hello! Rule 2.1 was violated.")
    assert p.polish(DRAFT, T, None, "complaint.insult", rb).text == DRAFT.text


def test_http_error_falls_back(rb):
    p = make("x", status=500)
    out = p.polish(DRAFT, T, None, "complaint.insult", rb)
    assert out.text == DRAFT.text and "LLM недоступна" in out.reasons[-1]
