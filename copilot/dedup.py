"""Дубли и спам.

Дубль: тот же заявитель, тот же нарушитель или то же содержание, меньше часа
назад. В данных это частый случай: «1 игрок, 1 проблема, 5 тикетов за час».
Хранилище в памяти процесса, по заявителям: результат не зависит от порядка добавления. Время с часовым поясом
приводится к UTC, время без пояса считается UTC.
"""
from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .textnorm import for_matching

WINDOW = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _shingles(text: str) -> set[str]:
    t = re.sub(r"\W+", " ", for_matching(text)).strip()
    return {t[i:i + 4] for i in range(max(1, len(t) - 3))}


def _ts(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_spam(text: str) -> bool:
    words = re.findall(r"[^\W\d_]{2,}", for_matching(text))
    if len(words) >= 10:
        top = Counter(words).most_common(1)[0][1]
        if top / len(words) >= 0.3:
            return True
    letters = re.sub(r"[^a-zа-яё]", "", for_matching(text))
    # длинная строка без пробелов - мусор, но не ник вида Имя_Фамилия, который игроки присылают сами по себе
    if len(letters) >= 20 and " " not in text.strip() and "_" not in text:
        return True
    if len(letters) >= 25:
        vowels = sum(1 for ch in letters if ch in "аеиоуыэюяaeiouy")
        if vowels / len(letters) < 0.15:
            return True
    return False


REASON_SAME_REPORTED = "тот же заявитель и тот же нарушитель менее часа назад"
REASON_SIMILAR_TEXT = "тот же заявитель с тем же текстом менее часа назад"


@dataclass
class DedupMatch:
    """Чем именно обращение совпало с более ранним. Все числа считает этот модуль, ничего не оценивается на глаз."""
    reason: str
    kind: str                    # same_reported | similar_text
    original_ref: str | None     # идентификатор более раннего обращения, если его передали при добавлении
    same_reporter: bool
    same_reported: bool
    text_overlap: float          # коэффициент Жаккара по 4-граммам текста, 0..1
    category_equal: bool
    delta_seconds: float
    window_seconds: int = int(WINDOW.total_seconds())

    def as_dict(self) -> dict:
        return {"reason": self.reason, "kind": self.kind, "original_ref": self.original_ref,
                "same_reporter": self.same_reporter, "same_reported": self.same_reported,
                "text_overlap": round(self.text_overlap, 3), "category_equal": self.category_equal,
                "delta_seconds": round(self.delta_seconds, 1), "window_seconds": self.window_seconds}


MAX_PER_REPORTER = 200
MAX_REPORTERS = 50000


class DedupStore:
    def __init__(self, maxlen: int = MAX_REPORTERS):
        self._by_reporter: dict[str, list] = {}
        self._maxlen = maxlen
        self._lock = threading.Lock()

    def _push(self, item: dict) -> None:
        lst = self._by_reporter.get(item["reporter"])
        if lst is None:
            if len(self._by_reporter) >= self._maxlen:
                self._by_reporter.pop(next(iter(self._by_reporter)))     # вытесняется самый давний заявитель
            lst = self._by_reporter[item["reporter"]] = []
        lst.append(item)
        if len(lst) > MAX_PER_REPORTER:
            del lst[0]

    def check_and_add(self, *, reporter: str | None, reported: str | None, text: str, kind: str,
                      created_at: str | None, category: str, ref: str | None = None) -> str | None:
        """Возвращает причину, если это дубль, и запоминает тикет."""
        m = self.match_and_add(reporter=reporter, reported=reported, text=text, kind=kind,
                               created_at=created_at, category=category, ref=ref)
        return m.reason if m else None

    def match_and_add(self, *, reporter: str | None, reported: str | None, text: str, kind: str,
                      created_at: str | None, category: str, ref: str | None = None) -> DedupMatch | None:
        """То же, что check_and_add, но с подробностями совпадения. `ref` запоминается для ссылки на оригинал."""
        if not reporter:
            return None
        now = _ts(created_at) or _utcnow()
        sh = _shingles(text)
        best: tuple | None = None       # (время, совпадение): оригинал это самое позднее подходящее обращение
        with self._lock:
            for it in reversed(self._by_reporter.get(reporter, ())):
                if it["kind"] != kind or it["ts"] > now or now - it["ts"] > WINDOW:
                    continue
                if best is not None and it["ts"] <= best[0]:
                    continue
                inter = len(sh & it["sh"]) / max(1, len(sh | it["sh"]))
                same_reported = bool(reported and it["reported"] == reported)
                cat_eq = it["category"] == category
                if same_reported:
                    reason, mk = REASON_SAME_REPORTED, "same_reported"
                elif inter >= 0.7 or (cat_eq and inter >= 0.4):
                    reason, mk = REASON_SIMILAR_TEXT, "similar_text"
                else:
                    continue
                best = (it["ts"], DedupMatch(reason=reason, kind=mk, original_ref=it.get("ref"), same_reporter=True,
                                             same_reported=same_reported, text_overlap=inter, category_equal=cat_eq,
                                             delta_seconds=(now - it["ts"]).total_seconds()))
            self._push({"reporter": reporter, "reported": reported, "ts": now, "sh": sh, "kind": kind,
                        "category": category, "ref": ref})
        return best[1] if best else None

    def discard(self, ref: str) -> None:
        """Убрать обращение из памяти, если его не удалось сохранить: несуществующее обращение не должно быть оригиналом."""
        with self._lock:
            for lst in self._by_reporter.values():
                lst[:] = [it for it in lst if it.get("ref") != ref]

    def restore(self, rows: list[dict]) -> int:
        """Восстановить память после перезапуска из сохранённых обращений.

        Каждая строка: reporter, reported, text, kind, category, ts (ISO), ref."""
        n = 0
        with self._lock:
            for r in rows:
                if not r.get("reporter"):
                    continue
                self._push({"reporter": r["reporter"], "reported": r.get("reported"), "ts": _ts(r.get("ts")) or _utcnow(),
                            "sh": _shingles(r.get("text") or ""), "kind": r["kind"], "category": r.get("category"),
                            "ref": r.get("ref")})
                n += 1
        return n
