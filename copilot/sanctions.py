"""Наказания из текста правил: разбор и вывод на языке игрока.

Сроки берутся только из rules.json. Если строку не удалось разобрать,
наказание в черновик не попадает: лучше без срока, чем с выдуманным.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Sanction:
    kind: str                 # mute | mute_report | ban | jail | warn | verbal | reprimand
    lo: int | None = None
    hi: int | None = None     # None + forever=True -> «навсегда»
    unit: str | None = None   # min | day
    forever: bool = False
    label: str = ""           # «Оскорбление родных» и т.п.
    alt: bool = False         # альтернатива предыдущему («или»)


_KIND = [
    (r"mute\s*report", "mute_report"),
    (r"\bmute\b|\bмут", "mute"),
    (r"блокировк\w*\s+персонаж|блокировк\w*\s+аккаунт|\bban\b|\bбан\b", "ban"),
    (r"demorgan|деморган|\bjail\b|джайл", "jail"),
    (r"\bwarn\b|\bварн\b", "warn"),
    (r"устн\w+ (предупреждени|выговор)|^предупреждение|\bпредупреждение\b", "verbal"),
]


def _num_unit(s: str) -> tuple[int | None, int | None, str | None, bool]:
    s = s.lower()
    forever = "навсегда" in s
    unit = "day" if re.search(r"дн|дня|дней|день|сут", s) else "min" if re.search(r"мин", s) else None
    if re.search(r"час", s) and unit is None:
        unit = "min"
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if "час" in s:
        nums = [n * 60 for n in nums]
    lo = hi = None
    if re.search(r"\bот\s+\d", s) and len(nums) >= 2:
        lo, hi = nums[0], nums[1]
    elif re.search(r"\bот\s+\d", s) and len(nums) == 1:
        lo = nums[0]
    elif re.search(r"\bдо\s+\d", s) and nums:
        hi = nums[0]
    elif re.search(r"\b(на|-)\s*\d", s) and nums:
        lo = hi = nums[0]
    return lo, hi, unit, forever


def parse(text: str) -> list[Sanction]:
    """«Оскорбление игрока: MUTE - от 15 до 30 минут.» -> [Sanction(mute, 15, 30, min)]"""
    out: list[Sanction] = []
    label = ""
    m = re.match(r"\s*([^:]{3,60}):\s*(.+)", text)
    body = text
    if m:
        label, body = m.group(1).strip(), m.group(2)
    pieces = re.split(r"(\s+\+\s+|\s+или\s+)", body)
    alt_next = False
    for part in pieces:
        if re.fullmatch(r"\s+или\s+", part):
            alt_next = True
            continue
        if re.fullmatch(r"\s+\+\s+", part):
            continue
        kind = None
        for rx, k in _KIND:
            if re.search(rx, part, re.I):
                kind = k
                break
        if not kind:
            continue
        lo, hi, unit, forever = _num_unit(part)
        out.append(Sanction(kind=kind, lo=lo, hi=hi, unit=unit, forever=forever, label=label, alt=alt_next))
        alt_next = False
    return out


def choose(point, text: str) -> list[Sanction]:
    """Базовая ступень наказания по пункту, с учётом подслучаев 2.1."""
    if point is None:
        return []
    lines = point.sanctions
    if not lines:
        return []
    t = text.lower()
    if point.cite == "2.1":
        if re.search(r"родн|родак|сем(ью|ья|ьи|ье)\b|\bмам[уаы]?\b|\bмать\b|матер(и|ью)\b|osk\w*\W*rod|\brod(ni|nyu|u)?\b|"
                     r"onadan|onam|onasi|анам|dodam|otam|туыс|mother|\bmom\b|family|relatives|madre|familia|m[ãa]e\b|fam[íi]lia", t) and not re.search(r"упом", t):
            pick = [l for l in lines if l.lower().startswith("оскорбление родных")]
        elif re.search(r"упом", t):
            pick = [l for l in lines if l.lower().startswith("упоминание")]
        else:
            pick = [l for l in lines if l.lower().startswith("оскорбление игрока")]
        if pick:
            return parse(pick[0])
    if point.cite == "5.2":
        if re.search(r"баг", t):
            key = "багоюз"
        elif re.search(r"автоклик|скрипт|макрос", t):
            key = "использование автокликеров"
        elif re.search(r"кноп|сборк|\bсб\b|зон\w* взаимодейств", t):
            key = "использование модификаций"
        else:
            key = "распространение"
        pick = [l for l in lines if l.lower().startswith(key)]
        if pick:
            return parse(pick[0])
    # первая строка с «Нарушение:» или первая разобранная
    for l in lines:
        if l.lower().startswith("нарушение"):
            s = parse(l)
            if s:
                return s
    for l in lines:
        s = parse(l)
        if s:
            return s
    return []


# ---------- вывод ----------
_UNITS = {
    "ru": {"min": "минут", "day": "дней"},
    "kk": {"min": "минут", "day": "күн"},
    "uz": {"min": "daqiqa", "day": "kun"},
    "en": {"min": "minutes", "day": "days"},
    "es": {"min": "minutos", "day": "días"},
    "pt": {"min": "minutos", "day": "dias"},
}
_KIND_NAMES = {
    "ru": {"mute": "мут чата", "mute_report": "мут репорта", "ban": "блокировка персонажа", "jail": "деморган",
           "warn": "WARN", "verbal": "устное предупреждение", "reprimand": "выговор"},
    "kk": {"mute": "чатқа мут", "mute_report": "репортқа мут", "ban": "кейіпкерді бұғаттау", "jail": "деморган",
           "warn": "WARN", "verbal": "ауызша ескерту", "reprimand": "сөгіс"},
    "uz": {"mute": "chatga mute", "mute_report": "reportga mute", "ban": "personajni bloklash", "jail": "demorgan",
           "warn": "WARN", "verbal": "og‘zaki ogohlantirish", "reprimand": "hayfsan"},
    "en": {"mute": "a chat mute", "mute_report": "a report mute", "ban": "a character ban", "jail": "demorgan (jail)",
           "warn": "a WARN", "verbal": "a verbal warning", "reprimand": "a reprimand"},
    "es": {"mute": "silencio en el chat", "mute_report": "silencio de reportes", "ban": "bloqueo del personaje",
           "jail": "demorgan (cárcel)", "warn": "un WARN", "verbal": "una advertencia verbal", "reprimand": "una amonestación"},
    "pt": {"mute": "silenciamento no chat", "mute_report": "silenciamento de reports", "ban": "bloqueio do personagem",
           "jail": "demorgan (prisão)", "warn": "um WARN", "verbal": "uma advertência verbal", "reprimand": "uma advertência formal"},
}


_RU_FORMS = {"min": ("минута", "минуты", "минут"), "day": ("день", "дня", "дней")}


def _ru_nom(n: int, unit: str) -> str:
    f = _RU_FORMS[unit]
    if n % 10 == 1 and n % 100 != 11:
        return f[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f[1]
    return f[2]


def _ru_gen(n: int, unit: str) -> str:
    f = _RU_FORMS[unit]
    return {"min": ("минуты", "минут"), "day": ("дня", "дней")}[unit][0 if n % 10 == 1 and n % 100 != 11 else 1]


def _span(s: Sanction, lang: str) -> str:
    if lang == "ru" and s.unit in _RU_FORMS:
        if s.forever and s.lo:
            return f"от {s.lo} {_ru_gen(s.lo, s.unit)} до бессрочной"
        if s.lo and s.hi and s.lo != s.hi:
            return f"от {s.lo} до {s.hi} {_ru_gen(s.hi, s.unit)}"
        if s.hi and not s.lo:
            return f"до {s.hi} {_ru_gen(s.hi, s.unit)}"
        if s.lo:
            return f"на {s.lo} {_ru_nom(s.lo, s.unit)}"
        return ""
    if lang == "kk" and s.unit in ("min", "day"):
        base = {"min": "минут", "day": "күн"}[s.unit]
        dat = {"min": "минутқа", "day": "күнге"}[s.unit]
        abl = {"min": "минуттан", "day": "күннен"}[s.unit]
        if s.forever and s.lo:
            return f"{s.lo} {abl} бастап мерзімсізге дейін"
        if s.lo and s.hi and s.lo != s.hi:
            return f"{s.lo}–{s.hi} {base}"
        if s.hi and not s.lo:
            return f"{s.hi} {dat} дейін"
        if s.lo:
            return f"{s.lo} {base}"
        return ""
    u = _UNITS[lang].get(s.unit or "", "")
    if s.forever and s.lo:
        return {"ru": f"от {s.lo} {u} до бессрочной", "kk": f"{s.lo} {u} бастап мерзімсізге дейін",
                "uz": f"{s.lo} {u}dan muddatsizgacha", "en": f"from {s.lo} {u} up to permanent",
                "es": f"de {s.lo} {u} a permanente", "pt": f"de {s.lo} {u} a permanente"}[lang]
    if s.lo and s.hi and s.lo != s.hi:
        return {"ru": f"от {s.lo} до {s.hi} {u}", "kk": f"{s.lo}–{s.hi} {u}", "uz": f"{s.lo}–{s.hi} {u}",
                "en": f"{s.lo}–{s.hi} {u}", "es": f"de {s.lo} a {s.hi} {u}", "pt": f"de {s.lo} a {s.hi} {u}"}[lang]
    if s.hi and not s.lo:
        return {"ru": f"до {s.hi} {u}", "kk": f"{s.hi} {u} дейін", "uz": f"{s.hi} {u}gacha",
                "en": f"up to {s.hi} {u}", "es": f"hasta {s.hi} {u}", "pt": f"até {s.hi} {u}"}[lang]
    if s.lo:
        return {"ru": f"{s.lo} {u}", "kk": f"{s.lo} {u}", "uz": f"{s.lo} {u}", "en": f"{s.lo} {u}",
                "es": f"{s.lo} {u}", "pt": f"{s.lo} {u}"}[lang]
    return ""


def render(sanctions: list[Sanction], lang: str) -> str:
    if lang not in _KIND_NAMES:
        lang = "ru"
    parts = []
    alt_word = {"ru": " или ", "kk": " немесе ", "uz": " yoki ", "en": " or ", "es": " o ", "pt": " ou "}[lang]
    out = ""
    for s in sanctions:
        name = _KIND_NAMES[lang][s.kind]
        span = _span(s, lang)
        if not span:
            parts.append(name)
        elif lang == "ru":
            parts.append(f"{name} {span}")
        elif lang in ("kk", "uz"):
            parts.append(f"{name} ({span})")
        elif lang == "en":
            parts.append(f"{name} for {span}" if not span.startswith(("up", "from")) else f"{name} ({span})")
        else:
            parts.append(f"{name} ({span})")
        piece = parts.pop()
        out = piece if not out else out + (alt_word if s.alt else " + ") + piece
    return out
