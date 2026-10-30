"""Дубли и спам.

Дубль: тот же заявитель, тот же нарушитель или то же содержание, меньше часа
назад. В данных это частый случай: «1 игрок, 1 проблема, 5 тикетов за час».
Хранилище в памяти процесса (для make predict тикеты идут по времени).
"""
from __future__ import annotations

import re
import threading
from collections import Counter, deque
from datetime import datetime, timedelta

from .textnorm import for_matching

WINDOW = timedelta(hours=1)


def _shingles(text: str) -> set[str]:
    t = re.sub(r"\W+", " ", for_matching(text)).strip()
    return {t[i:i + 4] for i in range(max(1, len(t) - 3))}


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def is_spam(text: str) -> bool:
    words = re.findall(r"[^\W\d_]{2,}", for_matching(text))
    if len(words) >= 10:
        top = Counter(words).most_common(1)[0][1]
        if top / len(words) >= 0.3:
            return True
    letters = re.sub(r"[^a-zа-яё]", "", for_matching(text))
    if len(letters) >= 20 and " " not in text.strip():
        return True
    if len(letters) >= 25:
        vowels = sum(1 for ch in letters if ch in "аеиоуыэюяaeiouy")
        if vowels / len(letters) < 0.15:
            return True
    return False


class DedupStore:
    def __init__(self, maxlen: int = 50000):
        self._items: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def check_and_add(self, *, reporter: str | None, reported: str | None, text: str, kind: str,
                      created_at: str | None, category: str) -> str | None:
        """Возвращает причину, если это дубль, и запоминает тикет."""
        if not reporter:
            return None
        now = _ts(created_at) or datetime.utcnow()
        sh = _shingles(text)
        reason = None
        with self._lock:
            for it in reversed(self._items):
                if now - it["ts"] > WINDOW:
                    break
                if it["reporter"] != reporter or it["kind"] != kind or it["ts"] > now:
                    continue
                if reported and it["reported"] == reported:
                    reason = "тот же заявитель и тот же нарушитель менее часа назад"
                    break
                inter = len(sh & it["sh"]) / max(1, len(sh | it["sh"]))
                if inter >= 0.7 or (it["category"] == category and inter >= 0.4):
                    reason = "тот же заявитель с тем же текстом менее часа назад"
                    break
            self._items.append({"reporter": reporter, "reported": reported, "ts": now, "sh": sh, "kind": kind,
                                "category": category})
        return reason
