"""Кандидат на замену RuleBase.search в drafts.pick_violation: только эксперимент, в продукт не подключён.

Идея минимальная и без новых зависимостей: BM25 по телу пункта (без санкций), удвоенный вес первых слов пункта (в них
названо нарушение), мягкий стеммер с отсечением окончаний, слова после отрицания не участвуют в запросе. Пункт выдаётся,
только если совпали минимум два разных слова запроса и первый результат заметно сильнее второго. Параметры заданы заранее
и не подбирались ни на наборе tests/fixtures/rag_cases.py, ни на train.
"""
from __future__ import annotations

import math
import re

from copilot.rules import RuleBase
from copilot.textnorm import for_matching

_STOP = set("""и в во на не ни что это как он она они его ее их мне меня мой моя мою моё я мы вы ты у с со по за к о об от до из для
при а но или же бы ли то там тут так ещё еще уже очень просто пожалуйста""".split())
_NEG = {"не", "ни", "нет", "нету", "без", "никто", "никого", "никогда"}
_END = re.compile(r"(ыми|ими|ого|его|ому|ему|ая|ой|ый|ие|ия|ов|ев|ом|ем|ам|ям|ах|ях|ую|юю|ое|ее|ых|их|ать|ять|ить|ет|ут|ют|ит|ат|ят|ла|ли|ло|л|а|я|ы|и|у|ю|е|о)$")

MIN_MATCHED = 2
MARGIN = 1.3
HEAD_WORDS = 12


def _stem(w: str) -> str:
    s = _END.sub("", w) if len(w) > 5 else w
    return s[:6]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zа-яё]{3,}|не|ни", for_matching(text))


def query_terms(text: str) -> list[str]:
    toks = _tokens(text)
    out = []
    for i, w in enumerate(toks):
        if w in _STOP or w in _NEG:
            continue
        if any(t in _NEG for t in toks[max(0, i - 2):i]):
            continue                       # слово под отрицанием не ищем: «не использует читы»
        out.append(_stem(w))
    return out


class Candidate:
    def __init__(self, rb: RuleBase, section: int = 30):
        self.docs = []
        for cite, p in rb.points.items():
            if p.section_id != section:
                continue
            words = [_stem(w) for w in _tokens(p.body) if w not in _STOP and w not in _NEG]
            weighted = words + words[:HEAD_WORDS]
            self.docs.append((cite, weighted, set(words)))
        n = len(self.docs)
        df: dict[str, int] = {}
        for _, _, vocab in self.docs:
            for w in vocab:
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.avg = sum(len(d) for _, d, _ in self.docs) / max(1, n)

    def search(self, text: str) -> tuple[str | None, float]:
        q = list(dict.fromkeys(query_terms(text)))
        if not q:
            return None, 0.0
        scored = []
        for cite, doc, vocab in self.docs:
            tf: dict[str, int] = {}
            for w in doc:
                tf[w] = tf.get(w, 0) + 1
            matched = [w for w in q if w in tf]
            if not matched:
                continue
            s = sum(self.idf.get(w, 0) * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(doc) / self.avg)) for w in matched)
            scored.append((s, len(matched), cite))
        scored.sort(reverse=True)
        if not scored:
            return None, 0.0
        top = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        if top[1] < MIN_MATCHED or top[0] < MARGIN * second:
            return None, top[0]
        return top[2], top[0]
