"""Повторная отправка того же обращения не дубль; краткие шаблоны без утверждений, которых сервис не знает."""
from __future__ import annotations

import shutil

import pytest

from copilot.pipeline import Copilot
from tests.support import FIXTURE_RULES


@pytest.fixture()
def cp(tmp_path):
    shutil.copy(FIXTURE_RULES, tmp_path / "rules.json")
    return Copilot(tmp_path, tmp_path / "no_models")


def _payload(text="Bad_Guy оскорбил меня в чате, смотрите скрин", *, tid="t1", at="2026-10-30T10:00:00Z", att=1, kind="complaint"):
    return {"kind": kind, "ticket_id": tid, "created_at": at, "reporter_hash": "r1", "reported_nick": "Bad_Guy",
            "messages": [{"role": "player", "text": text, "attachments": att}]}


def test_same_ticket_sent_twice_is_not_a_duplicate_of_itself(cp):
    first = cp.triage(_payload())
    second = cp.triage(_payload())
    assert first["is_spam_or_duplicate"] is False
    assert second["is_spam_or_duplicate"] is False
    assert second["draft_reply"]["text"] == first["draft_reply"]["text"]
    assert second["_meta"]["intent"] == first["_meta"]["intent"]


def test_replay_works_without_created_at(cp):
    p = _payload()
    del p["created_at"]
    assert cp.triage(dict(p))["is_spam_or_duplicate"] is False
    assert cp.triage(dict(p))["is_spam_or_duplicate"] is False


def test_different_ticket_id_with_same_text_is_still_a_duplicate(cp):
    cp.triage(_payload(tid="t1"))
    again = cp.triage(_payload(tid="t2", at="2026-10-30T10:05:00Z"))
    assert again["is_spam_or_duplicate"] is True
    assert again["_meta"]["intent"] == "duplicate"


def test_replay_of_a_real_duplicate_stays_a_duplicate(cp):
    cp.triage(_payload(tid="t1"))
    dup1 = cp.triage(_payload(tid="t2", at="2026-10-30T10:05:00Z"))
    dup2 = cp.triage(_payload(tid="t2", at="2026-10-30T10:05:00Z"))
    assert dup1["is_spam_or_duplicate"] is True
    assert dup2["is_spam_or_duplicate"] is True
    assert dup2["_meta"]["dedup"]["original_ref"] == dup1["_meta"]["dedup"]["original_ref"]


def test_same_ticket_id_with_different_text_is_not_treated_as_replay():
    from copilot.dedup import DedupStore
    s = DedupStore()
    kw = dict(reporter="r", reported=None, kind="complaint", category="complaint.other", ticket_id="t1")
    assert s.match_and_add(text="ник Aaa убил меня у банка", created_at="2026-10-30T10:00:00Z", **kw) is None
    second = s.match_and_add(text="ник Aaa убил меня у банка", created_at="2026-10-30T10:01:00Z", **kw)
    assert second is None                                   # тот же id и текст: повтор, прежний результат
    third = s.match_and_add(text="Совсем другой текст про аккаунт и пароль", created_at="2026-10-30T10:02:00Z", **kw)
    assert third is None
    assert len(s._by_reporter["r"]) == 2                    # разный текст с тем же id записан как новое обращение


@pytest.mark.parametrize("server_lang,hello_text", [("ru", None), ("kk", None), ("uz", None)])
def test_approve_draft_is_short_and_does_not_claim_closure(cp, server_lang, hello_text):
    r = cp.triage(_payload(att=2) | {"server_lang": server_lang,
                                     "messages": [{"role": "player", "attachments": 2,
                                                   "text": {"ru": "Bad_Guy оскорблял меня в чате, скрины есть, 2.1 ОП",
                                                            "kk": "Bad_Guy мені чатта балағаттады, скриншот бар, 2.1",
                                                            "uz": "Bad_Guy meni chatda haqorat qildi, skrinshot bor, 2.1"}[server_lang]}]})
    text = r["draft_reply"]["text"]
    assert len(text) <= 280, text      # было 290–390 до сокращения шаблонов
    for banned in ("активную позицию", "Жалоба закрыта", "Белсенділігіңізге", "Shikoyat yopildi", "Шағым жабылды", "Faol pozitsiyangiz"):
        assert banned not in text


@pytest.mark.parametrize("lang", ["ru", "kk", "uz", "en", "es", "pt"])
def test_event_teleport_does_not_state_unknown_facts(lang):
    from copilot import i18n
    t = i18n.T[lang]["event_tp"].lower()
    for claim in ("сейчас закрыт", "не проводится", "қазір жабық", "өтпей жатыр", "hozir yopiq", "o‘tkazilmayapti",
                  "closed right now", "no event is running", "cerrado ahora", "fechado agora"):
        assert claim not in t


def test_report_drafts_stay_short(cp):
    r = cp.triage({"kind": "report", "messages": [{"role": "player", "text": "Ivan_Test [123] читерит, проследите"}]})
    assert len(r["draft_reply"]["text"]) <= 190, r["draft_reply"]["text"]
