"""HTTP-сервис: POST /triage по контракту кейса, плюс очередь для интерфейса админа.

Запуск: make serve  (uvicorn copilot.api:app --port 8000)
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .llm import from_env as llm_from_env
from .pipeline import Copilot

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_PATH = Path(os.environ.get("COPILOT_FEEDBACK", ROOT / "reports/private/feedback.jsonl"))


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


class Feedback(BaseModel):
    queue_id: str
    action: str = Field(pattern="^(send|edit|escalate)$")
    final_text: str | None = None
    final_category: str | None = None
    final_priority: str | None = None
    comment: str | None = None


app = FastAPI(title="Grand Mobile Support Copilot", version="1.0")
copilot = Copilot(llm=llm_from_env())
QUEUE: deque = deque(maxlen=500)
_lock = threading.Lock()


def _public(resp: dict, debug: bool) -> dict:
    if debug:
        return resp
    return {k: v for k, v in resp.items() if not k.startswith("_")}


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": copilot.category_model.loaded,
            "verdict_model_loaded": copilot.verdict_model is not None, "llm": copilot.llm is not None,
            "rules": len(copilot.rules.points)}


@app.post("/triage")
def triage(req: TriageRequest, debug: bool = False, enqueue: bool = False):
    payload = req.model_dump()
    payload["messages"] = [m for m in payload["messages"] if m.get("role") != "admin"]
    if not any((m.get("text") or "").strip() or m.get("attachments") for m in payload["messages"]):
        raise HTTPException(422, "в обращении нет сообщений игрока")
    resp = copilot.triage(payload)
    if enqueue:
        qid = uuid.uuid4().hex[:12]
        with _lock:
            QUEUE.appendleft({"queue_id": qid, "received": time.time(), "request": payload, "response": resp,
                              "status": "new"})
        resp = dict(resp, queue_id=qid)
        return JSONResponse(resp)
    return _public(resp, debug)


@app.get("/queue")
def queue(status: str | None = None):
    with _lock:
        items = [q for q in QUEUE if status is None or q["status"] == status]
    order = {"p0": 0, "p1": 1, "p2": 2, "p3": 3}
    items.sort(key=lambda q: (order.get(q["response"]["priority"], 9), -q["received"]))
    return items


@app.post("/feedback")
def feedback(fb: Feedback):
    with _lock:
        item = next((q for q in QUEUE if q["queue_id"] == fb.queue_id), None)
        if item is None:
            raise HTTPException(404, "нет такого обращения в очереди")
        item["status"] = {"send": "sent", "edit": "sent", "escalate": "escalated"}[fb.action]
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), "queue_id": fb.queue_id, "action": fb.action,
              "draft": item["response"]["draft_reply"], "category": item["response"]["category"],
              "priority": item["response"]["priority"], "final_text": fb.final_text,
              "final_category": fb.final_category, "final_priority": fb.final_priority, "comment": fb.comment,
              "intent": item["response"].get("_meta", {}).get("intent")}
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "status": item["status"]}


@app.get("/rules")
def rules_lookup(cite: list[str] = Query(default=[])):
    out = {}
    for c in cite or []:
        p = copilot.rules.get(c)
        if p:
            out[c] = {"section": p.section_name, "ref": p.ref, "text": p.text}
    return out


@app.get("/")
def admin_ui():
    return FileResponse(ROOT / "admin_ui/index.html")
