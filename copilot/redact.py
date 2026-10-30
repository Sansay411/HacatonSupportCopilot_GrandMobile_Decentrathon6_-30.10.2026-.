"""Маскирование секретов в тексте обращения до записи в базу и до разбора.

Игроки иногда вставляют в обращение пароль, ключ или номер карты. Хранить такое открытым текстом в базе нельзя.
Маскируются только узнаваемые шаблоны: токены и ключи, JWT, номера карт с верной контрольной суммой Luhn, значения
после слов «пароль», «PIN», «CVV», «token». На категорию и приоритет это не влияет: они определяются по словам вокруг.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_MASK = "[скрыто]"

_TOKENS = re.compile(
    r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"            # ключи в стиле API-провайдеров
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"                 # токены GitHub
    r"|\bxox[abprs]-[A-Za-z0-9\-]{10,}"              # токены Slack
    r"|\bAKIA[0-9A-Z]{16}\b"                         # ключ доступа AWS
    r"|\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"  # JWT
)
_CARD = re.compile(r"(?<![\w.])(?:\d[ \-]?){13,19}(?![\w])")
# трёхзначный CVV и подобные коды короче порога общего правила, поэтому для них отдельный шаблон
_CVV = re.compile(r"(?P<label>\b(?:cvv2?|cvc2?|cvn|cid)\b)(?P<sep>\s*[:=\-–—]?\s*)(?P<val>\d{3,4})\b", re.IGNORECASE)
_LABELLED = re.compile(
    r"(?P<label>\b(?:парол[ьяюеи]|password|passwd|pwd|pass|пин(?:[\s\-]?код)?|pin(?:[\s\-]?code)?|cvv2?|cvc2?|"
    r"токен|token|api[\s_\-]?key|секрет\w*|secret)\b)\s*(?P<sep>[:=\-–—]\s*|\s+(?:это|is)\s+|\s+)(?P<val>\S{4,64})",
    re.IGNORECASE,
)


@dataclass
class Redaction:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.counts)


def _luhn(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        flip = not flip
    return total % 10 == 0


def redact(text: str) -> Redaction:
    counts: dict[str, int] = {}

    def bump(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    def token(m: re.Match) -> str:
        bump("token")
        return _MASK

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            bump("card")
            return f"[карта ****{digits[-4:]}]"
        return m.group(0)

    def labelled(m: re.Match) -> str:
        val = m.group("val")
        sep = m.group("sep")
        explicit = ":" in sep or "=" in sep or "-" in sep or "–" in sep or "—" in sep
        # без явного разделителя маскируем только то, что похоже на пароль: есть цифра
        if not explicit and not re.search(r"\d", val):
            return m.group(0)
        if val == _MASK or val.startswith("[карта"):
            return m.group(0)
        bump("secret")
        return f"{m.group('label')}{sep}{_MASK}"

    def cvv(m: re.Match) -> str:
        bump("secret")
        return f"{m.group('label')}{m.group('sep')}{_MASK}"

    out = _TOKENS.sub(token, text or "")
    out = _CARD.sub(card, out)
    out = _CVV.sub(cvv, out)
    out = _LABELLED.sub(labelled, out)
    return Redaction(out, counts)
