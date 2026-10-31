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

# Утверждения, которые верны только после действия человека: «передано администратору», «жалоба закрыта»,
# «жалоба рассмотрена». Канала отправки у сервиса нет, поэтому такой текст нельзя отдавать без проверки.
_CLAIM = [
    r"передан[оаы]?\s+(?:администратор|старшей|ответственн)", r"передал\s+администратор", r"администратору\b.{0,20}\bпередан",
    r"(?:направлен|отправлен)[оаы]?\s+(?:администратор|старшей)",
    r"жалоба\s+(?:рассмотрена|закрыта)", r"обжалование\s+рассмотрено", r"\bжалоба\s+принята\b",
    r"ma[’']?muriyatga\s+(?:yuborildi|yetkazildi)", r"administratorga\s+(?:ham\s+)?(?:yetkazildi|yuborildi)",
    r"shikoyat\s+yopildi", r"ko[‘']rib\s+chiqildi",
    r"әкімшіге\s+(?:де\s+)?(?:берілді|жіберілді)", r"аға\s+әкімшілікке\s+(?:жіберілді|берілді)", r"шағым\s+жабылды", r"шағымыңыз\s+қаралды",
    r"(?:passed|forwarded|sent)\s+(?:this\s+|it\s+)?to\s+(?:an?\s+|the\s+)?(?:administrator|senior|admin)",
    r"(?:has|have)\s+(?:also\s+)?been\s+(?:passed|forwarded|sent)\s+to\s+(?:an?\s+|the\s+)?(?:administrator|senior)",
    r"complaint\s+is\s+closed", r"(?:has|have)\s+been\s+reviewed",
    r"queja\s+(?:est[aá]\s+cerrada|ha\s+sido\s+revisada)", r"(?:pas[oó]|avisado|enviad[oa])\s+a\s+(?:un\s+)?(?:la\s+)?administra",
    r"den[uú]ncia\s+(?:est[aá]\s+encerrada|foi\s+analisada)", r"encaminhad[oa]\s+(?:a|ao)\s+(?:um\s+)?(?:administra|à\s+administra)",
]
_CLAIM_RX = re.compile("|".join(_CLAIM), re.I)


def claims_action(text: str) -> bool:
    """Текст утверждает, что обращение передано, рассмотрено или закрыто."""
    return bool(_CLAIM_RX.search(text or ""))


def check(text: str, cited: list[str], rb: RuleBase) -> tuple[list[str], list[str]]:
    """Возвращает (валидные цитаты, причины для человека)."""
    reasons = []
    valid = [c for c in cited if rb.exists(c)]
    if len(valid) != len(cited):
        reasons.append("удалены несуществующие пункты правил: " + ", ".join(c for c in cited if c not in valid))
    if _PROMISE_RX.search(text or ""):
        reasons.append("в тексте обещание (разбан, возврат, компенсация): нужен человек")
    return valid, reasons
