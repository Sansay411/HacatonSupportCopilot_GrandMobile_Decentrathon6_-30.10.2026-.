"""Приведение входа к одному виду: запрос POST /triage и строка tickets.jsonl."""
from __future__ import annotations

import re
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


def _to_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


_NICK_OK =re.compile(r"[\w.\-]{2,32}", re.UNICODE)


def safe_nick(nick) -> str | None:
    """Ник попадает в текст ответа, поэтому принимаем только ник, а не произвольную строку."""
    if not isinstance(nick, str):
        return None
    nick = nick.strip()
    return nick if _NICK_OK.fullmatch(nick) else None


def has_player_content(d: dict) -> bool:
    """Есть ли в обращении текст или вложения игрока: те же роли, что использует from_dict."""
    for m in d.get("messages") or []:
        if not isinstance(m, dict) or m.get("role", "player") != "player":
            continue
        try:
            att = int(m.get("attachments") or 0)
        except (TypeError, ValueError):
            att = 0
        if (m.get("text") or "").strip() or att > 0:
            return True
    return False


def from_dict(d: dict) -> Ticket:
    """Ответы админа во входе игнорируются: это то, что мы предсказываем."""
    region = d.get("region")
    msgs = [m for m in (d.get("messages") or []) if isinstance(m, dict)]
    player = [str(m.get("text") or "") for m in msgs if m.get("role", "player") == "player"]
    accused = [str(m.get("text") or "") for m in msgs if m.get("role") == "reported_player"]
    attachments = sum(max(0, _to_int(m.get("attachments"))) for m in msgs if m.get("role", "player") == "player")
    images = d.get("images_count")
    if images is None:
        images = attachments
    images = max(0, _to_int(images))
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
        reported_nick=safe_nick(d.get("reported_nick")),
        rule_refs_raw=d.get("rule_refs_raw"),
        images=images,
        raw=d,
    )
