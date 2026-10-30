"""Жизненный цикл обращения в Sentra: создание, импорт, решения модератора, шаблоны, статистика.

Здесь живёт вся логика продукта поверх пайплайна и хранилища, а HTTP-слой (api.py) только разбирает запрос.
Принципы:

* исходный результат триажа пишется один раз и больше не меняется, решения модератора лежат отдельно;
* ничего не «отправляется»: канала доставки игрокам нет, поэтому утверждённый текст только сохраняется;
* текст ответа, который утверждает человек, проверяется кодом по rules.json заново (пункты, обещания);
* повторное нажатие кнопки не создаёт второе обращение (Idempotency-Key) и не применяет решение дважды (ревизия).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

from . import lang as lang_mod
from . import selfcheck, taxonomy, verify
from .redact import redact
from .store import Conflict, Store, iso
from .ticket import _to_int, from_dict, has_player_content, safe_nick

ACTOR = "moderator"
MAX_TEXT_IN = 8000
MAX_MESSAGES = 100
MAX_ATTACH = 1000
MAX_IMPORT_BYTES = 5_000_000
MAX_IMPORT_LINES = 5000
KNOWN_PLACEHOLDERS = {"nick", "n"}

ESCALATION_REASONS = {
    "senior_admin": "Решение старшей администрации",
    "payment": "Платёж: нужна техподдержка",
    "account": "Взлом или доступ к аккаунту",
    "admin_complaint": "Жалоба на администратора",
    "threat": "Угроза вне игры",
    "unclear": "Не хватает данных для решения",
    "other": "Другая причина (опишите)",
}
CLOSE_REASONS = {
    "answered": "Игроку ответили вручную",
    "rejected": "Жалоба отклонена",
    "violation_confirmed": "Нарушение подтверждено, наказание назначает администратор",
    "duplicate": "Дубль другого обращения",
    "spam": "Спам или флуд",
    "no_action": "Действий не требуется",
    "other": "Другая причина (опишите)",
}
TRANSITIONS = {
    "approve": {"new": "approved", "approved": "approved", "escalated": "approved"},
    "edit": {"new": "new", "approved": "approved", "escalated": "escalated"},
    "escalate": {"new": "escalated", "approved": "escalated"},
    "close": {"new": "closed", "approved": "closed", "escalated": "closed"},
    "reopen": {"approved": "new", "escalated": "new", "closed": "new"},
}


class ApiError(Exception):
    def __init__(self, http_status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = http_status, code, message, extra

    def body(self) -> dict:
        return {"detail": {"code": self.code, "message": self.message, **self.extra}}


def _s(v, limit: int, field: str, required: bool = False) -> str | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ApiError(422, "invalid_input", "Поле обязательно", field=field)
        return None
    if not isinstance(v, (str, int)):
        raise ApiError(422, "invalid_input", "Ожидалась строка", field=field)
    v = str(v).strip()
    if len(v) > limit:
        raise ApiError(422, "invalid_input", f"Не длиннее {limit} символов", field=field)
    return v


def _redact_deep(obj, counts: dict):
    """Маскирует секреты во всех строках структуры: сообщения, ссылки, служебные поля. Счётчики копятся в `counts`."""
    if isinstance(obj, str):
        r = redact(obj)
        for k, v in r.counts.items():
            counts[k] = counts.get(k, 0) + v
        return r.text
    if isinstance(obj, dict):
        return {k: _redact_deep(v, counts) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_deep(v, counts) for v in obj]
    return obj


class TicketService:
    def __init__(self, copilot, store: Store, *, templates_json: Path, templates_md: Path | None = None,
                 private_templates: Path | None = None, metrics_json: Path | None = None):
        self.cp = copilot
        self.store = store
        self.templates_json = Path(templates_json)
        self.templates_md = Path(templates_md) if templates_md else None
        self.private_templates = Path(private_templates) if private_templates else None
        self.metrics_json = Path(metrics_json) if metrics_json else None
        self._create_lock = threading.Lock()
        self._cite_cache: tuple | None = None
        if copilot is not None:
            copilot.dedup.restore(self._dedup_state())   # дедупликация переживает перезапуск

    def _dedup_state(self) -> list[dict]:
        """Память дедупликации из сохранённых обращений: ключи собираются тем же кодом, что и в живом пути."""
        items = []
        for r in self.store.dedup_rows():
            t = from_dict(r["payload"])
            items.append({"reporter": t.reporter_hash, "reported": t.reported_hash or t.reported_nick, "text": t.player_text,
                          "kind": t.kind, "category": r["category"], "ts": t.created_at, "ref": r["ref"]})
        return items

    # ------------------------------------------------------------------ создание
    def _require_cp(self):
        if self.cp is None:
            raise ApiError(503, "triage_unavailable", "Триаж недоступен: не загружены правила (см. /health)")
        return self.cp

    def create_from_form(self, body: dict, *, idem_key: str | None = None, actor: str = ACTOR, source: str = "manual") -> tuple[dict, bool]:
        """Обращение, созданное в интерфейсе или через API Sentra. Возвращает (обращение, создано_ли_сейчас)."""
        kind = body.get("kind")
        if kind not in ("complaint", "report"):
            raise ApiError(422, "invalid_input", "Тип обращения: complaint или report", field="kind")
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ApiError(422, "no_player_text", "В обращении нет текста игрока", field="text")
        if len(text) > MAX_TEXT_IN:
            raise ApiError(422, "invalid_input", f"Текст длиннее {MAX_TEXT_IN} символов", field="text")
        try:
            att = int(body.get("attachments") or 0)
        except (TypeError, ValueError):
            raise ApiError(422, "invalid_input", "Число вложений должно быть целым", field="attachments")
        if not 0 <= att <= 50:
            raise ApiError(422, "invalid_input", "Вложений от 0 до 50", field="attachments")
        server = _s(body.get("server"), 40, "server")
        server_lang = _s(body.get("server_lang"), 8, "server_lang")
        if server_lang not in (None, "ru", "uz", "kk"):
            raise ApiError(422, "invalid_input", "Язык сервера: ru, uz или kk", field="server_lang")
        reporter = _s(body.get("reporter"), 64, "reporter")
        reported_nick = _s(body.get("reported_nick"), 32, "reported_nick")
        if reported_nick and not safe_nick(reported_nick):
            raise ApiError(422, "invalid_input", "Ник нарушителя: буквы, цифры, точка, дефис, подчёркивание, 2-32 символа",
                           field="reported_nick")
        reported_id = _s(body.get("reported_id"), 64, "reported_id")
        urls = body.get("evidence_urls") or []
        if not isinstance(urls, list) or len(urls) > 10:
            raise ApiError(422, "invalid_input", "Ссылок на доказательства не больше 10", field="evidence_urls")
        clean_urls = []
        for u in urls:
            u = _s(u, 500, "evidence_urls")
            if u and not re.match(r"^https?://\S+$", u, re.I):
                raise ApiError(422, "invalid_input", "Ссылка должна начинаться с http:// или https://", field="evidence_urls")
            if u:
                clean_urls.append(u)
        messages = [{"role": "player", "text": text, "attachments": att}]
        if clean_urls:
            messages.append({"role": "player", "text": "\n".join(clean_urls), "attachments": 0})
        payload = {"kind": kind, "messages": messages}
        if reporter:
            payload["reporter_hash"] = reporter.lower()
        if reported_nick:
            payload["reported_nick"] = reported_nick
        if reported_id:
            payload["reported_hash"] = reported_id.lower()
        if server_lang:
            payload["server_lang"] = server_lang
        meta = {"server": server, "server_lang": server_lang, "reporter_id": reporter, "reporter_nick": None,
                "reported_nick": reported_nick, "reported_id": reported_id, "attachments": att}
        return self._ingest(payload, meta=meta, source=source, idem_key=idem_key, actor=actor,
                            display_text=text, evidence_urls=clean_urls)

    def create_from_payload(self, payload: dict, *, source: str = "api", idem_key: str | None = None,
                            external_id: str | None = None, actor: str = ACTOR) -> tuple[dict, bool]:
        """Обращение в формате POST /triage или строки tickets.jsonl (API с enqueue=true и импорт)."""
        msgs = [m for m in (payload.get("messages") or []) if isinstance(m, dict) and m.get("role") != "admin"]
        if len(msgs) > MAX_MESSAGES:
            raise ApiError(422, "invalid_input", f"В обращении больше {MAX_MESSAGES} сообщений")
        msgs = [dict(m, attachments=min(max(0, _to_int(m.get("attachments"))), MAX_ATTACH)) if "attachments" in m else m for m in msgs]
        payload = dict(payload, messages=msgs)
        if payload.get("images_count") is not None:
            payload["images_count"] = min(max(0, _to_int(payload["images_count"])), MAX_ATTACH)
        if not has_player_content(payload):
            raise ApiError(422, "no_player_text", "В обращении нет сообщений игрока")
        players = [m for m in msgs if m.get("role", "player") == "player"]
        text = "\n".join(str(m.get("text") or "") for m in players)
        if len(text) > MAX_TEXT_IN:
            raise ApiError(422, "invalid_input", f"Текст игрока длиннее {MAX_TEXT_IN} символов")
        att = payload.get("images_count")
        if att is None:
            att = min(sum(max(0, _to_int(m.get("attachments"))) for m in players), MAX_ATTACH)
        meta = {"server": None, "server_lang": payload.get("server_lang"), "reporter_id": payload.get("reporter_hash"),
                "reporter_nick": None, "reported_nick": safe_nick(payload.get("reported_nick")),
                "reported_id": payload.get("reported_hash"), "attachments": int(att or 0)}
        ext = external_id or (str(payload["ticket_id"]) if payload.get("ticket_id") else None)
        return self._ingest(payload, meta=meta, source=source, idem_key=idem_key, actor=actor, display_text=text,
                            external_id=ext[:128] if ext else None, event_at=payload.get("created_at"))

    def _ingest(self, payload: dict, *, meta: dict, source: str, idem_key: str | None, actor: str, display_text: str,
                external_id: str | None = None, event_at: str | None = None, evidence_urls: list[str] | None = None) -> tuple[dict, bool]:
        cp = self._require_cp()
        if idem_key is not None and not (0 < len(idem_key) <= 128):
            raise ApiError(422, "invalid_input", "Idempotency-Key: от 1 до 128 символов")
        t0 = time.perf_counter()
        red_counts: dict[str, int] = {}
        payload = _redact_deep(payload, red_counts)           # секреты не попадают ни в разбор, ни в базу
        meta = _redact_deep(meta, red_counts)
        urls = _redact_deep(list(evidence_urls or []), red_counts)
        shown = redact(display_text)
        tid = None
        try:
            # блокировка записи БД держится на весь цикл: ключ идемпотентности, номер, разбор и запись видят одно состояние
            with self._create_lock, self.store.tx():
                for lookup in ((self.store.find_by_idem, idem_key), (lambda k: self.store.find_by_external(source, k), external_id)):
                    if lookup[1]:
                        existing = lookup[0](lookup[1])
                        if existing:
                            return self.store.get_ticket(existing), False
                tid = self.store.peek_next_id()
                now_ts, now_iso = self.store.now()
                payload.setdefault("created_at", now_iso)
                payload["ticket_id"] = payload.get("ticket_id") or tid
                resp = cp.triage(payload, ref=tid)
                meta_r = resp["_meta"]
                dedup = meta_r.get("dedup")
                reasons = resp["reasons"]
                needs_human = bool(resp["needs_human"])
                policy = []
                if dedup and not needs_human:
                    policy.append("политика Sentra: повтор не закрывается автоматически из-за похожего текста, решает администратор")
                if meta_r.get("intent") == "approve" and not resp["extracted"]["has_evidence"]:
                    # pipeline по умолчанию подтверждает оскорбление, даже если вложений нет; в продукте это проверяет человек
                    policy.append("политика Sentra: в черновике нарушение подтверждается «по приложенным материалам», но вложений и "
                                  "ссылок в обращении нет; проверьте или выберите «Запросить доказательства»")
                policy_nh = needs_human or bool(dedup) or bool(policy)
                resp["_meta"]["policy"] = policy
                if red_counts:
                    resp["_meta"]["redactions"] = red_counts
                dup_row = None
                if dedup and dedup.get("original_ref"):
                    dup_row = dict(dedup, original_id=dedup["original_ref"])
                derived = {
                    "category": resp["category"], "priority": resp["priority"], "lang": resp["lang"],
                    "draft_lang": resp["draft_reply"]["lang"], "intent": meta_r.get("intent"),
                    "category_source": meta_r.get("category_source"), "needs_human": needs_human,
                    "needs_human_policy": policy_nh, "confidence": resp["confidence"],
                    "is_spam": any("признаки спама" in r for r in reasons), "is_dup": bool(dedup),
                    "cited_count": len(resp["draft_reply"]["cited"]),
                    "guard_missing": any("несуществующие пункты" in r for r in reasons),
                    "guard_promise": any("обещание" in r for r in reasons),
                    "guard_text_ref": any("в тексте черновика пункт" in r for r in reasons),
                    "proposes_penalty": any("предлагает наказание" in r for r in reasons),
                    "llm": bool(meta_r.get("llm")), "latency_ms": meta_r.get("latency_ms"),
                    "rules_fingerprint": meta_r.get("rules_fingerprint"), "model_loaded": cp.category_model.loaded,
                }
                request = dict(payload)
                if urls:
                    request["evidence_urls"] = urls
                ticket = self.store.insert_ticket(
                    kind=payload["kind"], source=source, actor=actor, request=request, player_text=shown.text, meta=meta,
                    response=resp, derived=derived,
                    draft={"text": resp["draft_reply"]["text"], "cited": resp["draft_reply"]["cited"],
                           "intent": meta_r.get("intent"), "lang": resp["draft_reply"]["lang"]},
                    dup=dup_row, idem_key=idem_key, external_id=external_id, event_at=event_at, tid=tid,
                    total_ms=round((time.perf_counter() - t0) * 1000, 2), redactions=red_counts)
                return ticket, True
        except BaseException as e:
            if tid is not None:
                cp.dedup.discard(tid)              # несохранённое обращение не должно стать оригиналом для следующих
            if isinstance(e, sqlite3.IntegrityError):
                # гонка за тот же ключ: запись другого запроса уже есть, отдаём её как повторный ответ
                existing = (idem_key and self.store.find_by_idem(idem_key)) or \
                           (external_id and self.store.find_by_external(source, external_id))
                if existing:
                    return self.store.get_ticket(existing), False
            raise

    # ------------------------------------------------------------------ импорт
    def import_jsonl(self, raw: bytes | str, *, actor: str = ACTOR) -> dict:
        if isinstance(raw, bytes):
            if len(raw) > MAX_IMPORT_BYTES:
                raise ApiError(413, "too_large", f"Файл больше {MAX_IMPORT_BYTES // 1_000_000} МБ")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as e:
                raise ApiError(400, "bad_encoding", f"Файл не в кодировке UTF-8: {e}")
        else:
            text = raw
        lines = [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if ln.strip()]
        if len(lines) > MAX_IMPORT_LINES:
            raise ApiError(413, "too_many_lines", f"Не больше {MAX_IMPORT_LINES} строк за один импорт")
        if not lines:
            raise ApiError(422, "empty_file", "В файле нет строк с обращениями")
        self._require_cp()
        errors: list[dict] = []
        rows: list[tuple[int, dict]] = []
        for i, ln in lines:
            try:
                d = json.loads(ln)
            except ValueError as e:
                errors.append({"line": i, "error": f"не JSON: {str(e)[:80]}"})
                continue
            if not isinstance(d, dict):
                errors.append({"line": i, "error": "строка не является JSON-объектом"})
                continue
            if d.get("kind") not in ("complaint", "report"):
                d = dict(d, kind="report" if d.get("kind") is None else d["kind"])
            if d["kind"] not in ("complaint", "report"):
                errors.append({"line": i, "error": f"неизвестный kind: {str(d['kind'])[:30]}"})
                continue
            if not isinstance(d.get("messages"), list):
                errors.append({"line": i, "error": "нет списка messages"})
                continue
            rows.append((i, d))
        # дедупликация работает по времени: обрабатываем в порядке created_at, при равенстве в порядке строк
        rows.sort(key=lambda r: (r[1].get("created_at") if isinstance(r[1].get("created_at"), str) else "", r[0]))
        imported, existing = [], 0
        for i, d in rows:
            try:
                t, created = self.create_from_payload(d, source="import", actor=actor)
            except ApiError as e:
                errors.append({"line": i, "error": e.message})
                continue
            except Exception as e:  # одна строка не должна ронять весь импорт
                errors.append({"line": i, "error": f"ошибка обработки: {type(e).__name__}"})
                continue
            if created:
                imported.append(t["id"])
            else:
                existing += 1
        errors.sort(key=lambda e: e["line"])
        self.store.add_event(actor, "import.finished", "import", "jsonl", None,
                             {"lines": len(lines), "imported": len(imported), "skipped_existing": existing, "errors": len(errors)})
        return {"lines": len(lines), "imported": len(imported), "skipped_existing": existing, "errors": errors[:100],
                "errors_total": len(errors), "ids": imported[:50]}

    # ------------------------------------------------------------------ решения
    def decide(self, tid: str, body: dict, *, actor: str = ACTOR) -> dict:
        t = self.store.get_ticket(tid)
        if t is None:
            raise ApiError(404, "not_found", "Нет такого обращения")
        action = body.get("action")
        if action not in TRANSITIONS:
            raise ApiError(422, "invalid_input", "Действие: approve, edit, escalate, close или reopen", field="action")
        try:
            expected = int(body.get("expected_rev"))
        except (TypeError, ValueError):
            raise ApiError(422, "invalid_input", "Нужна ревизия обращения expected_rev", field="expected_rev")
        to_status = TRANSITIONS[action].get(t["status"])
        if to_status is None:
            raise ApiError(409, "invalid_transition", f"Из статуса «{t['status']}» нельзя выполнить «{action}»",
                           status=t["status"], rev=t["rev"])
        if expected != t["rev"]:
            raise ApiError(409, "conflict", "Обращение уже изменилось: обновите карточку", status=t["status"], rev=t["rev"])

        cats = taxonomy.COMPLAINT_CATS if t["kind"] == "complaint" else taxonomy.REPORT_CATS
        final_cat, final_pri = body.get("category"), body.get("priority")
        if final_cat is not None and final_cat not in cats:
            raise ApiError(422, "invalid_input", "Категория не из таксономии для этого типа обращения", field="category")
        if final_pri is not None and final_pri not in taxonomy.PRIORITIES:
            raise ApiError(422, "invalid_input", "Приоритет: p0, p1, p2 или p3", field="priority")
        final_cat = final_cat if final_cat and final_cat != t["category"] else None
        final_pri = final_pri if final_pri and final_pri != t["priority"] else None

        reason = _s(body.get("reason"), 40, "reason")
        comment = _s(body.get("comment"), 1000, "comment")
        if action in ("escalate", "close"):
            allowed = ESCALATION_REASONS if action == "escalate" else CLOSE_REASONS
            if reason not in allowed:
                raise ApiError(422, "reason_required", "Укажите причину из списка", field="reason", allowed=allowed)
            if reason == "other" and not comment:
                raise ApiError(422, "comment_required", "Для причины «другая» опишите её в комментарии", field="comment")

        revision = None
        if action in ("approve", "edit"):
            cp = self._require_cp()
            text = body.get("text")
            if text is None and action == "approve":
                text = t["draft"]["text"]
            if not isinstance(text, str):
                raise ApiError(422, "invalid_input", "Нужен текст ответа", field="text")
            if action == "edit" and text.strip() == t["draft"]["text"].strip():
                raise ApiError(422, "no_change", "Текст не изменился: сохранять нечего")
            v = verify.verify_text(text, cp.rules)
            if not v.ok:
                self.store.add_event(actor, "decision.blocked", "ticket", tid, tid,
                                     {"action": action, "violations": [x.as_dict() for x in v.violations]})
                raise ApiError(422, "draft_rejected", "Текст не прошёл проверку и не сохранён",
                               violations=[x.as_dict() for x in v.violations])
            revision = {"kind": "approved" if action == "approve" else "edit", "text": text, "cited": v.cited,
                        "intent": body.get("intent") or t["draft"]["intent"], "lang": t["draft"]["lang"],
                        "verification": v.as_dict()}
        try:
            return self.store.apply_decision(tid, expected_rev=expected, action=action, to_status=to_status, actor=actor,
                                             revision=revision, final_category=final_cat, final_priority=final_pri,
                                             reason_code=reason, comment=comment)
        except Conflict as c:
            raise ApiError(409, "conflict", "Обращение уже изменилось: обновите карточку", status=c.status, rev=c.actual)

    # ------------------------------------------------------------------ статистика и диагностика
    def stats(self) -> dict:
        s = self.store.stats()
        s["live_citation_check"] = self._live_citation_check(s["version"])
        s["rules"] = {"fingerprint": self.cp.rules_fingerprint, "synthetic": self.cp.rules_synthetic,
                      "points": len(self.cp.rules.points)} if self.cp else None
        return s

    def _live_citation_check(self, version: int) -> dict:
        """Каждая цитата и каждый номер пункта в действующих текстах черновиков сверяются с текущим rules.json."""
        if self.cp is None:
            return {"available": False}
        key = (version, self.cp.rules_fingerprint)
        if self._cite_cache and self._cite_cache[0] == key:
            return self._cite_cache[1]
        rows = self.store.revalidation_rows()
        bad = []
        for r in rows:
            missing = [c for c in r["cited"] if not self.cp.rules.exists(c)]
            refs_bad = [x.raw for x in verify.extract_refs(r["text"], self.cp.rules) if not x.exists]
            if missing or refs_bad:
                bad.append({"id": r["id"], "missing_cites": missing, "missing_refs_in_text": refs_bad})
        res = {"available": True, "checked": len(rows), "failed": len(bad), "failures": bad[:10],
               "rules_fingerprint": self.cp.rules_fingerprint,
               "scope": "действующий текст каждого сохранённого обращения, по текущему rules.json"}
        self._cite_cache = (key, res)
        return res

    def selfcheck(self) -> dict:
        r = selfcheck.run(self._require_cp())
        self.store.add_event(ACTOR, "quality.selfcheck", "quality", "selfcheck", None,
                             {"ran": r["ran"], "passed": r["passed"], "failed": r["failed"]})
        return r

    def metrics(self) -> dict:
        if self.metrics_json is None or not self.metrics_json.exists():
            return {"available": False, "hint": "метрик нет: выполните make eval"}
        m = json.loads(self.metrics_json.read_text(encoding="utf-8"))
        mt = self.metrics_json.stat().st_mtime
        m["available"] = True
        m["provenance"] = {
            "kind": "offline", "file": str(self.metrics_json.name), "file_modified": iso(mt),
            "population": "валидационная выгрузка кейса, 1000 обращений, не живой поток",
            "note": "Посчитано до независимого аудита 30.10.2026 и после исправлений не пересчитывалось. Категории и "
                    "приоритеты размечены по черновику таксономии организаторов, поэтому цифры ориентировочные. "
                    "Историческое измерение не гарантирует безопасность будущих обращений.",
            "models_now": bool(self.cp and self.cp.category_model.loaded)}
        return m

    # ------------------------------------------------------------------ шаблоны
    @staticmethod
    def template_key(c: dict) -> str:
        return f"{c['category']}:{c['cluster']}"

    def _load_summary(self) -> dict | None:
        if not self.templates_json.exists():
            return None
        return json.loads(self.templates_json.read_text(encoding="utf-8"))

    def _private_examples(self) -> dict[str, list]:
        if not self.private_templates or not self.private_templates.exists():
            return {}
        try:
            data = json.loads(self.private_templates.read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return {self.template_key(c): c.get("examples") or [] for c in data.get("clusters", []) if "category" in c}

    def template_safety(self, text: str) -> dict:
        """Проверка текста шаблона теми же кодовыми проверками, что и ответы, плюс совместимость с пайплайном."""
        cp = self._require_cp()
        v = verify.verify_text(text, cp.rules, allow_placeholders=True)
        holders = set(re.findall(r"\{([^{}]*)\}", text))
        unknown = sorted(h for h in holders if h not in KNOWN_PLACEHOLDERS)
        detected = lang_mod.detect(re.sub(r"\{[^{}]*\}", "", text), None)
        compat = {"known_placeholders": sorted(holders & KNOWN_PLACEHOLDERS), "unknown_placeholders": unknown,
                  "detected_lang": detected, "supported_lang": detected in ("ru", "uz", "kk", "en", "es", "pt"),
                  "integrated_in_pipeline": False}
        ok = v.ok and not unknown
        problems = [x.message for x in v.violations] + ([f"Неизвестные поля: {', '.join('{' + u + '}' for u in unknown)}"] if unknown else [])
        return {"ok": ok, "problems": problems, "cited": v.cited, "compat": compat,
                "note": "Утверждённый шаблон только сохраняется. В генерацию ответов он не подключён: для этого нужна "
                        "отдельная доработка пайплайна и повторная оценка."}

    def templates(self, only_candidates: bool = False) -> dict:
        summary = self._load_summary()
        if summary is None:
            return {"available": False, "hint": "сводки нет: выполните make suggest-templates", "totals": {}, "clusters": [],
                    "markdown": ""}
        reviews = self.store.template_reviews()
        examples = self._private_examples()
        live = self.store.intent_counts()
        for c in summary["clusters"]:
            key = self.template_key(c)
            c["key"] = key
            c["review"] = reviews.get(key) or {"status": "pending", "template_final": c.get("template"), "rev": 0}
            c["live_matches"] = live.get(c.get("intent"), 0)
            ex = examples.get(key)
            c["examples"] = ex if ex else None
        if only_candidates:
            summary["clusters"] = [c for c in summary["clusters"] if c.get("gap")]
        mt = self.templates_json.stat().st_mtime
        summary["available"] = True
        summary["provenance"] = {
            "kind": "offline analysis", "file": self.templates_json.name, "file_modified": iso(mt),
            "population": f"{summary.get('meta', {}).get('tickets', 0)} обращений train, кластеризация scripts/suggest_templates.py",
            "examples_available": bool(examples),
            "examples_note": None if examples else "Примеров обращений нет: reports/private/template_suggestions.json отсутствует. "
                                                   "Тексты игроков не публикуются и лежат только у владельца данных.",
            "live_note": "«Живые совпадения» считаются по сценарию ответа среди обращений, сохранённых в Sentra."}
        summary["review_counts"] = {s: sum(1 for c in summary["clusters"] if c["review"]["status"] == s)
                                    for s in ("pending", "approved", "rejected")}
        summary["markdown"] = self.templates_md.read_text(encoding="utf-8") if self.templates_md and self.templates_md.exists() else ""
        return summary

    def review_template(self, key: str, body: dict, *, actor: str = ACTOR) -> dict:
        summary = self._load_summary()
        if summary is None:
            raise ApiError(404, "not_found", "Нет сводки по шаблонам")
        cluster = next((c for c in summary["clusters"] if self.template_key(c) == key), None)
        if cluster is None:
            raise ApiError(404, "not_found", "Нет такого кластера")
        action = body.get("action")
        if action not in ("approve", "reject", "edit", "reset"):
            raise ApiError(422, "invalid_input", "Действие: approve, reject, edit или reset", field="action")
        cur = self.store.template_reviews().get(key)
        original = cluster.get("template") or ""
        text = body.get("template")
        if text is None:
            text = cur["template_final"] if cur else original
        if not isinstance(text, str) or len(text) > 2000:
            raise ApiError(422, "invalid_input", "Текст шаблона до 2000 символов", field="template")
        note = _s(body.get("note"), 1000, "note")
        expected = body.get("expected_rev")
        if action == "reset":
            status, text = "pending", original
        elif action == "reject":
            status = "rejected"
        else:
            status = "approved" if action == "approve" else (cur["status"] if cur else "pending")
        safety = None
        if action in ("approve", "edit"):
            safety = self.template_safety(text)
            if action == "approve" and not safety["ok"]:
                self.store.add_event(actor, "template.blocked", "template", key, None, {"problems": safety["problems"]})
                raise ApiError(422, "template_rejected", "Шаблон не прошёл проверку безопасности и не утверждён",
                               problems=safety["problems"], safety=safety)
            if action == "edit" and text.strip() == (cur["template_final"] if cur else original).strip():
                raise ApiError(422, "no_change", "Текст не изменился")
            if action == "edit" and status == "approved":
                status = "pending"      # изменённый текст нужно утвердить заново
        try:
            return self.store.put_template_review(key, category=cluster["category"], cluster=int(cluster["cluster"]),
                                                  status=status, template_original=original, template_final=text,
                                                  safety=safety, note=note, actor=actor,
                                                  expected_rev=int(expected) if expected is not None else None)
        except Conflict as c:
            raise ApiError(409, "conflict", "Решение по шаблону уже изменилось: обновите страницу", rev=c.actual)

    # ------------------------------------------------------------------ экспорт
    def export_jsonl(self) -> str:
        out = []
        for s in self.store.list_tickets(limit=100000)["items"]:
            t = self.store.get_ticket(s["id"])
            out.append(json.dumps({
                "id": t["id"], "kind": t["kind"], "status": t["status"], "created_at": t["created_at"], "text": t["text"],
                "triage": {k: v for k, v in t["response"].items() if not k.startswith("_")},
                "original_draft": t["draft_original"]["text"], "final_draft": t["draft"]["text"],
                "final_category": t["category"], "final_priority": t["priority"],
                "decisions": t["decisions"], "duplicate_of": (t["duplicate"] or {}).get("root_id")},
                ensure_ascii=False))
        return "\n".join(out) + ("\n" if out else "")

