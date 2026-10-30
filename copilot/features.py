"""Текст для классификатора: сообщение игрока + поле «пункт правил» + теги сигналов."""
from __future__ import annotations

from .signals import Signals
from .textnorm import for_matching


def model_text(t, sig: Signals) -> str:
    tags = " ".join(f"__{x}" for x in sorted(sig.topics))
    refs = " ".join(f"__ref_{r.replace(' ', '_')}" for r in sig.rule_refs)
    flags = []
    if sig.has_url:
        flags.append("__url")
    if sig.content_free:
        flags.append("__empty")
    if sig.player_id:
        flags.append("__pid")
    if sig.words <= 2:
        flags.append("__short")
    raw = for_matching(t.player_text)[:600]
    rr = for_matching(t.rule_refs_raw or "")[:60]
    return f"{raw} __rr {rr} {tags} {refs} {' '.join(flags)}"
