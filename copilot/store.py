"""Постоянное хранилище Sentra на SQLite (стандартная библиотека, без новых зависимостей).

Что хранится и зачем разделено:

* ``tickets``          обращение и его текущее состояние (статус, ревизия, действующие категория и приоритет);
* ``triage_results``   исходный ответ пайплайна: не меняется никогда, правки администратора сюда не попадают;
* ``draft_revisions``  все версии текста ответа: 0 это исходный черновик, дальше правки и утверждённая версия;
* ``decisions``        решения модератора: утвердил, правка, эскалация, закрытие, возврат в работу;
* ``duplicate_links``  связи повторного обращения с первым, с причиной и измеренными признаками;
* ``audit_events``     журнал всех изменений, только добавление; номер последнего события служит версией состояния;
* ``template_reviews`` решения по кандидатам в шаблоны.

Схема версионируется через ``PRAGMA user_version``; миграции применяются по порядку при открытии базы.
Секреты не хранятся: ключи LLM читаются из окружения и в базу не попадают, а текст игрока проходит ``redact``.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PRIORITIES = ("p0", "p1", "p2", "p3")
STATUSES = ("new", "approved", "escalated", "closed")


class StorageError(RuntimeError):
    """База недоступна или повреждена: причина написана по-русски и годится для показа в интерфейсе."""


MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "tickets_triage_decisions", """
CREATE TABLE tickets (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('complaint','report')),
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','api','import')),
  external_id TEXT,
  idem_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  received REAL NOT NULL,
  event_at TEXT,
  server TEXT,
  server_lang TEXT,
  reporter_id TEXT,
  reporter_nick TEXT,
  reported_nick TEXT,
  reported_id TEXT,
  attachments INTEGER NOT NULL DEFAULT 0,
  player_text TEXT NOT NULL,
  request_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','approved','escalated','closed')),
  rev INTEGER NOT NULL DEFAULT 1,
  eff_category TEXT NOT NULL,
  eff_priority TEXT NOT NULL CHECK (eff_priority IN ('p0','p1','p2','p3')),
  eff_needs_human INTEGER NOT NULL,
  draft_rev INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  closed_at TEXT
);
CREATE INDEX tickets_status ON tickets(status, received);
CREATE INDEX tickets_reporter ON tickets(reporter_id, received);
CREATE UNIQUE INDEX tickets_external ON tickets(source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE triage_results (
  ticket_id TEXT PRIMARY KEY REFERENCES tickets(id),
  response_json TEXT NOT NULL,
  category TEXT NOT NULL,
  priority TEXT NOT NULL,
  lang TEXT,
  draft_lang TEXT,
  intent TEXT,
  category_source TEXT,
  needs_human INTEGER NOT NULL,
  needs_human_policy INTEGER NOT NULL,
  confidence REAL,
  is_spam INTEGER NOT NULL DEFAULT 0,
  is_dup INTEGER NOT NULL DEFAULT 0,
  cited_count INTEGER NOT NULL DEFAULT 0,
  guard_missing INTEGER NOT NULL DEFAULT 0,
  guard_promise INTEGER NOT NULL DEFAULT 0,
  guard_text_ref INTEGER NOT NULL DEFAULT 0,
  proposes_penalty INTEGER NOT NULL DEFAULT 0,
  llm INTEGER NOT NULL DEFAULT 0,
  latency_ms REAL,
  total_ms REAL,
  rules_fingerprint TEXT,
  model_loaded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE draft_revisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL REFERENCES tickets(id),
  rev INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('original','edit','approved')),
  intent TEXT,
  lang TEXT,
  text TEXT NOT NULL,
  cited_json TEXT NOT NULL DEFAULT '[]',
  verification_json TEXT,
  author TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (ticket_id, rev)
);

CREATE TABLE decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL REFERENCES tickets(id),
  action TEXT NOT NULL CHECK (action IN ('approve','edit','escalate','close','reopen')),
  from_status TEXT NOT NULL,
  to_status TEXT NOT NULL,
  draft_rev INTEGER,
  final_category TEXT,
  final_priority TEXT,
  reason_code TEXT,
  comment TEXT,
  actor TEXT NOT NULL,
  ticket_rev_before INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX decisions_ticket ON decisions(ticket_id, id);

CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  event TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  ticket_id TEXT,
  data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_ticket ON audit_events(ticket_id, id);
"""),
    (2, "duplicates_templates", """
CREATE TABLE duplicate_links (
  ticket_id TEXT PRIMARY KEY REFERENCES tickets(id),
  original_id TEXT NOT NULL REFERENCES tickets(id),
  root_id TEXT NOT NULL REFERENCES tickets(id),
  kind TEXT NOT NULL,
  reason TEXT NOT NULL,
  same_reporter INTEGER NOT NULL,
  same_reported INTEGER NOT NULL,
  text_overlap REAL NOT NULL,
  category_equal INTEGER NOT NULL,
  delta_seconds REAL NOT NULL,
  window_seconds INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX duplicate_root ON duplicate_links(root_id);
CREATE INDEX duplicate_original ON duplicate_links(original_id);

CREATE TABLE template_reviews (
  key TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  cluster INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected')),
  template_original TEXT NOT NULL,
  template_final TEXT NOT NULL,
  safety_json TEXT,
  note TEXT,
  reviewer TEXT NOT NULL,
  rev INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ts * 1000) % 1000:03d}Z"


def _loads(s, default=None):
    if s is None:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(p * len(v)))]


class Store:
    def __init__(self, path: str | Path, clock=time.time):
        self.path = str(path)
        self.clock = clock
        self._lock = threading.RLock()
        self._depth = 0
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
            self._conn.row_factory = sqlite3.Row
            # встроенный lower() в SQLite понимает только ASCII, а поиск по-русски должен не зависеть от регистра
            self._conn.create_function("ucase", 1, lambda v: v.casefold() if isinstance(v, str) else v, deterministic=True)
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=10000")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA schema_version").fetchone()   # здесь падает файл, который не база
            self.migrate()
        except sqlite3.DatabaseError as e:
            raise StorageError(f"база {self.path} повреждена или не является базой SQLite: {e}. "
                               f"Восстановите её из копии или переименуйте файл, тогда Sentra создаст новую.") from e

    # ------------------------------------------------------------ служебное
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self):
        """Транзакция записи под блокировкой БД. Вложенный вызов работает в той же транзакции: так сервис держит
        блокировку на весь цикл «проверить ключ, выдать номер, разобрать, записать», в том числе между процессами."""
        with self._lock:
            if self._depth:
                yield self._conn
                return
            self._conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
            finally:
                self._depth = 0

    @contextmanager
    def read(self):
        """Согласованный снимок для нескольких запросов подряд: статистика не смешивает разные состояния базы."""
        with self._lock:
            if self._depth:
                yield self._conn
                return
            self._conn.execute("BEGIN")
            self._depth = 1
            try:
                yield self._conn
            finally:
                self._conn.execute("COMMIT")
                self._depth = 0

    def now(self) -> tuple[float, str]:
        ts = self.clock()
        return ts, iso(ts)

    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self, target: int | None = None) -> list[int]:
        """Применить недостающие миграции по порядку; возвращает номера применённых."""
        applied: list[int] = []
        with self._lock:
            current = self.schema_version()
            if current > SCHEMA_VERSION:
                raise StorageError(f"схема базы (v{current}) новее, чем понимает эта версия Sentra (v{SCHEMA_VERSION}): "
                                   f"обновите приложение, данные не тронуты")
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                               "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
            for version, name, sql in MIGRATIONS:
                if version <= current or (target is not None and version > target):
                    continue
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(sql):
                        self._conn.execute(stmt)
                    self._conn.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
                                       (version, name, self.now()[1]))
                    self._conn.execute(f"PRAGMA user_version={int(version)}")
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                applied.append(version)
        return applied

    # ------------------------------------------------------------ журнал
    def _event(self, c, actor: str, event: str, entity: str, entity_id: str, ticket_id: str | None = None,
               data: dict | None = None) -> int:
        cur = c.execute("INSERT INTO audit_events(ts, actor, event, entity, entity_id, ticket_id, data_json) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (self.now()[1], actor, event, entity, entity_id, ticket_id,
                         json.dumps(data or {}, ensure_ascii=False)))
        return cur.lastrowid

    def add_event(self, actor: str, event: str, entity: str, entity_id: str, ticket_id: str | None = None,
                  data: dict | None = None) -> int:
        with self.tx() as c:
            return self._event(c, actor, event, entity, entity_id, ticket_id, data)

    def version(self) -> int:
        """Номер последнего события журнала: меняется при любом изменении состояния."""
        with self._lock:
            return self._conn.execute("SELECT COALESCE(MAX(id),0) FROM audit_events").fetchone()[0]

    def events(self, ticket_id: str, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM audit_events WHERE ticket_id=? ORDER BY id LIMIT ?",
                                      (ticket_id, limit)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "actor": r["actor"], "event": r["event"], "entity": r["entity"],
                 "data": _loads(r["data_json"], {})} for r in rows]

    def count_events(self, event: str) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM audit_events WHERE event=?", (event,)).fetchone()[0]

    # ------------------------------------------------------------ создание
    def peek_next_id(self) -> str:
        """Идентификатор, который получит следующее обращение; вызывать внутри `tx()`: блокировка записи не даст
        другому процессу занять этот номер до записи."""
        with self.read():
            seq = self._conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM tickets").fetchone()[0]
        return f"SNT-{seq:06d}"

    def insert_ticket(self, *, kind: str, source: str, actor: str, request: dict, player_text: str, meta: dict,
                      response: dict, derived: dict, draft: dict, dup: dict | None, idem_key: str | None = None,
                      external_id: str | None = None, event_at: str | None = None, total_ms: float | None = None,
                      redactions: dict | None = None, tid: str | None = None) -> dict:
        """Одной транзакцией: обращение, исходный результат триажа, исходный черновик, связь дубля и события.
        `tid` это номер, выданный заранее под той же блокировкой (peek_next_id); если его нет, номер выдаётся здесь."""
        ts, stamp = self.now()
        with self.tx() as c:
            seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM tickets").fetchone()[0]
            if tid is not None and tid != f"SNT-{seq:06d}":
                raise RuntimeError(f"номер {tid} выдан не под блокировкой записи: ожидался SNT-{seq:06d}")
            tid = f"SNT-{seq:06d}"
            c.execute(
                "INSERT INTO tickets(seq,id,kind,source,external_id,idem_key,created_at,received,event_at,server,server_lang,"
                "reporter_id,reporter_nick,reported_nick,reported_id,attachments,player_text,request_json,status,rev,"
                "eff_category,eff_priority,eff_needs_human,draft_rev,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'new',1,?,?,?,0,?)",
                (seq, tid, kind, source, external_id, idem_key, stamp, ts, event_at, meta.get("server"),
                 meta.get("server_lang"), meta.get("reporter_id"), meta.get("reporter_nick"), meta.get("reported_nick"),
                 meta.get("reported_id"), int(meta.get("attachments") or 0), player_text,
                 json.dumps(request, ensure_ascii=False), derived["category"], derived["priority"],
                 int(derived["needs_human_policy"]), stamp))
            c.execute(
                "INSERT INTO triage_results(ticket_id,response_json,category,priority,lang,draft_lang,intent,category_source,"
                "needs_human,needs_human_policy,confidence,is_spam,is_dup,cited_count,guard_missing,guard_promise,"
                "guard_text_ref,proposes_penalty,llm,latency_ms,total_ms,rules_fingerprint,model_loaded,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, json.dumps(response, ensure_ascii=False), derived["category"], derived["priority"], derived["lang"],
                 derived["draft_lang"], derived["intent"], derived["category_source"], int(derived["needs_human"]),
                 int(derived["needs_human_policy"]), derived["confidence"], int(derived["is_spam"]), int(derived["is_dup"]),
                 derived["cited_count"], int(derived["guard_missing"]), int(derived["guard_promise"]),
                 int(derived["guard_text_ref"]), int(derived["proposes_penalty"]), int(derived["llm"]),
                 derived["latency_ms"], total_ms, derived["rules_fingerprint"], int(derived["model_loaded"]), stamp))
            c.execute("INSERT INTO draft_revisions(ticket_id,rev,kind,intent,lang,text,cited_json,author,created_at) "
                      "VALUES (?,0,'original',?,?,?,?,?,?)",
                      (tid, draft.get("intent"), draft.get("lang"), draft["text"],
                       json.dumps(draft.get("cited") or [], ensure_ascii=False), "pipeline", stamp))
            self._event(c, actor, "ticket.created", "ticket", tid, tid,
                        {"source": source, "kind": kind, "external_id": external_id, "redactions": redactions or {}})
            self._event(c, "pipeline", "ticket.triaged", "ticket", tid, tid,
                        {"category": derived["category"], "priority": derived["priority"],
                         "needs_human": bool(derived["needs_human_policy"]), "latency_ms": derived["latency_ms"],
                         "rules_fingerprint": derived["rules_fingerprint"]})
            if dup:
                root = c.execute("SELECT root_id FROM duplicate_links WHERE ticket_id=?",
                                 (dup["original_id"],)).fetchone()
                root_id = root["root_id"] if root else dup["original_id"]
                c.execute("INSERT INTO duplicate_links(ticket_id,original_id,root_id,kind,reason,same_reporter,same_reported,"
                          "text_overlap,category_equal,delta_seconds,window_seconds,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (tid, dup["original_id"], root_id, dup["kind"], dup["reason"], int(dup["same_reporter"]),
                           int(dup["same_reported"]), dup["text_overlap"], int(dup["category_equal"]),
                           dup["delta_seconds"], dup["window_seconds"], stamp))
                self._event(c, "pipeline", "ticket.duplicate_linked", "ticket", tid, tid,
                            {"original": dup["original_id"], "root": root_id, "kind": dup["kind"],
                             "text_overlap": dup["text_overlap"]})
        return self.get_ticket(tid)

    # ------------------------------------------------------------ чтение
    _BASE = ("SELECT t.*, r.response_json, r.category AS o_category, r.priority AS o_priority, r.needs_human AS o_needs_human,"
             " r.needs_human_policy AS p_needs_human, r.is_spam, r.is_dup, r.confidence, r.lang, r.draft_lang, r.intent,"
             " r.category_source, r.latency_ms, r.total_ms, r.rules_fingerprint, r.model_loaded, r.guard_missing,"
             " r.guard_promise, r.guard_text_ref, r.proposes_penalty, r.llm,"
             " d.original_id, d.root_id, d.kind AS dup_kind, d.reason AS dup_reason, d.same_reporter, d.same_reported,"
             " d.text_overlap, d.category_equal, d.delta_seconds, d.window_seconds"
             " FROM tickets t JOIN triage_results r ON r.ticket_id=t.id LEFT JOIN duplicate_links d ON d.ticket_id=t.id")

    def _summary(self, r: sqlite3.Row) -> dict:
        dup = None
        if r["original_id"]:
            dup = {"original_id": r["original_id"], "root_id": r["root_id"], "kind": r["dup_kind"], "reason": r["dup_reason"],
                   "same_reporter": bool(r["same_reporter"]), "same_reported": bool(r["same_reported"]),
                   "text_overlap": r["text_overlap"], "category_equal": bool(r["category_equal"]),
                   "delta_seconds": r["delta_seconds"], "window_seconds": r["window_seconds"]}
        return {
            "id": r["id"], "queue_id": r["id"], "seq": r["seq"], "kind": r["kind"], "source": r["source"],
            "status": r["status"], "rev": r["rev"], "created_at": r["created_at"], "received": r["received"],
            "updated_at": r["updated_at"], "closed_at": r["closed_at"], "text": r["player_text"],
            "server": r["server"], "reporter_id": r["reporter_id"], "reporter_nick": r["reporter_nick"],
            "reported_nick": r["reported_nick"], "attachments": r["attachments"], "external_id": r["external_id"],
            "lang": r["lang"], "draft_lang": r["draft_lang"], "intent": r["intent"], "confidence": r["confidence"],
            "category": r["eff_category"], "priority": r["eff_priority"], "needs_human": bool(r["eff_needs_human"]),
            "original": {"category": r["o_category"], "priority": r["o_priority"], "needs_human": bool(r["o_needs_human"]),
                         "category_source": r["category_source"]},
            "overridden": {"category": r["eff_category"] != r["o_category"], "priority": r["eff_priority"] != r["o_priority"]},
            "is_spam": bool(r["is_spam"]), "is_duplicate": bool(r["is_dup"]), "duplicate": dup,
            "latency_ms": r["latency_ms"], "draft_rev": r["draft_rev"],
        }

    def list_tickets(self, *, status: str | None = None, statuses: list[str] | None = None, priority: str | None = None,
                     q: str | None = None, kind: str | None = None, flagged: bool | None = None, limit: int = 200,
                     offset: int = 0, q_categories: list[str] | None = None) -> dict:
        where, args = [], []
        if statuses:
            where.append("t.status IN (%s)" % ",".join("?" * len(statuses)))
            args += statuses
        elif status:
            where.append("t.status=?")
            args.append(status)
        if priority:
            where.append("t.eff_priority=?")
            args.append(priority)
        if kind:
            where.append("t.kind=?")
            args.append(kind)
        if flagged:
            where.append("(r.is_spam=1 OR r.is_dup=1)")
        if q:
            # служебные символы LIKE (% _ \) ищутся буквально, регистр сворачивается для любого алфавита
            like = "%" + q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            cols = ("t.player_text", "t.id", "COALESCE(t.reported_nick,'')", "COALESCE(t.reporter_id,'')", "t.eff_category")
            clauses = [f"ucase({c}) LIKE ? ESCAPE '\\'" for c in cols]
            args += [like] * len(cols)
            if q_categories:                       # запрос совпал с названием категории («Оскорбление»), а в базе её код
                clauses.append("t.eff_category IN (%s)" % ",".join("?" * len(q_categories)))
                args += list(q_categories)
            where.append("(" + " OR ".join(clauses) + ")")
        sql_where = (" WHERE " + " AND ".join(where)) if where else ""
        order = (" ORDER BY CASE t.eff_priority WHEN 'p0' THEN 0 WHEN 'p1' THEN 1 WHEN 'p2' THEN 2 ELSE 3 END,"
                 " t.received DESC, t.seq DESC")
        with self.read():
            total = self._conn.execute(f"SELECT COUNT(*) FROM tickets t JOIN triage_results r ON r.ticket_id=t.id "
                                       f"LEFT JOIN duplicate_links d ON d.ticket_id=t.id{sql_where}", args).fetchone()[0]
            rows = self._conn.execute(f"{self._BASE}{sql_where}{order} LIMIT ? OFFSET ?",
                                      args + [int(limit), int(offset)]).fetchall()
        return {"total": total, "items": [self._summary(r) for r in rows]}

    def get_ticket(self, tid: str, *, detail: bool = True) -> dict | None:
        with self.read():
            r = self._conn.execute(f"{self._BASE} WHERE t.id=?", (tid,)).fetchone()
            if r is None:
                return None
            out = self._summary(r)
            if not detail:
                return out
            out["request"] = _loads(r["request_json"], {})
            out["response"] = _loads(r["response_json"], {})
            revs = self._conn.execute("SELECT * FROM draft_revisions WHERE ticket_id=? ORDER BY rev", (tid,)).fetchall()
            decisions = self._conn.execute("SELECT * FROM decisions WHERE ticket_id=? ORDER BY id", (tid,)).fetchall()
            repeats = self._conn.execute(
                "SELECT d.ticket_id, d.kind, d.reason, d.text_overlap, d.delta_seconds, d.original_id, t.received, t.status, "
                "t.player_text FROM duplicate_links d JOIN tickets t ON t.id=d.ticket_id "
                "WHERE d.root_id=? OR d.original_id=? ORDER BY t.received", (tid, tid)).fetchall()
        out["revisions"] = [{"rev": x["rev"], "kind": x["kind"], "intent": x["intent"], "lang": x["lang"], "text": x["text"],
                             "cited": _loads(x["cited_json"], []), "verification": _loads(x["verification_json"]),
                             "author": x["author"], "created_at": x["created_at"]} for x in revs]
        cur = next((x for x in reversed(out["revisions"]) if x["rev"] == out["draft_rev"]), out["revisions"][-1])
        out["draft"] = cur
        out["draft_original"] = out["revisions"][0]
        out["decisions"] = [{"id": x["id"], "action": x["action"], "from": x["from_status"], "to": x["to_status"],
                             "draft_rev": x["draft_rev"], "final_category": x["final_category"],
                             "final_priority": x["final_priority"], "reason_code": x["reason_code"], "comment": x["comment"],
                             "actor": x["actor"], "created_at": x["created_at"]} for x in decisions]
        out["last_decision"] = out["decisions"][-1] if out["decisions"] else None
        out["repeats"] = [{"id": x["ticket_id"], "kind": x["kind"], "reason": x["reason"], "text_overlap": x["text_overlap"],
                           "delta_seconds": x["delta_seconds"], "direct_original": x["original_id"], "received": x["received"],
                           "status": x["status"], "text": x["player_text"]} for x in repeats]
        out["history"] = self.events(tid)
        return out

    def find_by_idem(self, key: str) -> str | None:
        with self.read():
            r = self._conn.execute("SELECT id FROM tickets WHERE idem_key=?", (key,)).fetchone()
        return r["id"] if r else None

    def find_by_external(self, source: str, external_id: str) -> str | None:
        with self.read():
            r = self._conn.execute("SELECT id FROM tickets WHERE source=? AND external_id=?", (source, external_id)).fetchone()
        return r["id"] if r else None

    def dedup_rows(self, limit: int = 20000) -> list[dict]:
        """Запросы и исходные категории последних обращений: из них после перезапуска восстанавливается дедупликация."""
        with self.read():
            rows = self._conn.execute(
                "SELECT t.id, t.request_json, t.eff_needs_human, r.category FROM tickets t JOIN triage_results r ON r.ticket_id=t.id "
                "WHERE t.reporter_id IS NOT NULL AND t.reporter_id<>'' ORDER BY t.seq DESC LIMIT ?", (limit,)).fetchall()
        return [{"ref": r["id"], "payload": _loads(r["request_json"], {}), "category": r["category"],
                 "mandatory_human": bool(r["eff_needs_human"])} for r in reversed(rows)]

    def count(self) -> int:
        with self.read():
            return self._conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]

    def intent_counts(self) -> dict[str, int]:
        with self.read():
            return {r["intent"]: r["n"] for r in self._conn.execute(
                "SELECT intent, COUNT(*) n FROM triage_results WHERE intent IS NOT NULL GROUP BY intent")}

    # ------------------------------------------------------------ решения
    def apply_decision(self, tid: str, *, expected_rev: int, action: str, to_status: str, actor: str,
                       revision: dict | None = None, final_category: str | None = None,
                       final_priority: str | None = None, reason_code: str | None = None,
                       comment: str | None = None) -> dict:
        """Применить решение одной транзакцией. Бросает Conflict, если ревизия обращения уже ушла вперёд."""
        _, stamp = self.now()
        with self.tx() as c:
            row = c.execute("SELECT status, rev, eff_category, eff_priority, eff_needs_human, draft_rev FROM tickets WHERE id=?",
                            (tid,)).fetchone()
            if row is None:
                raise KeyError(tid)
            if row["rev"] != expected_rev:
                raise Conflict(tid, expected_rev, row["rev"], row["status"])
            draft_rev = row["draft_rev"]
            if revision:
                draft_rev = c.execute("SELECT COALESCE(MAX(rev),0)+1 FROM draft_revisions WHERE ticket_id=?", (tid,)).fetchone()[0]
                c.execute("INSERT INTO draft_revisions(ticket_id,rev,kind,intent,lang,text,cited_json,verification_json,author,"
                          "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (tid, draft_rev, revision["kind"], revision.get("intent"), revision.get("lang"), revision["text"],
                           json.dumps(revision.get("cited") or [], ensure_ascii=False),
                           json.dumps(revision.get("verification"), ensure_ascii=False), actor, stamp))
            cat = final_category or row["eff_category"]
            pri = final_priority or row["eff_priority"]
            eff_nh = int(row["eff_needs_human"])
            if to_status == "escalated" or pri == "p0" or cat in ("report.account", "report.payment", "complaint.admin"):
                eff_nh = 1
            closed_at = stamp if to_status == "closed" else None
            c.execute("UPDATE tickets SET status=?, rev=rev+1, eff_category=?, eff_priority=?, eff_needs_human=?, draft_rev=?, "
                      "updated_at=?, closed_at=? WHERE id=?",
                      (to_status, cat, pri, eff_nh, draft_rev, stamp, closed_at, tid))
            c.execute("INSERT INTO decisions(ticket_id,action,from_status,to_status,draft_rev,final_category,final_priority,"
                      "reason_code,comment,actor,ticket_rev_before,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, action, row["status"], to_status, draft_rev if revision else None, final_category, final_priority,
                       reason_code, comment, actor, expected_rev, stamp))
            self._event(c, actor, f"decision.{action}", "ticket", tid, tid,
                        {"from": row["status"], "to": to_status, "draft_rev": draft_rev if revision else None,
                         "final_category": final_category, "final_priority": final_priority, "reason": reason_code,
                         "comment": comment})
        return self.get_ticket(tid)

    # ------------------------------------------------------------ агрегаты
    def stats(self) -> dict:
        with self.read():
            c = self._conn
            total = c.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            by_status = {s: 0 for s in STATUSES}
            for r in c.execute("SELECT status, COUNT(*) n FROM tickets GROUP BY status"):
                by_status[r["status"]] = r["n"]
            by_kind = {r["kind"]: r["n"] for r in c.execute("SELECT kind, COUNT(*) n FROM tickets GROUP BY kind")}
            by_source = {r["source"]: r["n"] for r in c.execute("SELECT source, COUNT(*) n FROM tickets GROUP BY source")}
            pri_all = {p: 0 for p in PRIORITIES}
            pri_open = {p: 0 for p in PRIORITIES}
            for r in c.execute("SELECT eff_priority p, status='closed' closed, COUNT(*) n FROM tickets GROUP BY 1, 2"):
                pri_all[r["p"]] += r["n"]
                if not r["closed"]:
                    pri_open[r["p"]] += r["n"]
            cats, heat, flow_kc, flow_cd, risk = {}, {p: {} for p in PRIORITIES}, {}, {}, {}
            decide = {"h": 0, "a": 0}
            human_total = human_open = 0
            for r in c.execute("SELECT kind, eff_category cat, eff_priority p, eff_needs_human h, status='closed' closed, "
                               "COUNT(*) n FROM tickets GROUP BY 1,2,3,4,5"):
                n = r["n"]
                cats[r["cat"]] = cats.get(r["cat"], 0) + n
                heat[r["p"]][r["cat"]] = heat[r["p"]].get(r["cat"], 0) + n
                flow_kc[f'{r["kind"]}>{r["cat"]}'] = flow_kc.get(f'{r["kind"]}>{r["cat"]}', 0) + n
                key = f'{r["cat"]}>{"h" if r["h"] else "a"}'
                flow_cd[key] = flow_cd.get(key, 0) + n
                decide["h" if r["h"] else "a"] += n
                if r["h"]:
                    human_total += n
                    if not r["closed"]:
                        human_open += n
                rk = 2 if r["p"] == "p0" else 1 if r["p"] == "p1" else 0
                risk[r["cat"]] = max(risk.get(r["cat"], 0), rk)
            q = c.execute(
                "SELECT COUNT(*) n, SUM(is_spam) spam, SUM(is_dup) dup, SUM(cited_count>0) cited, SUM(guard_missing) gmiss, "
                "SUM(guard_promise) gprom, SUM(guard_text_ref) gtext, SUM(proposes_penalty) pen, SUM(llm) llm, "
                "SUM(category_source='model') model, SUM(confidence<0.5) low, AVG(confidence) conf, "
                "SUM(lang IS NOT NULL AND draft_lang IS NOT NULL AND lang<>draft_lang) langmis, "
                "SUM(needs_human_policy<>needs_human) policy, "
                "SUM(category IN ('report.account','report.payment','complaint.admin') OR priority='p0') sensitive "
                "FROM triage_results").fetchone()
            linked = c.execute("SELECT COUNT(*) n, COUNT(DISTINCT root_id) roots FROM duplicate_links").fetchone()
            flagged = c.execute("SELECT COUNT(*) FROM triage_results WHERE is_spam=1 OR is_dup=1").fetchone()[0]
            lat = [r[0] for r in c.execute("SELECT latency_ms FROM triage_results WHERE latency_ms IS NOT NULL")]
            tot = [r[0] for r in c.execute("SELECT total_ms FROM triage_results WHERE total_ms IS NOT NULL")]
            span = c.execute("SELECT MIN(created_at) a, MAX(created_at) b FROM tickets").fetchone()
            dec = {r["action"]: r["n"] for r in c.execute("SELECT action, COUNT(*) n FROM decisions GROUP BY action")}
            ov_cat = c.execute("SELECT COUNT(*) FROM tickets t JOIN triage_results r ON r.ticket_id=t.id "
                               "WHERE t.eff_category<>r.category").fetchone()[0]
            ov_pri = c.execute("SELECT COUNT(*) FROM tickets t JOIN triage_results r ON r.ticket_id=t.id "
                               "WHERE t.eff_priority<>r.priority").fetchone()[0]
            edited = c.execute("SELECT COUNT(DISTINCT ticket_id) FROM draft_revisions WHERE kind IN ('edit','approved') "
                               "AND rev>0 AND text<>(SELECT text FROM draft_revisions o WHERE o.ticket_id=draft_revisions.ticket_id "
                               "AND o.rev=0)").fetchone()[0]
            intents = {r["intent"]: r["n"] for r in c.execute(
                "SELECT intent, COUNT(*) n FROM triage_results WHERE intent IS NOT NULL GROUP BY intent")}
            langs = {r["lang"]: r["n"] for r in c.execute("SELECT lang, COUNT(*) n FROM triage_results GROUP BY lang")}
            blocked = c.execute("SELECT COUNT(*) FROM audit_events WHERE event='decision.blocked'").fetchone()[0]
            hourly = [{"h": r["h"], "n": r["n"]} for r in c.execute(
                "SELECT substr(created_at,1,13) h, COUNT(*) n FROM tickets GROUP BY 1 ORDER BY 1 DESC LIMIT 24")][::-1]
            version = c.execute("SELECT COALESCE(MAX(id),0) FROM audit_events").fetchone()[0]

        def lat_stats(v):
            return {"n": len(v), "p50": percentile(v, .5), "p95": percentile(v, .95), "p99": percentile(v, .99),
                    "max": max(v) if v else None, "mean": (sum(v) / len(v)) if v else None}
        return {
            "version": version, "generated_at": self.now()[1],
            "tickets": {"total": total, "by_status": by_status, "by_kind": by_kind, "by_source": by_source,
                        "awaiting": by_status["new"], "in_progress": by_status["approved"] + by_status["escalated"],
                        "closed": by_status["closed"], "open": total - by_status["closed"]},
            "priority": {"all": pri_all, "open": pri_open},
            "needs_human": {"total": human_total, "open": human_open, "auto_ok": total - human_total},
            "duplicates": {"tickets": q["dup"] or 0, "linked": linked["n"], "originals": linked["roots"], "spam": q["spam"] or 0,
                           "flagged": flagged},
            "categories": cats, "intents": intents, "langs": langs, "heat": heat,
            "flow": {"kind": by_kind, "cat": cats, "dec": decide, "links": {**flow_kc, **flow_cd}, "risk": risk},
            "hourly": hourly,
            "latency": dict(lat_stats(lat), source="время пайплайна в _meta.latency_ms, замер при каждом вызове"),
            "request_latency": dict(lat_stats(tot), source="полное время создания обращения вместе с записью в базу"),
            "quality_live": {
                "tickets": q["n"] or 0, "with_cites": q["cited"] or 0, "guard_removed_missing": q["gmiss"] or 0,
                "guard_promise": q["gprom"] or 0, "guard_text_ref": q["gtext"] or 0, "penalty": q["pen"] or 0,
                "llm": q["llm"] or 0, "by_model": q["model"] or 0, "low_confidence": q["low"] or 0,
                "avg_confidence": q["conf"], "lang_mismatch": q["langmis"] or 0, "policy_to_human": q["policy"] or 0,
                "sensitive_to_human": q["sensitive"] or 0,
                "approvals_blocked": blocked},
            "decisions": dec,
            "overrides": {"category": ov_cat, "priority": ov_pri, "text_edited": edited},
            "range": {"first": span["a"], "last": span["b"]},
        }

    def duplicates(self, limit: int = 100) -> dict:
        with self.read():
            c = self._conn
            roots = c.execute(
                "SELECT d.root_id, COUNT(*) n, MAX(t.received) last FROM duplicate_links d JOIN tickets t ON t.id=d.ticket_id "
                "GROUP BY d.root_id ORDER BY last DESC LIMIT ?", (limit,)).fetchall()
            groups = []
            for r in roots:
                orig = self.get_ticket(r["root_id"], detail=False)
                reps = c.execute(
                    "SELECT d.ticket_id FROM duplicate_links d JOIN tickets t ON t.id=d.ticket_id WHERE d.root_id=? "
                    "ORDER BY t.received", (r["root_id"],)).fetchall()
                groups.append({"original": orig, "repeats": [self.get_ticket(x["ticket_id"], detail=False) for x in reps]})
            spam = [self.get_ticket(r["ticket_id"], detail=False) for r in c.execute(
                "SELECT ticket_id FROM triage_results WHERE is_spam=1 ORDER BY created_at DESC LIMIT ?", (limit,))]
            reporters = [{"reporter_id": r["reporter_id"], "n": r["n"]} for r in c.execute(
                "SELECT reporter_id, COUNT(*) n FROM tickets WHERE reporter_id IS NOT NULL AND reporter_id<>'' "
                "GROUP BY reporter_id HAVING n>1 ORDER BY n DESC, reporter_id LIMIT 10")]
        return {"groups": groups, "spam": spam, "repeat_reporters": reporters}

    def revalidation_rows(self, limit: int = 5000) -> list[dict]:
        """Действующий текст и цитаты каждого обращения: для живой проверки цитат по текущему rules.json."""
        with self.read():
            rows = self._conn.execute(
                "SELECT t.id, v.text, v.cited_json FROM tickets t JOIN draft_revisions v "
                "ON v.ticket_id=t.id AND v.rev=t.draft_rev ORDER BY t.seq DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "text": r["text"], "cited": _loads(r["cited_json"], [])} for r in rows]

    # ------------------------------------------------------------ шаблоны
    def template_reviews(self) -> dict[str, dict]:
        with self.read():
            rows = self._conn.execute("SELECT * FROM template_reviews").fetchall()
        return {r["key"]: {"status": r["status"], "template_original": r["template_original"],
                           "template_final": r["template_final"], "safety": _loads(r["safety_json"]), "note": r["note"],
                           "reviewer": r["reviewer"], "rev": r["rev"], "updated_at": r["updated_at"]} for r in rows}

    def put_template_review(self, key: str, *, category: str, cluster: int, status: str, template_original: str,
                            template_final: str, safety: dict | None, note: str | None, actor: str,
                            expected_rev: int | None = None) -> dict:
        _, stamp = self.now()
        with self.tx() as c:
            cur = c.execute("SELECT rev, status FROM template_reviews WHERE key=?", (key,)).fetchone()
            if cur is not None and expected_rev is not None and cur["rev"] != expected_rev:
                raise Conflict(key, expected_rev, cur["rev"], cur["status"])
            if cur is None:
                c.execute("INSERT INTO template_reviews(key,category,cluster,status,template_original,template_final,"
                          "safety_json,note,reviewer,rev,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
                          (key, category, cluster, status, template_original, template_final,
                           json.dumps(safety, ensure_ascii=False), note, actor, stamp, stamp))
            else:
                c.execute("UPDATE template_reviews SET status=?, template_final=?, safety_json=?, note=?, reviewer=?, "
                          "rev=rev+1, updated_at=? WHERE key=?",
                          (status, template_final, json.dumps(safety, ensure_ascii=False), note, actor, stamp, key))
            self._event(c, actor, f"template.{status}", "template", key, None,
                        {"template_changed": template_final != template_original, "note": note,
                         "safety_ok": (safety or {}).get("ok")})
        return self.template_reviews()[key]


class Conflict(Exception):
    """Состояние обращения изменилось с момента, когда его видел клиент (двойной клик, второй модератор)."""

    def __init__(self, ticket_id: str, expected: int, actual: int, status: str):
        super().__init__(f"{ticket_id}: ожидалась ревизия {expected}, сейчас {actual}")
        self.ticket_id, self.expected, self.actual, self.status = ticket_id, expected, actual, status


def _split_sql(script: str) -> list[str]:
    """Разделить скрипт миграции на операторы: в миграциях нет триггеров и строк с точкой с запятой."""
    return [s.strip() for s in script.split(";") if s.strip()]
