"""Один ticket_id: повтор того же обращения даёт тот же результат, другое содержимое обрабатывается явно.

Правила:
* тот же ticket_id, тип, заявитель и текст это тот же логический тикет: результат прежний, самодублем он не становится;
* новое сообщение того же игрока с другим ticket_id остаётся настоящим дублем;
* одинаковый текст двух разных игроков не склеивается;
* тот же ticket_id с другим содержимым не повтор и не дубль: причина в reasons, needs_human=true, на уровне хранилища 409;
* обязательная эскалация (платёж, аккаунт, обжалование, угроза) повтором не снимается.
"""
from __future__ import annotations

import json
import shutil

import pytest

from copilot.dedup import REASON_ID_CONFLICT, DedupStore
from copilot.pipeline import Copilot
from tests.support import FIXTURE_RULES

TEXT = "Bad_Guy оскорбил меня в чате, смотрите скрин"


@pytest.fixture()
def cp(tmp_path):
    shutil.copy(FIXTURE_RULES, tmp_path / "rules.json")
    return Copilot(tmp_path, tmp_path / "no_models")


def payload(text=TEXT, *, tid="t1", at="2026-10-30T10:00:00Z", reporter="r1", kind="complaint", att=1):
    p = {"kind": kind, "ticket_id": tid, "created_at": at, "reporter_hash": reporter, "reported_nick": "Bad_Guy",
         "messages": [{"role": "player", "text": text, "attachments": att}]}
    if reporter is None:
        del p["reporter_hash"]
    return p


def contract(r: dict) -> dict:
    """Всё, что видит клиент контракта, без времени обработки."""
    r = json.loads(json.dumps(r))
    r["_meta"].pop("latency_ms", None)
    return r


# ---------------------------------------------------------------- повтор того же тикета
def test_replay_gives_an_identical_result_not_only_the_same_flags(cp):
    first = cp.triage(payload())
    again = cp.triage(payload())
    assert contract(again) == contract(first)


def test_replay_with_a_different_arrival_time_is_still_the_same_ticket(cp):
    first = cp.triage(payload(at="2026-10-30T10:00:00Z"))
    late = cp.triage(payload(at="2026-10-30T18:30:00Z"))        # ретрай клиента спустя часы, то же содержимое
    assert late["is_spam_or_duplicate"] is False
    assert late["draft_reply"] == first["draft_reply"] and late["needs_human"] == first["needs_human"]


def test_replay_after_other_tickets_of_the_same_player_keeps_the_first_result(cp):
    first = cp.triage(payload(tid="t1"))
    cp.triage(payload(tid="t2", at="2026-10-30T10:05:00Z"))                # настоящий дубль
    cp.triage(payload("Совсем другая жалоба про взлом аккаунта", tid="t3", at="2026-10-30T10:06:00Z"))
    assert contract(cp.triage(payload(tid="t1"))) == contract(first)


def test_new_message_of_the_same_player_with_another_ticket_id_is_a_real_duplicate(cp):
    cp.triage(payload(tid="t1"))
    again = cp.triage(payload(tid="t2", at="2026-10-30T10:07:00Z"))
    assert again["is_spam_or_duplicate"] is True and again["_meta"]["intent"] == "duplicate"


def test_replay_of_a_duplicate_does_not_create_a_second_incident(cp):
    cp.triage(payload(tid="t1"))
    d1 = cp.triage(payload(tid="t2", at="2026-10-30T10:07:00Z"))
    d2 = cp.triage(payload(tid="t2", at="2026-10-30T10:07:00Z"))
    assert contract(d2) == contract(d1)
    assert len(cp.dedup._by_reporter["r1"]) == 2                           # в памяти два обращения, а не три


def test_same_text_from_different_players_is_never_merged(cp):
    a = cp.triage(payload(tid="a", reporter="player_a"))
    b = cp.triage(payload(tid="b", reporter="player_b", at="2026-10-30T10:01:00Z"))
    assert a["is_spam_or_duplicate"] is False and b["is_spam_or_duplicate"] is False


def test_same_text_without_a_reporter_is_never_merged(cp):
    a = cp.triage(payload(tid="a", reporter=None))
    b = cp.triage(payload(tid="b", reporter=None, at="2026-10-30T10:01:00Z"))
    assert a["is_spam_or_duplicate"] is False and b["is_spam_or_duplicate"] is False


# ---------------------------------------------------------------- один id, другое содержимое
@pytest.mark.parametrize("changed", [
    dict(text="Совсем другой текст про угрозы в реальной жизни"),
    dict(reporter="another_player"),
    dict(kind="report"),
])
def test_same_ticket_id_with_other_content_is_explicit_and_goes_to_a_human(cp, changed):
    first = cp.triage(payload())
    second = cp.triage(payload(**{"at": "2026-10-30T10:30:00Z", **changed}))
    assert REASON_ID_CONFLICT in second["reasons"]
    assert second["needs_human"] is True
    assert REASON_ID_CONFLICT not in first["reasons"]


def test_edited_ticket_is_not_a_duplicate_of_its_own_earlier_version(cp):
    cp.triage(payload())
    edited = cp.triage(payload(TEXT + " и ещё матерился", at="2026-10-30T10:20:00Z"))
    assert REASON_ID_CONFLICT in edited["reasons"]
    assert edited["is_spam_or_duplicate"] is False                          # тот же id: это не повтор самого себя


def test_conflict_does_not_break_a_later_replay_of_the_original(cp):
    first = cp.triage(payload())
    cp.triage(payload("Совсем другой текст про аккаунт и пароль", at="2026-10-30T10:30:00Z"))
    back = cp.triage(payload(at="2026-10-30T10:40:00Z"))
    assert REASON_ID_CONFLICT not in back["reasons"]
    assert back["draft_reply"] == first["draft_reply"]


def test_huge_ticket_id_does_not_grow_memory(cp):
    huge = "x" * 100_000
    cp.triage(payload(tid=huge))
    assert all(len(k) <= 128 for k in cp.dedup._tids)
    assert cp.triage(payload(tid=huge))["is_spam_or_duplicate"] is False       # и это по-прежнему повтор того же обращения


def test_conflict_is_reported_through_the_store_notes():
    s = DedupStore()
    kw = dict(reporter="r", reported=None, kind="complaint", category="complaint.other", created_at="2026-10-30T10:00:00Z")
    notes: list[str] = []
    assert s.match_and_add(text="ник Aaa убил меня у банка", ticket_id="x", notes=notes, **kw) is None
    assert s.match_and_add(text="ник Aaa убил меня у банка", ticket_id="x", notes=notes, **kw) is None
    assert notes == []
    s.match_and_add(text="другой текст про пароль", ticket_id="x", notes=notes, **kw)
    assert notes == [REASON_ID_CONFLICT]


def test_discarded_ticket_does_not_leave_a_phantom_conflict():
    s = DedupStore()
    kw = dict(reporter="r", reported=None, kind="complaint", category="complaint.other", created_at="2026-10-30T10:00:00Z")
    s.match_and_add(text="ник Aaa убил меня у банка", ticket_id="x", ref="Q-1", **kw)
    s.discard("Q-1")                                        # обращение не удалось сохранить
    notes: list[str] = []
    s.match_and_add(text="другой текст про пароль", ticket_id="x", notes=notes, **kw)
    assert notes == []


# ---------------------------------------------------------------- обязательная эскалация не зависит от повтора
@pytest.mark.parametrize("kind,text", [
    ("report", "Оплатил донат, деньги списались, но Grand Coins не пришли."),
    ("report", "Меня взломали, не могу войти в аккаунт и пропало имущество."),
    ("complaint", "Я не согласен с баном, прошу пересмотреть наказание."),
    ("report", "Игрок угрожает найти меня в реальной жизни и расправиться."),
])
def test_replay_never_lowers_mandatory_escalation(cp, kind, text):
    p = {"kind": kind, "ticket_id": "p0-1", "reporter_hash": "p0", "created_at": "2026-10-30T10:00:00Z",
         "messages": [{"role": "player", "text": text}]}
    first, replay = cp.triage(dict(p)), cp.triage(dict(p))
    assert first["needs_human"] is True and replay["needs_human"] is True
    assert contract(replay) == contract(first)


# ---------------------------------------------------------------- слой хранения: enqueue и импорт
def enq(c, **kw):
    return c.post("/triage?enqueue=true", json=payload(**kw))


def test_enqueue_replay_returns_the_same_stored_ticket(boot):
    c, _ = boot()
    a, b = enq(c), enq(c, at="2026-10-30T12:00:00Z")
    assert a.status_code == b.status_code == 200
    assert a.json()["queue_id"] == b.json()["queue_id"]
    assert b.json()["draft_reply"] == a.json()["draft_reply"]
    assert c.get("/tickets").json()["total"] == 1


def test_enqueue_with_the_same_id_and_other_content_is_an_explicit_conflict(boot):
    c, _ = boot()
    first = enq(c)
    clash = enq(c, text="Совсем другой текст про взлом аккаунта")
    assert clash.status_code == 409
    detail = clash.json()["detail"]
    assert detail["code"] == "ticket_id_conflict" and detail["existing_id"] == first.json()["queue_id"]
    assert c.get("/tickets").json()["total"] == 1                          # молча ничего не перезаписано и не добавлено


def test_enqueue_other_player_with_the_same_text_is_a_new_ticket(boot):
    c, _ = boot()
    enq(c, tid="a", reporter="player_a")
    other = enq(c, tid="b", reporter="player_b", at="2026-10-30T10:01:00Z")
    assert other.status_code == 200 and c.get("/tickets").json()["total"] == 2
    assert other.json()["is_spam_or_duplicate"] is False


def test_import_reports_a_conflicting_row_and_stays_repeatable(boot):
    c, _ = boot()
    base = {"ticket_id": "T-1", "kind": "complaint", "created_at": "2026-10-30T10:00:00Z", "reporter_hash": "r1",
            "messages": [{"role": "player", "text": TEXT, "attachments": 1}]}
    body = json.dumps(base).encode("utf-8")
    assert c.post("/tickets/import", content=body).json()["imported"] == 1
    assert c.post("/tickets/import", content=body).json()["skipped_existing"] == 1
    clash = dict(base, messages=[{"role": "player", "text": "Совсем другой текст про взлом аккаунта", "attachments": 0}])
    r = c.post("/tickets/import", content=json.dumps(clash).encode("utf-8")).json()
    assert r["imported"] == 0 and r["skipped_existing"] == 0 and r["errors_total"] == 1
    assert "ticket_id" in r["errors"][0]["error"]
    assert c.get("/tickets").json()["total"] == 1
