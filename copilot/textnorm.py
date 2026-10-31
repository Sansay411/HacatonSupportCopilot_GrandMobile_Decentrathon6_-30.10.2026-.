"""Нормализация текста игрока.

Игровой клиент работает в cp1251, поэтому на kz-серверах казахские буквы
приходят похожими символами из других кириллиц. Таблица из README данных.
"""
from __future__ import annotations

import re
import unicodedata

# cp1251-суррогаты казахских букв (README данных кейса)
KK_CP1251_MAP = {
    "ќ": "қ", "Ќ": "Қ",
    "ґ": "ғ", "Ґ": "Ғ",
    "ѕ": "ң", "Ѕ": "Ң",
    "є": "ә", "Є": "Ә",
    "ј": "ө", "Ј": "Ө",
    "ў": "ұ", "Ў": "Ұ",
    "ї": "ү", "Ї": "Ү",
}
# Буквы, которые в живом тексте почти всегда означают cp1251-суррогат.
# «ў» входит в узбекскую кириллицу, а «є», «ї», «ґ» в украинскую, поэтому
# по ним одним замену не включаем.
_STRONG_SURROGATES = set("ќЌѕЅјЈ")

_WS = re.compile(r"\s+")
_REPEAT = re.compile(r"(.)\1{3,}")
# Zero-width и управляющие невидимые символы, которыми обходят регулярки
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]+")


def has_kk_surrogates(text: str) -> bool:
    return any(ch in _STRONG_SURROGATES for ch in text)


def fix_cp1251_kazakh(text: str, region: str | None = None) -> str:
    """Возвращает казахские буквы на место.

    Замену делаем, если тикет пришёл с kz-сервера или в тексте есть
    однозначные суррогаты. Иначе «ў» трогать нельзя: это узбекская буква.
    """
    if not text:
        return text
    if region == "kz" or has_kk_surrogates(text):
        return "".join(KK_CP1251_MAP.get(ch, ch) for ch in text)
    return text


def clean(text: str | None, region: str | None = None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = _INVISIBLE.sub("", t)
    t = fix_cp1251_kazakh(t, region)
    t = t.replace(" ", " ")
    t = _WS.sub(" ", t).strip()
    return t


def for_matching(text: str) -> str:
    """Форма для регулярок и классификатора: нижний регистр, ё→е, без растяжек."""
    t = _INVISIBLE.sub("", text)
    t = fix_cp1251_kazakh(t).lower().replace("ё", "е")
    t = _REPEAT.sub(r"\1\1", t)
    return t
