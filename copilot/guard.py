"""Последняя проверка ответа перед отдачей.

1. Каждая цитата существует в rules.json; несуществующие удаляются из
   cited и из текста не исчезают сами, поэтому такой черновик уходит человеку.
2. Черновик не обещает разбан, возврат имущества или денег, компенсацию.
   Наказание другому игроку допускается только с needs_human=true.
"""
from __future__ import annotations

import re

from .rules import RuleBase

_PROMISE = [
    # ru
    r"(будет|будут|будете) (снят|снято|сняты|разбанен|разблокирован|возвращен|возвращ[её]н|восстановлен)",
    r"\bвернем\b|\bвернём\b|\bвозместим\b|компенсируем|\bразбаним\b|\bснимем\b|\bвосстановим\b",
    # свершившиеся или гарантированные исходы: «бан снят», «деньги возвращены», «гарантируем возврат»
    r"\b(бан|мут|варн|warn|наказани\w*|блокировк\w*|деморган)\s+(уже\s+|был\s+|будет\s+)?(снят\w*|отмен[её]н\w*|аннулирован\w*)",
    r"\b(деньги|денег|средства|донат\w*|имущество|аккаунт\w*|машин\w*)\s+(уже\s+|были\s+|будут\s+)?"
    r"(возвращ[её]н\w*|вернут\w*|вернуты|восстановлен\w*)",
    r"гарантиру\w+|гарантия\b|обязательно (разбан|вернем|вернём|снимем)|\bразбан\w*\s+(будет|произведен|выдан)",
    # kk
    r"қайтарамыз|алып тастаймыз|қалпына келтіреміз",
    # uz
    r"qaytaramiz|olib tashlaymiz|tiklaymiz|bandan chiqaramiz",
    # en/es/pt
    r"\bwe will (unban|refund|restore|return|lift)\b|\bwill be (unbanned|refunded|restored|lifted)\b",
    r"\b(reembolsaremos|devolveremos|desbloquearemos|restauraremos)\b",
    r"\b(reembolsaremos|devolveremos|desbaniremos|restauraremos)\b",
]
_PROMISE_RX = re.compile("|".join(_PROMISE), re.I)
_REF_IN_DRAFT = re.compile(r"(?:п\.\s*|пункт\w*\s+|rule\s+|item\s+|punto\s+)(\d+(?:\.\d+)+)", re.I)


def check(text: str, cited: list[str], rb: RuleBase) -> tuple[list[str], list[str]]:
    """Возвращает (валидные цитаты, причины для человека)."""
    reasons = []
    valid = [c for c in cited if rb.exists(c)]
    if len(valid) != len(cited):
        reasons.append("удалены несуществующие пункты правил: " + ", ".join(c for c in cited if c not in valid))
    if _PROMISE_RX.search(text or ""):
        reasons.append("в тексте обещание (разбан, возврат, компенсация): нужен человек")
    return valid, reasons
