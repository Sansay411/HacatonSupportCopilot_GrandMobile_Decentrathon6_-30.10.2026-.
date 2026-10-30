"""Жизненный цикл обращения через HTTP: создание, триаж, очередь, решения, статистика, перезапуск.
Всё работает на синтетических правилах tests/fixtures и без ML-моделей: данных кейса на машине нет."""
import json

import pytest


def form(text="Arman_Petrov оскорблял меня и мою семью в чате, скрины есть, 2.1 ОП", **kw):
    body = {"kind": "complaint", "text": text, "attachments": 2, "reporter": "p-1042", "reported_nick": "Arman_Petrov",
            "server": "5"}
    body.update(kw)
    return body


def make(c, text=None, *, key=None, **kw):
    body = form(text, **kw) if text is not None else form(**kw)
    r = c.post("/tickets", json=body, headers={"Idempotency-Key": key} if key else {})
    assert r.status_code in (200, 201), r.text
    return r.json()["ticket"]


def decide(c, t, action, **kw):
    return c.post(f"/tickets/{t['id']}/decision", json=dict(action=action, expected_rev=t["rev"], **kw))


# ---------------------------------------------------------------- создание и триаж
def test_create_runs_real_triage_and_persists_everything(boot):
    c, _ = boot()
    r = c.post("/tickets", json=form())
    assert r.status_code == 201
    t = r.json()["ticket"]
    assert t["id"] == "SNT-000001" and t["status"] == "new" and t["rev"] == 1 and t["created_at"].endswith("Z")
    assert t["category"] == "complaint.insult" and "2.1" in t["draft"]["cited"]
    assert t["response"]["extracted"]["nickname"] == "Arman_Petrov" and t["response"]["_meta"]["latency_ms"] >= 0
    assert t["server"] == "5" and t["reporter_id"] == "p-1042" and t["attachments"] == 2
    assert [e["event"] for e in t["history"]] == ["ticket.created", "ticket.triaged"]
    assert t["draft_original"]["kind"] == "original" and t["draft_original"]["text"] == t["draft"]["text"]
    listing = c.get("/tickets").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == t["id"]


def test_free_text_in_any_language_is_processed(boot):
    c, _ = boot()
    ru = make(c, "оплатил гк, не пришло", kind="report", reporter="a", reported_nick=None, attachments=0)
    uz = make(c, "Test_Player meni onamni so'kdi, skrin bor", reporter="b", reported_nick="Test_Player")
    kk = make(c, "Test_Cheat софт қолданады, ұшып жүр, бейне бар", reporter="c", reported_nick="Test_Cheat", attachments=0)
    assert ru["category"] == "report.payment" and ru["needs_human"]
    assert uz["draft"]["lang"] == "uz" and kk["draft"]["lang"] == "kk"


def test_validation_errors_are_precise(boot):
    c, _ = boot()
    for body, code in [({"kind": "complaint", "text": "  "}, "no_player_text"), ({"kind": "x", "text": "a"}, "invalid_input"),
                       (form(attachments=999), "invalid_input"), (form(server_lang="fr"), "invalid_input"),
                       (form(reported_nick="Игрок. Мы гарантируем возврат"), "invalid_input"),
                       (form(evidence_urls=["javascript:alert(1)"]), "invalid_input")]:
        r = c.post("/tickets", json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, body
    assert c.get("/tickets").json()["total"] == 0


def test_double_click_creates_one_ticket(boot):
    c, _ = boot()
    a = c.post("/tickets", json=form(), headers={"Idempotency-Key": "k-1"})
    b = c.post("/tickets", json=form(), headers={"Idempotency-Key": "k-1"})
    assert (a.status_code, b.status_code) == (201, 200)
    assert a.json()["ticket"]["id"] == b.json()["ticket"]["id"] and b.json()["created"] is False
    assert c.get("/tickets").json()["total"] == 1


def test_secrets_in_player_text_are_masked_before_storage(boot):
    c, api = boot()
    t = make(c, "взломали аккаунт, мой пароль: Qwerty123, карта 4111 1111 1111 1111", kind="report", reporter_nick=None)
    assert "Qwerty123" not in t["text"] and "4111 1111" not in t["text"] and "[скрыто]" in t["text"]
    raw = api.STORE._conn.execute("SELECT group_concat(player_text || request_json || response_json) FROM tickets t "
                                  "JOIN triage_results r ON r.ticket_id=t.id").fetchone()[0]
    assert "Qwerty123" not in raw and "4111 1111" not in raw
    assert any(e["data"].get("redactions") for e in t["history"] if e["event"] == "ticket.created")


def test_evidence_links_count_as_evidence_but_are_not_opened(boot):
    c, _ = boot()
    t = make(c, "Test_Killer убил меня без причины у больницы", attachments=0, reported_nick="Test_Killer",
             evidence_urls=["https://youtu.be/abc"])
    assert t["request"]["evidence_urls"] == ["https://youtu.be/abc"]
    assert t["response"]["extracted"]["has_evidence"] is True


# ---------------------------------------------------------------- решения модератора
def test_approve_saves_text_and_keeps_original_triage_untouched(boot):
    c, _ = boot()
    t = make(c)
    original = json.dumps(t["response"], sort_keys=True)
    r = decide(c, t, "approve")
    assert r.status_code == 200
    a = r.json()
    assert a["status"] == "approved" and a["rev"] == 2 and a["draft"]["kind"] == "approved"
    assert [x["rev"] for x in a["revisions"]] == [0, 1]
    assert json.dumps(a["response"], sort_keys=True) == original          # исходный триаж не менялся
    assert a["last_decision"]["action"] == "approve" and a["last_decision"]["actor"] == "moderator"


def test_edit_keeps_original_and_records_revision(boot):
    c, _ = boot()
    t = make(c)
    new_text = "Здравствуйте! Жалоба рассмотрена, нарушение п. 2.1 Общих правил. Срок назначит администратор."
    a = decide(c, t, "edit", text=new_text).json()
    assert a["status"] == "new" and a["draft"]["text"] == new_text and a["draft"]["kind"] == "edit"
    assert a["draft_original"]["text"] == t["draft"]["text"] != new_text
    assert a["draft"]["cited"] == ["2.1"]
    same = decide(c, a, "edit", text=new_text)
    assert same.status_code == 422 and same.json()["detail"]["code"] == "no_change"


@pytest.mark.parametrize("text,code", [
    ("Здравствуйте! Видно нарушение п. 99.9 Общих правил.", "rule_missing"),
    ("Здравствуйте! Бан будет снят завтра.", "promise"),
    ("Здравствуйте! Нарушитель будет наказан.", "promise"),
    ("   ", "empty"),
])
def test_unsafe_text_cannot_be_saved(boot, text, code):
    c, api = boot()
    t = make(c)
    r = decide(c, t, "approve", text=text)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "draft_rejected"
    assert code in {v["code"] for v in r.json()["detail"]["violations"]}
    cur = c.get(f"/tickets/{t['id']}").json()
    assert cur["status"] == "new" and cur["rev"] == 1 and len(cur["revisions"]) == 1      # ничего не сохранилось
    assert api.STORE.count_events("decision.blocked") == 1                                 # но попытка в журнале


def test_rule_number_in_text_is_checked_against_rules_not_trusted(boot):
    c, _ = boot()
    t = make(c)
    ok = decide(c, t, "approve", text="Здравствуйте! Нарушение п. 2.1 Общих правил подтверждено.")
    assert ok.status_code == 200 and ok.json()["draft"]["cited"] == ["2.1"]
    t2 = make(c, reporter="other", reported_nick="Test_Z", text="Test_Z оскорблял")
    bad = decide(c, t2, "approve", text="Здравствуйте! Нарушение п. 7.7 Общих правил подтверждено.")
    assert bad.status_code == 422


def test_escalate_requires_reason_and_changes_queue(boot):
    c, _ = boot()
    t = make(c)
    no_reason = decide(c, t, "escalate")
    assert no_reason.status_code == 422 and no_reason.json()["detail"]["code"] == "reason_required"
    other = decide(c, t, "escalate", reason="other")
    assert other.json()["detail"]["code"] == "comment_required"
    e = decide(c, t, "escalate", reason="admin_complaint", comment="жалоба на админа").json()
    assert e["status"] == "escalated" and e["last_decision"]["reason_code"] == "admin_complaint"
    assert c.get("/tickets?status=new").json()["total"] == 0
    assert c.get("/tickets?status=escalated").json()["items"][0]["id"] == t["id"]


def test_close_and_reopen_update_state_and_stats(boot):
    c, _ = boot()
    t = make(c)
    before = c.get("/stats").json()["tickets"]
    assert before["awaiting"] == 1 and before["closed"] == 0
    assert decide(c, t, "close").json()["detail"]["code"] == "reason_required"
    closed = decide(c, t, "close", reason="rejected", comment="нет доказательств").json()
    assert closed["status"] == "closed" and closed["closed_at"]
    after = c.get("/stats").json()["tickets"]
    assert after["awaiting"] == 0 and after["closed"] == 1 and after["open"] == 0
    assert decide(c, closed, "approve").status_code == 409          # закрытое сначала возвращают в работу
    reopened = decide(c, closed, "reopen").json()
    assert reopened["status"] == "new" and reopened["closed_at"] is None
    assert [d["action"] for d in reopened["decisions"]] == ["close", "reopen"]


def test_double_click_on_decision_is_applied_once(boot):
    c, _ = boot()
    t = make(c)
    first = decide(c, t, "approve")
    second = decide(c, t, "approve")          # тот же expected_rev: второй клик
    assert first.status_code == 200 and second.status_code == 409
    assert second.json()["detail"]["code"] == "conflict"
    assert len(c.get(f"/tickets/{t['id']}").json()["decisions"]) == 1


def test_category_and_priority_corrections_do_not_overwrite_model_output(boot):
    c, _ = boot()
    t = make(c)
    a = decide(c, t, "approve", category="complaint.other", priority="p1").json()
    assert a["category"] == "complaint.other" and a["priority"] == "p1"
    assert a["original"]["category"] == "complaint.insult" and a["original"]["priority"] == "p2"
    assert a["overridden"] == {"category": True, "priority": True}
    assert a["response"]["category"] == "complaint.insult"
    s = c.get("/stats").json()
    assert s["overrides"]["category"] == 1 and s["overrides"]["priority"] == 1 and s["categories"] == {"complaint.other": 1}
    assert decide(c, a, "edit", text="Здравствуйте! Другой текст.", category="report.help").status_code == 422   # чужая таксономия


# ---------------------------------------------------------------- дубли
def test_duplicate_links_original_with_measured_signals(boot):
    c, _ = boot()
    first = make(c)
    second = make(c, "Arman_Petrov снова оскорбляет мою семью, скрины прикрепил")
    assert first["is_duplicate"] is False and second["is_duplicate"] is True
    d = second["duplicate"]
    assert d["original_id"] == first["id"] == d["root_id"]
    assert d["same_reporter"] and d["same_reported"] and 0 <= d["text_overlap"] <= 1 and d["window_seconds"] == 3600
    assert second["needs_human"] is True                               # дубль не закрывается автоматически
    detail = c.get(f"/tickets/{first['id']}").json()
    assert [r["id"] for r in detail["repeats"]] == [second["id"]]


def test_chain_of_repeats_points_to_the_first_ticket(boot):
    c, _ = boot()
    a = make(c)
    b = make(c, "Arman_Petrov снова оскорбляет мою семью")
    d = make(c, "Arman_Petrov опять оскорбляет мою семью")
    assert b["duplicate"]["root_id"] == a["id"] and d["duplicate"]["root_id"] == a["id"]
    assert d["duplicate"]["original_id"] in (a["id"], b["id"])
    groups = c.get("/duplicates").json()["groups"]
    assert len(groups) == 1 and groups[0]["original"]["id"] == a["id"] and len(groups[0]["repeats"]) == 2


def test_different_reporters_are_not_duplicates(boot):
    c, _ = boot()
    make(c)
    other = make(c, reporter="p-9999")
    assert other["is_duplicate"] is False


def test_without_reporter_id_duplicates_are_not_checked(boot):
    c, _ = boot()
    make(c, reporter=None)
    assert make(c, reporter=None)["is_duplicate"] is False


def test_spam_is_flagged_but_stays_open(boot):
    c, _ = boot()
    t = make(c, "афыв афыв афыв афыв афыв афыв афыв афыв афыв афыв", attachments=0, reported_nick=None)
    assert t["is_spam"] is True and t["status"] == "new"
    assert c.get("/duplicates").json()["spam"][0]["id"] == t["id"]


# ---------------------------------------------------------------- перезапуск
def test_everything_survives_restart_including_dedup_memory(boot):
    c, _ = boot()
    a = make(c)
    b = make(c, "Arman_Petrov снова оскорбляет мою семью")
    e = decide(c, make(c, reporter="r-2", reported_nick="Test_Z", text="Test_Z оскорблял"), "escalate", reason="unclear").json()
    approved = decide(c, a, "approve", text="Здравствуйте! Нарушение п. 2.1 Общих правил подтверждено.").json()
    stats_before = c.get("/stats").json()
    c2, _ = boot()                                                  # новый процесс, та же база
    got = c2.get(f"/tickets/{a['id']}").json()
    assert got["status"] == "approved" and got["draft"]["text"] == approved["draft"]["text"] and got["rev"] == approved["rev"]
    assert got["draft_original"]["text"] == a["draft"]["text"]
    assert c2.get(f"/tickets/{e['id']}").json()["status"] == "escalated"
    assert c2.get(f"/tickets/{b['id']}").json()["duplicate"]["original_id"] == a["id"]
    after = c2.get("/stats").json()
    for k in ("tickets", "priority", "categories", "duplicates", "needs_human", "decisions", "overrides"):
        assert after[k] == stats_before[k], k
    # память дедупликации восстановлена: повтор после перезапуска снова находит оригинал
    again = c2.post("/tickets", json=form("Arman_Petrov в третий раз оскорбляет мою семью")).json()["ticket"]
    assert again["is_duplicate"] and again["duplicate"]["root_id"] == a["id"]
    assert again["id"] == "SNT-000004"                              # нумерация продолжается


def test_idempotency_key_survives_restart(boot):
    c, _ = boot()
    c.post("/tickets", json=form(), headers={"Idempotency-Key": "stable"})
    c2, _ = boot()
    r = c2.post("/tickets", json=form(), headers={"Idempotency-Key": "stable"})
    assert r.status_code == 200 and r.json()["created"] is False and c2.get("/tickets").json()["total"] == 1


# ---------------------------------------------------------------- статистика
def test_stats_are_consistent_with_queue(boot):
    c, _ = boot()
    texts = [("complaint", "Arman_Petrov оскорблял меня, 2.1 ОП", "a", "Arman_Petrov"), ("report", "оплатил гк, не пришло", "b", None),
             ("complaint", "Test_Cheater летает, использует софт", "c", "Test_Cheater"), ("report", "машина перевернулась, помогите", "d", None),
             ("complaint", "афыв афыв афыв афыв афыв афыв афыв афыв афыв афыв", "e", None)]
    tickets = [make(c, t, kind=k, reporter=r, reported_nick=n, attachments=1) for k, t, r, n in texts]
    decide(c, tickets[0], "close", reason="rejected")
    decide(c, tickets[1], "escalate", reason="payment")
    s = c.get("/stats").json()
    allq = c.get("/tickets?limit=500").json()
    assert s["tickets"]["total"] == allq["total"] == 5
    assert sum(s["tickets"]["by_status"].values()) == 5
    assert s["tickets"]["by_status"] == {"new": 3, "approved": 0, "escalated": 1, "closed": 1}
    assert sum(s["priority"]["all"].values()) == 5 and sum(s["categories"].values()) == 5
    assert sum(s["priority"]["open"].values()) == 4
    by_pri = {}
    for it in allq["items"]:
        by_pri[it["priority"]] = by_pri.get(it["priority"], 0) + 1
    assert {k: v for k, v in s["priority"]["all"].items() if v} == by_pri
    assert s["needs_human"]["total"] == sum(1 for it in allq["items"] if it["needs_human"])
    assert s["duplicates"]["spam"] == 1 and s["latency"]["n"] == 5 and s["latency"]["p95"] is not None
    assert sum(v for k, v in s["flow"]["links"].items() if ">" in k and k.split(">")[0] in ("complaint", "report")) == 5
    assert sum(s["flow"]["dec"].values()) == 5


def test_empty_stats_are_zero_not_fake(boot):
    c, _ = boot()
    s = c.get("/stats").json()
    assert s["tickets"]["total"] == 0 and s["latency"]["n"] == 0 and s["latency"]["p50"] is None and s["categories"] == {}
    assert c.get("/tickets").json() == {"total": 0, "items": []}


def test_live_citation_check_runs_against_current_rules(boot):
    c, _ = boot()
    make(c)
    chk = c.get("/stats").json()["live_citation_check"]
    assert chk["available"] and chk["checked"] == 1 and chk["failed"] == 0


# ---------------------------------------------------------------- импорт
def test_import_reports_broken_lines_and_is_repeatable(boot):
    c, _ = boot()
    lines = [json.dumps({"ticket_id": "T-1", "kind": "complaint", "created_at": "2026-10-30T10:00:00Z", "reporter_hash": "r1",
                         "messages": [{"role": "player", "text": "Arman_Petrov оскорблял меня, 2.1 ОП", "attachments": 1}]}),
             "{это не json",
             json.dumps({"ticket_id": "T-2", "kind": "report", "created_at": "2026-10-30T10:05:00Z",
                         "messages": [{"role": "player", "text": "застрял"}, {"role": "admin", "text": "ответ админа"}]}),
             json.dumps([1, 2, 3]),
             json.dumps({"ticket_id": "T-3", "kind": "report", "messages": [{"role": "player", "text": "  "}]}),
             json.dumps({"ticket_id": "T-4", "kind": "weird", "messages": []})]
    body = "\n".join(lines).encode("utf-8")
    r = c.post("/tickets/import", content=body).json()
    assert r["imported"] == 2 and r["errors_total"] == 4
    assert {e["line"] for e in r["errors"]} == {2, 4, 5, 6}
    assert all(e["error"] for e in r["errors"])
    assert c.get("/tickets").json()["total"] == 2
    again = c.post("/tickets/import", content=body).json()
    assert again["imported"] == 0 and again["skipped_existing"] == 2 and c.get("/tickets").json()["total"] == 2
    t = c.get("/tickets?q=застрял").json()["items"][0]
    assert t["source"] == "import" and t["external_id"] == "T-2"
    assert "ответ админа" not in json.dumps(c.get(f"/tickets/{t['id']}").json(), ensure_ascii=False)


def test_import_rejects_empty_and_non_utf8(boot):
    c, _ = boot()
    assert c.post("/tickets/import", content=b"").status_code == 422
    assert c.post("/tickets/import", content="привет".encode("cp1251")).status_code == 400


# ---------------------------------------------------------------- контракт /triage
def test_triage_contract_is_unchanged_and_stateless(boot):
    c, _ = boot()
    r = c.post("/triage", json={"kind": "complaint", "messages": [
        {"role": "player", "text": "Arman_Petrov оскорблял меня в чате, 2.1 ОП", "attachments": 2}]})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"lang", "category", "priority", "is_spam_or_duplicate", "extracted", "draft_reply", "needs_human",
                         "confidence", "reasons"}
    assert set(body["extracted"]) == {"nickname", "rule_refs", "has_evidence", "server"}
    assert set(body["draft_reply"]) == {"lang", "text", "cited"}
    assert c.get("/tickets").json()["total"] == 0                       # без enqueue ничего не сохраняется
    assert c.post("/triage", json={"kind": "report", "messages": [{"role": "player", "text": " "}]}).status_code == 422
    assert c.post("/triage", json={"kind": "other", "messages": []}).status_code == 422
    dbg = c.post("/triage?debug=true", json={"kind": "report", "messages": [{"role": "player", "text": "застрял"}]}).json()
    assert "_meta" in dbg


def test_triage_enqueue_stores_a_real_ticket(boot):
    c, _ = boot()
    r = c.post("/triage?enqueue=true", json={"kind": "report", "messages": [{"role": "player", "text": "застрял"}]}).json()
    assert r["queue_id"] == "SNT-000001"
    assert c.get("/tickets/SNT-000001").json()["source"] == "api"


# ---------------------------------------------------------------- поиск
def test_search_ignores_case_for_cyrillic(boot):
    c, _ = boot()
    t = make(c, "ОСКОРБЛЯЛ меня в чате, Test_Foo, скрин есть", reported_nick="Test_Foo", reporter="rr1")
    for q in ("оскорблял", "ОСКОРБЛЯЛ", "Оскорблял", "test_foo", "TEST_FOO", "snt-000001", "Оскорбление"):
        found = [x["id"] for x in c.get(f"/tickets?q={q}").json()["items"]]
        assert found == [t["id"]], q
    assert c.get("/tickets?q=несуществующее").json()["total"] == 0
    assert c.get("/tickets?q=100%25").json()["total"] == 0           # служебные символы LIKE ищутся буквально
