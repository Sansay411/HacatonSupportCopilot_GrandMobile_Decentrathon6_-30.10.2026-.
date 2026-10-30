"""Тесты на реальных правилах и моделях (пропускаются, если data/ нет)."""
import re

from copilot.ticket import from_dict

CONTRACT_KEYS = {"lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply", "needs_human",
                 "confidence", "reasons"}
PROMISE = re.compile(r"будет снят|разбан(им|ен)|верн[её]м|компенс", re.I)


def run(cp, kind, text, **extra):
    d = {"kind": kind, "messages": [{"role": "player", "text": text, "attachments": extra.pop("attachments", 1)}]}
    d.update(extra)
    return cp.triage(d, use_dedup=False)


def test_contract_example(copilot_full):
    r = run(copilot_full, "complaint", "Arman_Petrov оскорблял меня и мою семью в чате, скрины есть, 2.1 ОП", attachments=2)
    assert CONTRACT_KEYS <= set(r)
    assert r["category"] == "complaint.insult"
    assert r["extracted"]["nickname"] == "Arman_Petrov"
    assert r["extracted"]["rule_refs"] == ["2.1"]
    assert r["extracted"]["has_evidence"] is True
    assert r["needs_human"] is True
    assert all(copilot_full.rules.exists(c) for c in r["draft_reply"]["cited"])


def test_always_human(copilot_full):
    for kind, text in [("report", "оплатил гк, не пришло"), ("report", "взломали аккаунт, пропала машина"),
                       ("complaint", "не согласен с наказанием, снимите бан")]:
        r = run(copilot_full, kind, text)
        assert r["needs_human"] is True, text
    assert run(copilot_full, "report", "оплатил гк, не пришло")["priority"] == "p0"


def test_languages(copilot_full):
    assert run(copilot_full, "complaint", "onadan so'kdi, ban bering")["draft_reply"]["lang"] == "uz"
    r = run(copilot_full, "complaint", "маѕан анамды балаѓаттады", region="kz", server_lang="kk")
    assert r["draft_reply"]["lang"] == "kk"
    assert run(copilot_full, "report", "help me stuck in texture")["draft_reply"]["lang"] == "en"


def test_no_promises_no_fake_rules(copilot_full):
    texts = ["верните машину, админ забрал", "разбаньте пожалуйста", "дайте денег", "помогите", "дм у банка",
             "софт летает", "скам на 100кк", "продаёт акк за реал в тг", "как устроиться в полицию?"]
    for kind in ("complaint", "report"):
        for t in texts:
            r = run(copilot_full, kind, t)
            assert not PROMISE.search(r["draft_reply"]["text"]), t
            assert all(copilot_full.rules.exists(c) for c in r["draft_reply"]["cited"])


def test_admin_messages_ignored():
    t = from_dict({"kind": "complaint", "messages": [{"role": "player", "text": "оск"},
                                                      {"role": "admin", "text": "одобрена, мут 30 минут"}]})
    assert "одобрена" not in t.player_text
