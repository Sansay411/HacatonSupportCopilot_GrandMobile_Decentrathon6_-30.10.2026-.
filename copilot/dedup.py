"""Дубли и спам.

Дубль: тот же заявитель, тот же нарушитель или то же содержание, меньше часа
назад. В данных это частый случай: «1 игрок, 1 проблема, 5 тикетов за час».
Хранилище в памяти процесса, по заявителям: результат не зависит от порядка добавления. Время с часовым поясом
приводится к UTC, время без пояса считается UTC.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .textnorm import for_matching

WINDOW = timedelta(hours=1)

_NEG_TOKENS = re.compile(
    r"\b(?:не|ни|нет|нету|без|никто|никого|никогда|not|no|don't|dont|емес|жоқ|emas|yo'q|yoq)\b",
    re.I,
)
_PROBLEM_GROUPS: dict[str, re.Pattern] = {
    "scam": re.compile(r"\bскам|\bscam|\bskam|обман|кинул|развел|развёл|мошен|украл|не вернул|не отдал|aldab|aldadi|алдап", re.I),
    "threat": re.compile(r"угрож|угроз|найду теб|вычисл|\bдеанон|\bдокс|\bсват|реальн\w* жизн|\birl\b|tahdid|шын өмірде", re.I),
    "insult": re.compile(r"\bоск|\bosk|оскорб|обзыва|обозвал|\bмат|родн|мамк|балағат|сөкт|haqorat|so'?k", re.I),
    "cheat": re.compile(r"\bсофт|\bsoft|\bчит|\bchit|\bcheat|аим|\baim|\bвх\b|\bwh\b|спидхак|багоюз|телепорт", re.I),
    "dm": re.compile(r"\bдм\b|\bdm\b|дмит|\bдб\b|\bdb\b|\bтк\b|\btk\b|\bск\b|\bsk\b|убил|убива|застрелил|стреля|таран|сбил|задавил|өлтір|o'?ldir", re.I),
    "payment": re.compile(r"\bдонат|задонат|оплатил|платеж|платёж|списал|төлем|to'?lov|\bpaid\b|\bpayment", re.I),
    "account": re.compile(r"взлом|угнал|увели|пароль|привязк|аккаунт.*бұз|hisob.*buz|vzlom", re.I),
}


def _problem_topics(text: str) -> set[str]:
    m = for_matching(text)
    return {name for name, rx in _PROBLEM_GROUPS.items() if rx.search(m)}


def _has_negation(text: str) -> bool:
    return bool(_NEG_TOKENS.search(for_matching(text)))


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
REASON_ID_CONFLICT = "тот же ticket_id уже приходил с другим содержимым (другой текст, заявитель или тип): проверьте обращение вручную"


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
    original_mandatory_human: bool = False

    def as_dict(self) -> dict:
        return {"reason": self.reason, "kind": self.kind, "original_ref": self.original_ref,
                "same_reporter": self.same_reporter, "same_reported": self.same_reported,
                "text_overlap": round(self.text_overlap, 3), "category_equal": self.category_equal,
                "delta_seconds": round(self.delta_seconds, 1), "window_seconds": self.window_seconds}


MAX_PER_REPORTER = 200
MAX_REPORTERS = 50000
MAX_TICKET_IDS = 200000


class DedupStore:
    def __init__(self, maxlen: int = MAX_REPORTERS):
        self._by_reporter: dict[str, list] = {}
        self._maxlen = maxlen
        self._lock = threading.Lock()
        # ticket_id -> отпечатки содержимого, с которыми он приходил: нужны, чтобы заметить один id с разным содержимым
        self._tids: OrderedDict[str, set] = OrderedDict()

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
                      created_at: str | None, category: str, ref: str | None = None,
                      mandatory_human: bool = False) -> str | None:
        """Возвращает причину, если это дубль, и запоминает тикет."""
        m = self.match_and_add(reporter=reporter, reported=reported, text=text, kind=kind,
                               created_at=created_at, category=category, ref=ref,
                               mandatory_human=mandatory_human)
        return m.reason if m else None

    def match_and_add(self, *, reporter: str | None, reported: str | None, text: str, kind: str,
                      created_at: str | None, category: str, ref: str | None = None,
                      mandatory_human: bool = False, ticket_id: str | None = None,
                      notes: list[str] | None = None) -> DedupMatch | None:
        """То же, что check_and_add, но с подробностями совпадения. `ref` запоминается для ссылки на оригинал.

        `ticket_id` нужен для повторной отправки того же обращения (прогрев, повторный прогон, ретрай клиента):
        тот же идентификатор с тем же текстом, заявителем и типом возвращает прежний результат и не считается дублем
        самого себя. Тот же идентификатор с другим содержимым это не повтор и не дубль: обращение разбирается как новое,
        а в `notes` (если передан список) добавляется REASON_ID_CONFLICT, чтобы вызывающий отправил его человеку."""
        if not reporter:
            return None
        now = _ts(created_at) or _utcnow()
        sh = _shingles(text)
        has_neg = _has_negation(text)
        prob_topics = _problem_topics(text)
        fingerprint = (reporter, kind, hash(frozenset(sh)))
        best: tuple | None = None       # (время, совпадение): оригинал это самое позднее подходящее обращение
        with self._lock:
            if ticket_id:
                seen = self._tids.get(ticket_id)
                if seen is not None and fingerprint not in seen and notes is not None:
                    notes.append(REASON_ID_CONFLICT)
                for it in self._by_reporter.get(reporter, ()):
                    if it.get("tid") == ticket_id and it["kind"] == kind and it["sh"] == sh:
                        return it.get("result")
            for it in reversed(self._by_reporter.get(reporter, ())):
                if it["kind"] != kind or it["ts"] > now or now - it["ts"] > WINDOW:
                    continue
                if ticket_id and it.get("tid") == ticket_id:
                    continue            # тот же идентификатор: это то же обращение с изменённым содержимым, а не его дубль
                if best is not None and it["ts"] <= best[0]:
                    continue
                # если в обоих обращениях явно указаны РАЗНЫЕ нарушители, это разные жалобы, а не дубль
                if reported and it.get("reported") and reported != it.get("reported"):
                    continue
                inter = len(sh & it["sh"]) / max(1, len(sh | it["sh"]))
                same_reported = bool(reported and it["reported"] == reported)
                cat_eq = it["category"] == category
                it_topics = it.get("topics") or set()
                disjoint_problems = bool(prob_topics and it_topics and not (prob_topics & it_topics))
                if same_reported:
                    # один и тот же нарушитель, но явно разные виды нарушений («украл машину» vs «угрожает в реале»)
                    if disjoint_problems and inter < 0.5:
                        continue
                    reason, mk = REASON_SAME_REPORTED, "same_reported"
                elif inter >= 0.7 or (cat_eq and inter >= 0.4):
                    # утверждение нарушения и его отрицание («оскорбил» vs «не оскорбил») не склеиваем
                    if has_neg != it.get("has_neg", False):
                        continue
                    if disjoint_problems and inter < 0.75:
                        continue
                    reason, mk = REASON_SIMILAR_TEXT, "similar_text"
                else:
                    continue
                best = (it["ts"], DedupMatch(
                    reason=reason, kind=mk, original_ref=it.get("ref"), same_reporter=True,
                    same_reported=same_reported, text_overlap=inter, category_equal=cat_eq,
                    delta_seconds=(now - it["ts"]).total_seconds(),
                    original_mandatory_human=bool(it.get("mandatory_human", False)),
                ))
            inh_human = bool(mandatory_human or (best and best[1].original_mandatory_human))
            self._push({"reporter": reporter, "reported": reported, "ts": now, "sh": sh, "kind": kind,
                        "category": category, "ref": ref, "has_neg": has_neg, "topics": prob_topics,
                        "mandatory_human": inh_human, "tid": ticket_id, "result": best[1] if best else None})
            if ticket_id:
                self._tids.setdefault(ticket_id, set()).add(fingerprint)
                self._tids.move_to_end(ticket_id)
                while len(self._tids) > MAX_TICKET_IDS:
                    self._tids.popitem(last=False)
        return best[1] if best else None

    def discard(self, ref: str) -> None:
        """Убрать обращение из памяти, если его не удалось сохранить: несуществующее обращение не должно быть оригиналом."""
        with self._lock:
            gone: set[str] = set()
            for lst in self._by_reporter.values():
                gone.update(it["tid"] for it in lst if it.get("ref") == ref and it.get("tid"))
                lst[:] = [it for it in lst if it.get("ref") != ref]
            for tid in gone:       # отпечаток остаётся, только пока где-то есть само обращение с этим идентификатором
                if not any(it.get("tid") == tid for lst in self._by_reporter.values() for it in lst):
                    self._tids.pop(tid, None)

    def restore(self, rows: list[dict]) -> int:
        """Восстановить память после перезапуска из сохранённых обращений.

        Каждая строка: reporter, reported, text, kind, category, ts (ISO), ref."""
        n = 0
        with self._lock:
            for r in rows:
                if not r.get("reporter"):
                    continue
                txt = r.get("text") or ""
                self._push({"reporter": r["reporter"], "reported": r.get("reported"), "ts": _ts(r.get("ts")) or _utcnow(),
                            "sh": _shingles(txt), "kind": r["kind"], "category": r.get("category"),
                            "ref": r.get("ref"), "has_neg": _has_negation(txt), "topics": _problem_topics(txt),
                            "mandatory_human": bool(r.get("mandatory_human", False))})
                n += 1
        return n
