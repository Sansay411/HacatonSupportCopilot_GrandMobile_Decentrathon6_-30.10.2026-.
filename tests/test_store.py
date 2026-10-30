"""SQLite-хранилище: миграции, целостность, защита от повреждений."""
import sqlite3
import threading

import pytest

from copilot.store import SCHEMA_VERSION, MIGRATIONS, StorageError, Store

DERIVED = dict(category="report.help", priority="p2", lang="ru", draft_lang="ru", intent="help_ack", category_source="rules",
               needs_human=True, needs_human_policy=True, confidence=0.7, is_spam=False, is_dup=False, cited_count=0,
               guard_missing=False, guard_promise=False, guard_text_ref=False, proposes_penalty=False, llm=False,
               latency_ms=2.5, rules_fingerprint="abc", model_loaded=False)


def add(store, text="застрял", **kw):
    return store.insert_ticket(
        kind="report", source="manual", actor="t", request={"kind": "report", "messages": []}, player_text=text,
        meta={"reporter_id": "r-1"}, response={"category": "report.help", "_meta": {}}, derived=DERIVED,
        draft={"text": "Здравствуйте! Передали.", "cited": [], "intent": "help_ack", "lang": "ru"}, dup=None, **kw)


def test_fresh_database_gets_latest_schema(tmp_path):
    s = Store(tmp_path / "a.db")
    assert s.schema_version() == SCHEMA_VERSION == len(MIGRATIONS)
    tables = {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tickets", "triage_results", "draft_revisions", "decisions", "audit_events", "duplicate_links",
            "template_reviews", "schema_migrations"} <= tables
    s.close()


def test_migration_upgrade_keeps_data(tmp_path):
    path = tmp_path / "old.db"
    s = Store(path)
    s.close()
    # откат до версии 1 и данные в ней
    c = sqlite3.connect(path)
    c.executescript("DROP TABLE duplicate_links; DROP TABLE template_reviews; DELETE FROM schema_migrations WHERE version=2; "
                    "PRAGMA user_version=1;")
    c.close()
    s = Store(path)           # открытие применяет недостающую миграцию
    assert s.schema_version() == SCHEMA_VERSION
    t = add(s)
    assert t["id"] == "SNT-000001"
    s.close()
    s = Store(path)           # повторное открытие ничего не ломает и не применяет заново
    assert s.get_ticket("SNT-000001")["text"] == "застрял"
    assert [r[0] for r in s._conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
    s.close()


def test_newer_schema_is_refused_without_touching_data(tmp_path):
    path = tmp_path / "new.db"
    Store(path).close()
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    c.close()
    with pytest.raises(StorageError, match="новее"):
        Store(path)


def test_corrupted_file_gives_clear_error(tmp_path):
    path = tmp_path / "broken.db"
    path.write_bytes(b"this is not a sqlite database at all " * 100)
    with pytest.raises(StorageError, match="повреждена"):
        Store(path)


def test_ids_are_sequential_and_stable_across_reopen(tmp_path):
    s = Store(tmp_path / "ids.db")
    assert [add(s)["id"] for _ in range(3)] == ["SNT-000001", "SNT-000002", "SNT-000003"]
    s.close()
    s = Store(tmp_path / "ids.db")
    assert add(s)["id"] == "SNT-000004"
    s.close()


def test_idempotency_key_and_external_id_are_unique(tmp_path):
    s = Store(tmp_path / "u.db")
    add(s, idem_key="k1")
    with pytest.raises(sqlite3.IntegrityError):
        add(s, idem_key="k1")
    add(s, external_id="e1")
    with pytest.raises(sqlite3.IntegrityError):
        add(s, external_id="e1")
    assert s.count() == 2         # неудачная вставка откатилась целиком, без полу-записей
    assert s._conn.execute("SELECT COUNT(*) FROM triage_results").fetchone()[0] == 2
    s.close()


def test_failed_transaction_leaves_no_partial_rows(tmp_path):
    s = Store(tmp_path / "t.db")
    add(s)
    bad = dict(DERIVED, priority="p9")   # нарушает CHECK: падает после вставки части строк
    with pytest.raises(sqlite3.IntegrityError):
        s.insert_ticket(kind="report", source="manual", actor="t", request={}, player_text="x", meta={}, response={},
                        derived=bad, draft={"text": "x", "cited": []}, dup=None)
    assert s.count() == 1
    assert s._conn.execute("SELECT COUNT(*) FROM draft_revisions").fetchone()[0] == 1
    s.close()


def test_decision_conflict_on_stale_revision(tmp_path):
    from copilot.store import Conflict
    s = Store(tmp_path / "c.db")
    t = add(s)
    s.apply_decision(t["id"], expected_rev=1, action="escalate", to_status="escalated", actor="a", reason_code="unclear")
    with pytest.raises(Conflict):
        s.apply_decision(t["id"], expected_rev=1, action="close", to_status="closed", actor="a")
    assert s.get_ticket(t["id"])["status"] == "escalated"
    s.close()


def test_concurrent_creation_never_duplicates_sequence(tmp_path):
    s = Store(tmp_path / "race.db")
    ids, errors = [], []

    def worker():
        try:
            ids.append(add(s)["id"])
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=worker) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and len(set(ids)) == 12 and s.count() == 12
    s.close()


def test_audit_version_grows_with_every_change(tmp_path):
    s = Store(tmp_path / "v.db")
    v0 = s.version()
    t = add(s)
    v1 = s.version()
    s.apply_decision(t["id"], expected_rev=1, action="close", to_status="closed", actor="a", reason_code="no_action")
    assert v0 < v1 < s.version()
    s.close()
