"""База правил: загрузка rules.json, разбор ссылок на пункты, поиск по тексту.

Номера пунктов повторяются между разделами («1.1» есть почти в каждом), поэтому
ссылка без раздела относится к Общим правилам (так пишут и админы: «2.1 ОП»),
а для остальных разделов используется префикс: «ЖБ 1.2.3», «GZ 1.1».
Ссылка в ответе сервиса появляется только если такой пункт реально есть в
rules.json: это проверяется кодом, а не моделью.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .textnorm import for_matching

# id раздела в rules.json -> (префикс для цитаты, короткое имя, синонимы в текстах)
SECTIONS: dict[int, tuple[str, str, tuple[str, ...]]] = {
    30: ("", "Общие правила", ("оп", "op", "ор", "опп", "общих", "общие", "общ")),
    31: ("ЖБ", "Правила подачи жалоб", ("жб", "ппж", "пж", "жалоб", "жалобы")),
    32: ("GZ", "Правила Зелёной Зоны", ("gz", "гз", "зз", "green", "greenzone", "зеленой", "зелёной", "zz")),
    33: ("ПЛ", "Правила для лидеров", ("пл", "лидер", "лидеров")),
    34: ("ПГО", "Правила государственных организаций", ("пго", "госс", "гос", "мвд", "пгос")),
    35: ("ГВ", "Правила гос. волны и департамента", ("гв", "волна", "департамент")),
    36: ("ФВ", "Правила семейных мероприятий", ("фв", "fw", "семейн")),
    40: ("ОПГ", "Правила для ОПГ", ("опг", "opg")),
    41: ("БВБ", "Правила войны за бизнес", ("бвб", "бизвар", "пвб", "bw", "стрел")),
    42: ("ПБФ", "Правила битвы за фургон", ("пбф", "фургон")),
}
RP_TERMS_SECTION = 43
_PREFIX_TO_SECTION = {v[0].lower(): k for k, v in SECTIONS.items() if v[0]}

_REF_IN_TEXT = re.compile(
    r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){1,2})(?![\d])\s*[.,]?\s*([a-zа-яё]{1,10})?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RulePoint:
    section_id: int
    ref: str            # как в rules.json: «2.1», «1.2.3»
    text: str

    @property
    def cite(self) -> str:
        prefix = SECTIONS[self.section_id][0]
        return f"{prefix} {self.ref}" if prefix else self.ref

    @property
    def section_name(self) -> str:
        return SECTIONS[self.section_id][1]

    @property
    def body(self) -> str:
        return self.text.split(" | ")[0].strip()

    @property
    def sanctions(self) -> list[str]:
        parts = [p.strip() for p in self.text.split(" | ")[1:]]
        out = []
        for p in parts:
            # хвосты вида «III. ПРАВИЛА ...» в конце пункта отрезаем
            p = re.split(r"\s+[IVX]{1,4}\.\s+[А-ЯЁ]", p)[0].strip()
            if p:
                out.append(p)
        return out


@dataclass
class RpTerm:
    code: str
    title: str
    text: str


@dataclass
class RuleBase:
    points: dict[str, RulePoint] = field(default_factory=dict)   # cite -> point
    terms: dict[str, RpTerm] = field(default_factory=dict)       # «DM» -> term
    _idf: dict[str, float] = field(default_factory=dict)
    _docs: list[tuple[str, list[str]]] = field(default_factory=list)

    # ---------- проверка ссылок ----------
    def exists(self, cite: str) -> bool:
        return cite in self.points

    def get(self, cite: str) -> RulePoint | None:
        return self.points.get(cite)

    def parse_refs(self, text: str, default_section: int = 30) -> list[str]:
        """Достаёт из свободного текста ссылки и приводит к виду цитаты.

        Возвращает только существующие пункты. «2.1оп», «5.2 OP», «1.1 gz»,
        «1.2.3 ППЖ». Голые числа вроде «3» или «357» ссылками не считаем.
        """
        if not text:
            return []
        t = for_matching(text)
        found: list[str] = []
        for m in _REF_IN_TEXT.finditer(t):
            num, suffix = m.group(1), (m.group(2) or "").lower()
            sec = default_section
            if suffix:
                for sid, (_, _, aliases) in SECTIONS.items():
                    if any(suffix == a or (len(a) > 3 and suffix.startswith(a)) for a in aliases):
                        sec = sid
                        break
                # «опг» начинается с «оп», поэтому проверка выше идёт по равенству
            point = self._lookup(sec, num)
            if point is None and sec != default_section and not suffix:
                point = self._lookup(default_section, num)
            if point and point.cite not in found:
                found.append(point.cite)
        return found

    def _lookup(self, section_id: int, ref: str) -> RulePoint | None:
        prefix = SECTIONS.get(section_id, ("",))[0]
        return self.points.get(f"{prefix} {ref}" if prefix else ref)

    # ---------- поиск (BM25) ----------
    def search(self, query: str, k: int = 5, sections: set[int] | None = None) -> list[tuple[RulePoint, float]]:
        q = _terms(query)
        if not q:
            return []
        scores = []
        avg = sum(len(d) for _, d in self._docs) / max(1, len(self._docs))
        for cite, doc in self._docs:
            p = self.points[cite]
            if sections and p.section_id not in sections:
                continue
            s = 0.0
            tf: dict[str, int] = {}
            for w in doc:
                tf[w] = tf.get(w, 0) + 1
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += self._idf.get(w, 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(doc) / avg))
            if s > 0:
                scores.append((p, s))
        scores.sort(key=lambda x: -x[1])
        return scores[:k]


def _stem(w: str) -> str:
    # грубый стеммер: для поиска по правилам хватает отсечения окончаний
    return w[:6] if len(w) > 6 else w


def _terms(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-zа-яё]{3,}", for_matching(text))]


def _parse_terms(text: str) -> dict[str, RpTerm]:
    out = {}
    for line in text.split("\n"):
        m = re.match(r"•\s*(.+?)\s*\(сокращенно\s+([^)]+)\)\s*[—-]\s*(.+)", line.strip())
        if m:
            code = m.group(2).strip()
            out[code.upper()] = RpTerm(code=code, title=m.group(1).strip(), text=m.group(3).strip())
    return out


@lru_cache(maxsize=4)
def load(path: str | Path) -> RuleBase:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rb = RuleBase()
    for sec in data["rules"]:
        sid = sec["id"]
        if sid == RP_TERMS_SECTION:
            rb.terms = _parse_terms(sec["text"])
            continue
        if sid not in SECTIONS:
            continue
        for p in sec.get("points", []):
            point = RulePoint(section_id=sid, ref=p["ref"], text=p["text"])
            rb.points[point.cite] = point
    docs = []
    for cite, p in rb.points.items():
        docs.append((cite, _terms(p.text + " " + p.section_name)))
    n = len(docs)
    dfc: dict[str, int] = {}
    for _, d in docs:
        for w in set(d):
            dfc[w] = dfc.get(w, 0) + 1
    rb._idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in dfc.items()}
    rb._docs = docs
    return rb
