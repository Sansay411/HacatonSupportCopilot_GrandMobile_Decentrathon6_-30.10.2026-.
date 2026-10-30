"""Регрессии по независимой проверке backend (Codex, 30.10.2026): каждая находка закреплена тестом.

Работают на синтетических правилах и без ML-моделей.
"""
import shutil
import sqlite3
import threading

import pytest

from support import FIXTURE_RULES, ROOT
from copilot.dedup import DedupStore
from copilot.pipeline import Copilot
from copilot.redact import redact
from copilot.service import ApiError, TicketService
from copilot.store import Store
from copilot.verify import verify_text


def new_service(tmp_path, name="proc", db="shared.db"):
    """Отдельный «процесс»: свой Copilot, своя память дедупликации, своё подключение к той же базе."""
    d = tmp_path / f"data-{name}"
    d.mkdir(exist_ok=True)
    shutil.copy(FIXTURE_RULES, d / "rules.json")
    cp = Copilot(data_dir=d, models_dir=tmp_path / "нет")
    store = Store(tmp_path / db)
    svc = TicketService(cp, store, templates_json=ROOT / "reports/template_suggestions_summary.json")
    return svc, store


def form(text, reporter, **kw):
    return dict({"kind": "complaint", "text": text, "reporter": reporter, "attachments": 1}, **kw)


# ---------------------------------------------------------------- 3, 4. секреты не доходят до базы
@pytest.mark.parametrize("text,secret", [("CVV: 123", "123"), ("cvv 123", "123"), ("код cvc2=456", "456"), ("CVC 7890", "7890")])
def test_short_cvv_is_masked(text, secret):
    r = redact("карта списана, " + text)
    assert secret not in r.text and r.counts


def test_secrets_never_reach_sqlite_in_any_field(tmp_path):
    svc, store = new_service(tmp_path)
    secret_url = "https://example.com/video?token=sk-abcdefghijklmnop1234567890"
    t, _ = svc.create_from_form(form("взломали аккаунт, CVV: 123, пароль: Qwerty123", "a1", evidence_urls=[secret_url],
                                     server="pwd: Secret999"))
    raw = "\n".join(str(r) for r in store._conn.execute(
        "SELECT player_text, request_json, server, response_json FROM tickets t JOIN triage_results r ON r.ticket_id=t.id"))
    for needle in ("CVV: 123", "Qwerty123", "sk-abcdefghijklmnop", "Secret999"):
        assert needle not in raw, needle
    assert t["request"]["evidence_urls"][0].endswith("token=[скрыто]")
    store.close()


# ---------------------------------------------------------------- 6, 7, 8. проверка текста
@pytest.mark.parametrize("text", [
    "Нарушен пункт 99．9 правил.",                 # полноширинная точка
    "Нарушен п. 99.9.1.1.1 правил.",                    # больше трёх уровней
    "Нарушен п. 2.1 ЖБ.",                               # раздел указан после номера, ЖБ 2.1 в правилах нет
    "Нарушен п. 7.7 Общих правил.",
])
def test_unverifiable_rule_reference_is_rejected(rb, text):
    v = verify_text("Здравствуйте! " + text, rb)
    assert not v.ok and v.violations[0].code == "rule_missing"


@pytest.mark.parametrize("text", [
    "We’ll unban you tomorrow.", "We'll refund the money.", "You will be banned.",
    "El jugador será castigado mañana.", "Lo banearé... castigaremos al jugador.",
    "O jogador será banido amanhã.", "Vamos reembolsaremos… baniremos o jogador.",
])
def test_promises_in_en_es_pt_are_rejected(rb, text):
    v = verify_text("Hello! " + text, rb)
    assert not v.ok and any(x.code == "promise" for x in v.violations), text


def test_legitimate_text_still_passes(rb):
    for t in ("Нарушен п. ЖБ 1.2.3 жалоб.", "п. 2.1 ОП", "Подождите 1.5 часа, версия 3.14.",
              "Меру назначит администратор.", "Your report was received, we will review it."):
        assert verify_text("Здравствуйте! " + t, rb).ok, t


# ---------------------------------------------------------------- 10, 11. дедупликация
def test_dedup_finds_original_even_if_older_ticket_was_added_later():
    d = DedupStore()
    kw = dict(reported=None, kind="complaint", category="complaint.insult")
    d.match_and_add(reporter="alice", text="оскорблял меня в чате", created_at="2026-10-30T10:00:00Z", ref="A", **kw)
    d.match_and_add(reporter="bob", text="другое", created_at="2026-10-30T08:00:00Z", ref="B", **kw)    # более раннее, добавлено позже
    m = d.match_and_add(reporter="alice", text="оскорблял меня в чате снова", created_at="2026-10-30T10:10:00Z", ref="C", **kw)
    assert m is not None and m.original_ref == "A"


def test_dedup_converts_time_zones_to_utc():
    d = DedupStore()
    kw = dict(reporter="alice", reported="bob", kind="complaint", category="x", text="оскорблял")
    d.match_and_add(created_at="2026-10-30T10:00:00+00:00", ref="A", **kw)
    m = d.match_and_add(created_at="2026-10-30T15:10:00+05:00", ref="B", **kw)       # то же время: 10:10 UTC
    assert m is not None and m.original_ref == "A" and 590 <= m.delta_seconds <= 610
    far = d.match_and_add(created_at="2026-10-30T12:30:00+05:00", ref="C", **kw)     # 07:30 UTC: вне окна и раньше
    assert far is None


def test_dedup_discard_removes_unsaved_ticket():
    d = DedupStore()
    kw = dict(reporter="alice", reported="bob", kind="complaint", category="x", text="оскорблял", created_at="2026-10-30T10:00:00Z")
    d.match_and_add(ref="GHOST", **kw)
    d.discard("GHOST")
    assert d.match_and_add(ref="REAL", **kw) is None


# ---------------------------------------------------------------- 2. сбой записи не оставляет призрак
def test_failed_write_does_not_leave_ghost_original(tmp_path, monkeypatch):
    svc, store = new_service(tmp_path)
    real = store.insert_ticket
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("диск недоступен")
        return real(**kw)

    monkeypatch.setattr(store, "insert_ticket", flaky)
    with pytest.raises(sqlite3.OperationalError):
        svc.create_from_form(form("Test_X оскорблял меня", "alice", reported_nick="Test_X"))
    assert store.count() == 0
    t, _ = svc.create_from_form(form("Test_X оскорблял меня", "alice", reported_nick="Test_X"))
    assert t["is_duplicate"] is False and t["id"] == "SNT-000001"
    store.close()


def test_huge_attachment_numbers_are_clamped_not_crashing(tmp_path):
    svc, store = new_service(tmp_path)
    t, _ = svc.create_from_payload({"kind": "report", "images_count": 2 ** 63,
                                   "messages": [{"role": "player", "text": "застрял", "attachments": 10 ** 20}]}, source="import")
    assert t["attachments"] == 1000
    store.close()


# ---------------------------------------------------------------- 9. единые лимиты на всех путях
def test_text_limit_applies_to_import_and_enqueue(boot):
    c, _ = boot()
    big = "а" * 8001
    assert c.post("/tickets", json={"kind": "report", "text": big}).status_code == 422
    r = c.post("/triage?enqueue=true", json={"kind": "report", "messages": [{"role": "player", "text": big}]})
    assert r.status_code == 422
    import json as j
    rep = c.post("/tickets/import", content=j.dumps({"kind": "report", "ticket_id": "X", "messages": [{"role": "player", "text": big}]}).encode()).json()
    assert rep["imported"] == 0 and rep["errors_total"] == 1 and "8000" in rep["errors"][0]["error"]
    many = {"kind": "report", "messages": [{"role": "player", "text": "a"}] * 101}
    assert c.post("/triage?enqueue=true", json=many).status_code == 422
    assert c.get("/tickets").json()["total"] == 0
    # контрактный POST /triage без enqueue этим лимитом не ограничивается
    assert c.post("/triage", json={"kind": "report", "messages": [{"role": "player", "text": big}]}).status_code == 200


# ---------------------------------------------------------------- 1, 5. два процесса на одной базе
def test_two_processes_share_one_database_without_collisions(tmp_path):
    a, sa = new_service(tmp_path, "a")
    b, sb = new_service(tmp_path, "b")
    ids, errors = [], []

    def worker(svc, tag):
        for i in range(12):
            try:
                t, _ = svc.create_from_form(form(f"застрял в текстурах {tag}{i}", f"{tag}-{i}", kind="report"))
                ids.append(t["id"])
            except Exception as e:  # pragma: no cover
                errors.append(repr(e))

    th = [threading.Thread(target=worker, args=(a, "a")), threading.Thread(target=worker, args=(b, "b"))]
    [t.start() for t in th]
    [t.join() for t in th]
    assert not errors, errors
    assert len(ids) == 24 and len(set(ids)) == 24 and sa.count() == 24
    sa.close()
    sb.close()


def test_same_idempotency_key_from_two_processes_returns_one_ticket(tmp_path, monkeypatch):
    a, sa = new_service(tmp_path, "a")
    b, sb = new_service(tmp_path, "b")
    first, created = a.create_from_form(form("Test_X оскорблял", "alice"), idem_key="same")
    assert created
    # второй процесс «не увидел» ключ при первой проверке (гонка): уникальный индекс срабатывает, ответ всё равно идемпотентный
    real_find = sb.find_by_idem
    hide = {"once": True}

    def find(k):
        return None if hide.pop("once", False) else real_find(k)

    monkeypatch.setattr(sb, "find_by_idem", find)
    second, created2 = b.create_from_form(form("Test_X оскорблял", "alice"), idem_key="same")
    assert created2 is False and second["id"] == first["id"] and sa.count() == 1
    sa.close()
    sb.close()


def test_ticket_id_reserved_under_write_lock_matches_final_id(tmp_path):
    svc, store = new_service(tmp_path)
    t1, _ = svc.create_from_form(form("Test_X оскорблял меня, скрин есть", "alice", reported_nick="Test_X"))
    t2, _ = svc.create_from_form(form("Test_X снова оскорбляет меня", "alice", reported_nick="Test_X"))
    assert t2["duplicate"]["original_id"] == t1["id"] == "SNT-000001" and t2["id"] == "SNT-000002"
    with pytest.raises(RuntimeError):
        store.insert_ticket(kind="report", source="manual", actor="t", request={}, player_text="x", meta={}, response={},
                            derived={"category": "report.help", "priority": "p2", "lang": "ru", "draft_lang": "ru",
                                     "intent": "x", "category_source": "rules", "needs_human": True, "needs_human_policy": True,
                                     "confidence": 0.5, "is_spam": False, "is_dup": False, "cited_count": 0, "guard_missing": False,
                                     "guard_promise": False, "guard_text_ref": False, "proposes_penalty": False, "llm": False,
                                     "latency_ms": 1, "rules_fingerprint": "x", "model_loaded": False},
                            draft={"text": "x", "cited": []}, dup=None, tid="SNT-000099")
    store.close()


# ---------------------------------------------------------------- 12. статистика из одного снимка
def test_stats_are_read_in_one_snapshot(tmp_path):
    store = Store(tmp_path / "snap.db")
    trace = []
    store._conn.set_trace_callback(trace.append)
    store.stats()
    stmts = [s.strip().split()[0].upper() for s in trace if s.strip()]
    assert stmts[0] == "BEGIN" and stmts[-1] == "COMMIT" and stmts.count("BEGIN") == 1 and stmts.count("COMMIT") == 1
    store.close()
