"""Приведение входа к одному виду: запрос POST /triage и строка tickets.jsonl."""
from __future__ import annotations

from dataclasses import dataclass, field

from .textnorm import clean


@dataclass
class Ticket:
    kind: str
    player_text: str
    accused_text: str = ""
    ticket_id: str | None = None
    created_at: str | None = None
    region: str | None = None
    server_lang: str | None = None
    reporter_hash: str | None = None
    reported_hash: str | None = None
    reported_nick: str | None = None
    rule_refs_raw: str | None = None
    images: int = 0
    raw: dict = field(default_factory=dict)


def from_dict(d: dict) -> Ticket:
    """Ответы админа во входе игнорируются: это то, что мы предсказываем."""
    region = d.get("region")
    msgs = d.get("messages") or []
    player = [m.get("text") or "" for m in msgs if m.get("role", "player") == "player"]
    accused = [m.get("text") or "" for m in msgs if m.get("role") == "reported_player"]
    attachments = sum(int(m.get("attachments") or 0) for m in msgs if m.get("role", "player") == "player")
    images = d.get("images_count")
    if images is None:
        images = attachments
    kind = d.get("kind") or "report"
    if kind not in ("complaint", "report"):
        kind = "report"
    return Ticket(
        kind=kind,
        player_text=clean("\n".join(player), region),
        accused_text=clean("\n".join(accused), region),
        ticket_id=d.get("ticket_id"),
        created_at=d.get("created_at") or (msgs[0].get("ts") if msgs else None),
        region=region,
        server_lang=d.get("server_lang"),
        reporter_hash=d.get("reporter_hash"),
        reported_hash=d.get("reported_hash"),
        reported_nick=d.get("reported_nick"),
        rule_refs_raw=d.get("rule_refs_raw"),
        images=int(images or 0),
        raw=d,
    )
