"""Проверка текста ответа, который пишет или правит человек, и текста шаблонов.

Пайплайн сам подставляет пункты правил по коду, но администратор может переписать черновик. Поэтому перед сохранением
утверждённого текста сервер разбирает его заново:

* каждая ссылка на пункт правил в тексте сверяется с rules.json, несуществующая блокирует сохранение;
* обещания разбана, возврата, компенсации и наказания блокируют сохранение;
* список подтверждённых цитат берётся из самого текста, а не из того, что было у исходного черновика.

Проверка выполняется кодом по rules.json, модель в ней не участвует.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import guard, i18n
from .rules import SECTIONS, RuleBase

MAX_TEXT = 4000
MIN_TEXT = 5

_KW = r"(?:п\.|пп\.|пункт\w*|rule|item|punto|clause)"
_NUM = r"\d{1,2}(?:\.\d{1,3}){1,8}"
_AFTER = re.compile(
    rf"(?P<kw>{_KW})\s*(?:(?P<pre>[A-Za-zА-Яа-яЁё]{{1,4}})\s+)?(?P<num>{_NUM})(?!\d)(?!\.\d)"
    r"(?:[ \t]*[.,]?[ \t]*(?P<suf>[A-Za-zА-Яа-яЁё]{1,10})\b)?",
    re.IGNORECASE,
)
# казахский и узбекский: «Жалпы ережелердің 2.1-тармағы», «Umumiy qoidalarning 2.1-bandi»
_SUFFIX = re.compile(rf"(?P<num>{_NUM})-(?:тарма\w*|band\w*)", re.IGNORECASE)

# названия разделов на всех языках черновиков -> id раздела
_NAMES: list[tuple[str, int]] = sorted(
    {(name.lower(), sid) for table in i18n.SECTION_GEN.values() for sid, name in table.items()},
    key=lambda x: -len(x[0]),
)
_ALIASES: dict[str, int] = {}
for _sid, (_prefix, _short, _syn) in SECTIONS.items():
    if _prefix:
        _ALIASES[_prefix.lower()] = _sid
    for _a in _syn:
        _ALIASES.setdefault(_a.lower(), _sid)

# наказание и исход, которые нельзя обещать от имени сервиса
_EXTRA_PROMISE = re.compile(
    "|".join([
        r"\b(?:будет|будут)\s+(?:наказан\w*|забанен\w*|заблокирован\w*|оштрафован\w*|уволен\w*|лишен\w*|лишён\w*)",
        r"\b(?:накажем|забаним|заблокируем|оштрафуем|уволим|лишим)\b",
        r"\bполучит(?:е)?\s+(?:бан|блокировк\w*|мут|варн|warn)\b",
        r"\bjazolaymiz\b|\bjazolanadi\b|\bbloklaymiz\b",
        r"жазалаймыз|бұғаттаймыз",
        r"\bwill be (?:banned|punished|blocked|fined|unbanned|refunded|restored)\b|\bwe(?: will|'ll) (?:ban|punish|block|fine|unban|refund|restore)\b",
        r"\byou(?:'ll| will) (?:be )?(?:unbanned|refunded|banned|punished)\b",
        # испанский и португальский
        r"\bser[aá] (?:castigad[oa]|banead[oa]|sancionad[oa]|bloquead[oa]|desbanead[oa]|reembolsad[oa]|restaurad[oa])\b",
        r"\b(?:castigaremos|banearemos|sancionaremos|bloquearemos|desbanearemos)\b",
        r"\bser[aá] (?:banid[oa]|punid[oa]|castigad[oa]|bloquead[oa]|desbanid[oa]|reembolsad[oa]|restaurad[oa])\b",
        r"\b(?:baniremos|puniremos|castigaremos|bloquearemos|desbaniremos|reembolsaremos|devolveremos)\b",
    ]),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextRef:
    raw: str            # как написано в тексте
    num: str            # «2.1»
    cite: str           # «2.1» или «ЖБ 1.2.3»
    section_id: int
    exists: bool


@dataclass
class Violation:
    code: str           # rule_missing | promise | empty | too_long
    message: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


@dataclass
class Verification:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    refs: list[TextRef] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)      # подтверждённые цитаты, найденные в тексте

    def as_dict(self) -> dict:
        return {"ok": self.ok, "violations": [v.as_dict() for v in self.violations], "warnings": self.warnings,
                "cited": self.cited,
                "refs": [{"raw": r.raw, "cite": r.cite, "exists": r.exists} for r in self.refs]}


_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]+")


def _norm(text: str) -> str:
    """Один вид записи для разбора: полноширинные точки и цифры, типографские апострофы, без невидимых символов."""
    t = _INVISIBLE.sub("", text or "")
    t = unicodedata.normalize("NFKC", t)
    return t.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'").replace("\u00b4", "'")


def _section_near(text: str, start: int, end: int, pre: str | None, suf: str | None = None) -> int:
    """Раздел для ссылки: ближайшее название раздела рядом с номером, иначе сокращение до или после номера («ЖБ 2.1»,
    «2.1 ЖБ»), иначе Общие правила."""
    low = text.lower()
    best: tuple[int, int] | None = None   # (расстояние, id)
    for name, sid in _NAMES:
        for m in re.finditer(re.escape(name), low[max(0, start - 70): end + 90]):
            base = max(0, start - 70)
            a, b = base + m.start(), base + m.end()
            dist = a - end if a >= end else start - b
            if dist < 0:
                dist = 0
            if dist <= 45 and (best is None or dist < best[0]):
                best = (dist, sid)
    if best is not None:
        return best[1]
    for alias in (pre, suf):
        if alias and alias.lower() in _ALIASES:
            return _ALIASES[alias.lower()]
    return 30


def extract_refs(text: str, rb: RuleBase) -> list[TextRef]:
    """Все ссылки на пункты в тексте, с проверкой по rules.json."""
    text = _norm(text)
    out: list[TextRef] = []
    seen: set[tuple[int, str]] = set()

    def add(raw: str, num: str, sid: int) -> None:
        if (sid, num) in seen:
            return
        seen.add((sid, num))
        prefix = SECTIONS[sid][0]
        cite = f"{prefix} {num}" if prefix else num
        out.append(TextRef(raw=raw.strip(), num=num, cite=cite, section_id=sid, exists=rb.exists(cite)))

    for m in _AFTER.finditer(text):
        add(m.group(0), m.group("num"), _section_near(text, m.start(), m.end(), m.group("pre"), m.group("suf")))
    for m in _SUFFIX.finditer(text):
        add(m.group(0), m.group("num"), _section_near(text, m.start(), m.end(), None))
    return out


def find_promise(text: str) -> str | None:
    text = _norm(text)
    m = guard._PROMISE_RX.search(text) or _EXTRA_PROMISE.search(text)
    return m.group(0) if m else None


def verify_text(text: str, rb: RuleBase, *, allow_placeholders: bool = False) -> Verification:
    """Проверка текста перед сохранением. `allow_placeholders` разрешает {nick}, {n} в шаблонах."""
    text = text or ""
    v = Verification(ok=True)
    stripped = text.strip()
    if len(stripped) < MIN_TEXT:
        v.violations.append(Violation("empty", "Текст ответа пустой или слишком короткий"))
    if len(text) > MAX_TEXT:
        v.violations.append(Violation("too_long", f"Текст длиннее {MAX_TEXT} символов"))
    v.refs = extract_refs(text, rb)
    for r in v.refs:
        if not r.exists:
            v.violations.append(Violation(
                "rule_missing", f"Пункта «{r.raw}» нет в rules.json", r.cite))
    v.cited = [r.cite for r in v.refs if r.exists]
    hit = find_promise(text)
    if hit:
        v.violations.append(Violation(
            "promise", f"В тексте обещание разбана, возврата, компенсации или наказания: «{hit}»", hit))
    if not allow_placeholders and re.search(r"\{[a-z_]+\}", text):
        v.warnings.append("В тексте остались незаполненные поля вида {nick}")
    v.ok = not v.violations
    return v


def text_ref_issues(text: str, cited: list[str], rb: RuleBase) -> list[str]:
    """Для черновика пайплайна: пункты в тексте, которых нет в rules.json или нет среди подтверждённых цитат."""
    issues: list[str] = []
    cited_set = set(cited)
    for r in extract_refs(text, rb):
        if not r.exists:
            issues.append(f"в тексте черновика пункт «{r.raw}» отсутствует в rules.json")
        elif r.cite not in cited_set:
            issues.append(f"в тексте черновика пункт «{r.raw}» не входит в подтверждённые цитаты")
    return issues
