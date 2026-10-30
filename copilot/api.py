"""HTTP-сервис: POST /triage по контракту кейса и рабочее место модератора Sentra.

Запуск: make serve  (uvicorn copilot.api:app --port 8000)

Что где хранится: обращения, решения, версии черновиков и журнал лежат в SQLite (COPILOT_DB, по умолчанию var/sentra.db).
Без rules.json сервис стартует и показывает диагностику, а триаж отвечает 503: результаты не подменяются.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import datacheck, taxonomy, verify
from .llm import from_env as llm_from_env
from .pipeline import Copilot
from .service import CLOSE_REASONS, ESCALATION_REASONS, ApiError, TicketService
from .store import Store, StorageError
from .ticket import has_player_content

log = logging.getLogger("copilot")
ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("COPILOT_DB", ROOT / "var/sentra.db"))
TEMPLATES_JSON = Path(os.environ.get("COPILOT_TEMPLATES", ROOT / "reports/template_suggestions_summary.json"))
TEMPLATES_MD = TEMPLATES_JSON.with_suffix(".md")
PRIVATE_TEMPLATES = Path(os.environ.get("COPILOT_TEMPLATES_PRIVATE", ROOT / "reports/private/template_suggestions.json"))
METRICS_JSON = Path(os.environ.get("COPILOT_METRICS", ROOT / "reports/metrics.json"))
UI_DIR = ROOT / "admin_ui"

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")


class Message(BaseModel):
    role: str = "player"
    text: str = ""
    attachments: int | None = 0
    ts: str | None = None


class TriageRequest(BaseModel):
    kind: str = Field("report", pattern="^(complaint|report)$")
    messages: list[Message]
    # необязательные поля из выгрузки: если есть, улучшают дедупликацию и язык
    ticket_id: str | None = None
    created_at: str | None = None
    region: str | None = None
    server_lang: str | None = None
    reporter_hash: str | None = None
    reported_hash: str | None = None
    reported_nick: str | None = None
    rule_refs_raw: str | None = None
    images_count: int | None = None


app = FastAPI(title="Grand Mobile Support Copilot", version="2.0")


# ---------------------------------------------------------------- запуск
def _boot():
    copilot, boot = None, []
    data_dir = Path(os.environ.get("COPILOT_DATA", ROOT / "data"))
    models_dir = Path(os.environ.get("COPILOT_MODELS", ROOT / "models"))
    rules = data_dir / "rules.json"
    if not rules.exists():
        boot.append({"code": "rules_missing", "level": "error",
                     "text": f"Не найден {rules}: положите выдачу кейса в data/ или задайте COPILOT_DATA. Триаж недоступен."})
    else:
        bad = datacheck.check_rules(rules)
        if bad:
            boot.append({"code": "rules_invalid", "level": "error",
                         "text": "rules.json не прошёл проверку структуры: " + "; ".join(bad[:3]) + ". Триаж недоступен."})
        else:
            try:
                copilot = Copilot(data_dir=data_dir, models_dir=models_dir, llm=llm_from_env())
            except Exception as e:  # повреждённая модель и подобное: сервис остаётся живым, причина видна в /health
                log.exception("не удалось запустить пайплайн")
                boot.append({"code": "pipeline_failed", "level": "error",
                             "text": f"Пайплайн не запустился: {type(e).__name__}: {e}. Триаж недоступен."})
    store, svc, storage_error = None, None, None
    try:
        store = Store(DB_PATH)
        svc = TicketService(copilot, store, templates_json=TEMPLATES_JSON, templates_md=TEMPLATES_MD,
                            private_templates=PRIVATE_TEMPLATES, metrics_json=METRICS_JSON)
    except StorageError as e:
        storage_error = str(e)
        boot.append({"code": "storage_failed", "level": "error", "text": storage_error})
    return copilot, store, svc, boot, storage_error, data_dir, models_dir


copilot, STORE, SVC, BOOT_PROBLEMS, STORAGE_ERROR, DATA_DIR, MODELS_DIR = _boot()
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"      # браузер каждый раз сверяет версию, старый JS не остаётся
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return JSONResponse(e.body(), status_code=e.status)


def _svc() -> TicketService:
    if SVC is None:
        raise ApiError(503, "storage_unavailable", STORAGE_ERROR or "Хранилище недоступно")
    return SVC


def _public(resp: dict, debug: bool) -> dict:
    if debug:
        return resp
    return {k: v for k, v in resp.items() if not k.startswith("_")}


# ---------------------------------------------------------------- состояние
@app.get("/health")
def health():
    """`status: ok` значит только «процесс жив». Готовность и режим показывают `ready` и `mode`."""
    diag = copilot.diagnostics() if copilot else None
    problems = list(BOOT_PROBLEMS) + (diag["problems"] if diag else [])
    if copilot is None:
        mode = "unavailable"
    else:
        mode = diag["mode"]
    storage = {"ok": STORE is not None, "path": str(DB_PATH), "error": STORAGE_ERROR}
    if STORE is not None:
        storage.update(schema_version=STORE.schema_version(), tickets=STORE.count())
    llm_on = bool(copilot and copilot.llm is not None)
    if llm_on:
        problems.append({"code": "llm_external", "level": "info",
                         "text": "LLM включена: тексты обращений отправляются во внешний API, настроенный в COPILOT_LLM_*."})
    return {
        "status": "ok", "ready": bool(copilot and SVC), "mode": mode,
        "model_loaded": bool(copilot and copilot.category_model.loaded),
        "verdict_model_loaded": bool(copilot and copilot.verdict_model is not None),
        "llm": llm_on, "rules": len(copilot.rules.points) if copilot else 0,
        "rules_synthetic": bool(copilot and copilot.rules_synthetic),
        "rules_source": diag["rules_source"] if diag else None,
        "problems": problems, "storage": storage,
        "files": datacheck.files_status(DATA_DIR, MODELS_DIR),
        "missing_files": [f["path"] for f in datacheck.files_status(DATA_DIR, MODELS_DIR) if not f["present"]],
    }


@app.get("/meta")
def meta():
    return {"escalation_reasons": ESCALATION_REASONS, "close_reasons": CLOSE_REASONS,
            "categories": {"complaint": taxonomy.COMPLAINT_CATS, "report": taxonomy.REPORT_CATS},
            "priorities": taxonomy.PRIORITIES, "category_labels": taxonomy.CATEGORY_LABELS}


@app.get("/stats")
def stats():
    return _svc().stats()


@app.get("/metrics")
def metrics():
    """Метрики последней оценки на валидации (reports/metrics.json): исторические, не живые."""
    return _svc().metrics() if SVC else {"available": False, "hint": "хранилище недоступно"}


@app.post("/verify")
def verify_draft(body: dict):
    """Проверка текста ответа кодом по rules.json: пункты и обещания. Ничего не сохраняет."""
    if copilot is None:
        raise ApiError(503, "triage_unavailable", "Проверка недоступна: не загружены правила, см. /health")
    text = body.get("text")
    if not isinstance(text, str):
        raise ApiError(422, "invalid_input", "Нужен текст", field="text")
    return verify.verify_text(text, copilot.rules).as_dict()


@app.post("/quality/selfcheck")
def quality_selfcheck():
    return _svc().selfcheck()


# ---------------------------------------------------------------- триаж (контракт кейса)
@app.post("/triage")
def triage(req: TriageRequest, debug: bool = False, enqueue: bool = False):
    payload = req.model_dump()
    payload["messages"] = [m for m in payload["messages"] if m.get("role") != "admin"]
    if not has_player_content(payload):
        raise HTTPException(422, "в обращении нет сообщений игрока")
    if copilot is None:
        raise ApiError(503, "triage_unavailable", "Триаж недоступен: не загружены правила, см. /health",
                       problems=BOOT_PROBLEMS)
    if enqueue:
        ticket, _ = _svc().create_from_payload(payload, source="api")
        resp = ticket["response"]
        return JSONResponse(dict(_public(resp, debug), queue_id=ticket["id"], ticket_id=ticket["id"]))
    return _public(copilot.triage(payload), debug)


# ---------------------------------------------------------------- обращения
@app.post("/tickets")
def create_ticket(body: dict, idempotency_key: str | None = Header(default=None)):
    ticket, created = _svc().create_from_form(body, idem_key=idempotency_key)
    return JSONResponse({"created": created, "ticket": ticket}, status_code=201 if created else 200)


@app.post("/tickets/import")
async def import_tickets(request: Request):
    body = await request.body()
    return await run_in_threadpool(_svc().import_jsonl, body)      # долгий разбор не блокирует остальные запросы


@app.get("/tickets")
def list_tickets(status: str | None = None, priority: str | None = None, q: str | None = None, kind: str | None = None,
                 flagged: bool = False, limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0)):
    statuses = [s for s in (status or "").split(",") if s] or None
    for s in statuses or []:
        if s not in ("new", "approved", "escalated", "closed"):
            raise ApiError(422, "invalid_input", "Неизвестный статус", field="status")
    if priority and priority not in taxonomy.PRIORITIES:
        raise ApiError(422, "invalid_input", "Неизвестный приоритет", field="priority")
    if kind and kind not in ("complaint", "report"):
        raise ApiError(422, "invalid_input", "Неизвестный тип", field="kind")
    by_label = [c for c, label in taxonomy.CATEGORY_LABELS.items() if q and q.strip().casefold() in label.casefold()]
    return _svc().store.list_tickets(statuses=statuses, priority=priority, q=q, kind=kind, flagged=flagged or None,
                                     limit=limit, offset=offset, q_categories=by_label)


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    t = _svc().store.get_ticket(ticket_id)
    if t is None:
        raise ApiError(404, "not_found", "Нет такого обращения")
    return t


@app.post("/tickets/{ticket_id}/decision")
def decide(ticket_id: str, body: dict):
    return _svc().decide(ticket_id, body)


@app.get("/duplicates")
def duplicates():
    return _svc().store.duplicates()


@app.get("/export/tickets.jsonl")
def export_tickets():
    return PlainTextResponse(_svc().export_jsonl(), media_type="application/x-ndjson")


@app.get("/rules")
def rules_lookup(cite: list[str] = Query(default=[])):
    out = {}
    if copilot is None:
        return out
    for c in cite or []:
        p = copilot.rules.get(c)
        if p:
            out[c] = {"section": p.section_name, "ref": p.ref, "text": p.text}
    return out


# ---------------------------------------------------------------- шаблоны
@app.get("/templates")
def templates(only_candidates: bool = True):
    """Кандидаты в новые шаблоны (оффлайн-анализ scripts/suggest_templates.py) и решения модератора по ним."""
    return _svc().templates(only_candidates=only_candidates)


@app.post("/templates/{key:path}/review")
def review_template(key: str, body: dict):
    return _svc().review_template(key, body)


# ---------------------------------------------------------------- интерфейс
@app.get("/")
def admin_ui():
    return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(UI_DIR / "assets/favicon.svg", media_type="image/svg+xml")
