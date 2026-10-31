"""Стиль ответа: без тире, слешей, эмодзи, разметки и штампов, по которым узнают текст ИИ.

Фильтр работает над любым черновиком, шаблоном или ответом модели. `clean` исправляет то, что можно исправить без потери
смысла, `issues` называет то, что осталось, а `apply_draft` для конвейера снимает автоотправку, если осталось что-то
неисправимое. Запрещено: тире (длинное, среднее, `--`, дефис с пробелами, диапазон через дефис), слеш вне ссылок,
эмодзи и стрелки, разметка (`*`, обратные кавычки, заголовки, списки), многоточие, больше одного «!», штампы вроде
«Конечно!» и «Рад помочь». Дефис внутри слова («кто-то», «из-за») остаётся: без него русский текст ломается.
Ссылки не трогаем, в них слеши нужны.
"""
from __future__ import annotations

import re
from dataclasses import replace

_DASH_CHARS = "—–―‒−"
_DASH_CLASS = "[—–―‒−]"
_URL = re.compile(
    r"(?:https?://|www\.)[^\s]*[^\s.,;:!?)\]»\"']"
    r"|(?:[a-z0-9-]+\.)+[a-z]{2,}/[^\s]*[^\s.,;:!?)\]»\"']"
    r"|(?:[a-z0-9-]+\.)+[a-z]{2,}/",
    re.I,
)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF←-⇿⌀-⏿☀-➿⬀-⯿️‍"
                    "•▪●▶]")
_INVISIBLE = re.compile(r"[​‌‎‏‪-‮⁠﻿­]+")
_RANGE = re.compile(r"(?<![\w.\-–—])(?:(от|на|до|около|в|за|по|через|с)\s+)?(\d+)\s*[–—―‒−-]\s*(\d+)(?![\w.\-–—])", re.I)
_NUM_HYPHEN = re.compile(r"(?<![\w.\-])\d+\s*-\s*\d+(?![\w.\-])")
_DASH_ANY = re.compile(r"\s*(?:" + _DASH_CLASS + r"|-{2,})\s*|\s+-\s+")
_PLACEHOLDER_SENTENCE = re.compile(r"^[^:]{1,80}:\s*(?:" + _DASH_CLASS + r"|-)+\s*[.!?]?$")
_KK_CASES = {"минут": ("минуттан", "минутқа"), "сағат": ("сағаттан", "сағатқа"), "күн": ("күннен", "күнге"),
             "апта": ("аптадан", "аптаға"), "ай": ("айдан", "айға")}
_OR = {"ru": "или", "kk": "немесе", "uz": "yoki", "en": "or", "es": "o", "pt": "ou"}

# штампы чат-ботов: в сообщении администратора игроку они выглядят как текст ИИ
_STAMPS = [re.compile(p, re.I) for p in (
    # ru
    r"\bконечно\b", r"\bбезусловно\b", r"\bразумеется\b", r"\bрад[ыа]?\s+(?:вам\s+)?помочь", r"с\s+радостью",
    r"надеюсь,\s+(?:это|что\s+это|я\s+смог)", r"не\s+стесняйтесь", r"(?:важно|стоит|следует|необходимо)\s+отметить",
    r"как\s+(?:языковая\s+)?модель", r"как\s+(?:ии|искусственный\s+интеллект)",
    r"если\s+(?:у\s+вас\s+)?(?:остались|возникнут|появятся)\s+(?:ещ[её]\s+|дополнительные\s+)?вопросы",
    r"обращайтесь\s+(?:снова|в\s+любое\s+время|ещ[её])", r"всегда\s+(?:рады|готовы)\s+помочь",
    r"ваше\s+(?:мнение|обращение)\s+(?:очень\s+)?важно\s+для\s+нас", r"\bв\s+заключение\b", r"подводя\s+итог",
    r"давайте\s+разберёмся|давайте\s+разберемся", r"понимаю\s+ваше\s+(?:разочарование|беспокойство|недовольство)",
    r"\bии\b", r"нейросет\w*", r"искусственн\w+\s+интеллект\w*", r"мне\s+доступн\w*|доступн\w*\s+мне",
    r"у\s+меня\s+(?:\S+\s+){0,3}?нет\b",
    # en
    r"\bcertainly\b", r"\bof\s+course\b", r"i(?:'m|\s+am)\s+(?:happy|glad)\s+to\s+help", r"feel\s+free\s+to",
    r"i\s+hope\s+this\s+helps", r"it(?:'s|\s+is)\s+(?:important|worth)\s+(?:to\s+)?not(?:e|ing)", r"\bas\s+an\s+ai\b",
    r"language\s+model", r"don't\s+hesitate\s+to", r"\bdelve\b", r"i\s+understand\s+your\s+frustration",
    # kk, uz
    r"\bәрине\b", r"көмектесуге\s+қуаныштымын", r"\balbatta\b", r"yordam\s+berishdan\s+mamnun", r"bemalol\s+murojaat",
    # es, pt
    r"\bpor\s+supuesto\b", r"estar[eé]\s+encantad[oa]", r"no\s+dudes\s+en", r"espero\s+que\s+esto\s+ayude",
    r"como\s+modelo\s+de\s+lenguaje", r"n[aã]o\s+hesite", r"espero\s+que\s+isso\s+ajude", r"como\s+um\s+modelo\s+de\s+linguagem",
    r"com\s+certeza",
)]
_MARKUP = re.compile(r"[*`{}]|<\w+[^>]*>|(?m:^\s*#)")


_TOKEN_OPEN, _TOKEN_CLOSE = "\ue000", "\ue001"   # символы частного использования: в живом тексте не встречаются


def _mask(text: str) -> tuple[str, list[str]]:
    """Прячет ссылки, чтобы фильтр не трогал слеши внутри них."""
    urls: list[str] = []

    def keep(m: re.Match) -> str:
        urls.append(m.group(0))
        return f"{_TOKEN_OPEN}{len(urls) - 1}{_TOKEN_CLOSE}"

    return _URL.sub(keep, text), urls


def _unmask(text: str, urls: list[str]) -> str:
    for i, u in enumerate(urls):
        text = text.replace(f"{_TOKEN_OPEN}{i}{_TOKEN_CLOSE}", u)
    return text


def _range_words(t: str, lang: str) -> str:
    """«15–30 минут» словами на языке ответа. Запятая вместо тире превратила бы диапазон в два отдельных срока."""
    if lang == "ru":
        return _RANGE.sub(lambda m: f"{m.group(1) or 'от'} {m.group(2)} до {m.group(3)}", t)
    if lang == "uz":
        return _range_unit("daqiqa|soat|kun|hafta|oy").sub(lambda m: f"{m[1]} dan {m[2]} {m[3]}gacha", t)
    if lang == "kk":
        def kk(m):
            abl, dat = _KK_CASES[m[3].lower()]
            return f"{m[1]} {abl} {m[2]} {dat} дейін"
        return _range_unit("|".join(_KK_CASES)).sub(kk, t)
    if lang == "en":
        return _range_unit("minutes|hours|days|weeks|months").sub(lambda m: f"{m[1]} to {m[2]} {m[3]}", t)
    if lang in ("es", "pt"):
        units = "minutos|horas|días|semanas|meses" if lang == "es" else "minutos|horas|dias|semanas|meses"
        return _range_unit(units).sub(lambda m: f"de {m[1]} a {m[2]} {m[3]}", t).replace("de de ", "de ")
    return t


def _range_unit(units: str) -> re.Pattern:
    return re.compile(r"(?<![\w.\-–—])(\d+)\s*[–—―‒−-]\s*(\d+)\s+(" + units + r")\b", re.I)


def _dash_sub(m: re.Match) -> str:
    before = m.string[m.start() - 1:m.start()]
    after = m.string[m.end():m.end() + 1]
    if before.isdigit() and after.isdigit():
        return m.group(0)   # диапазон с неизвестной единицей оставляем как есть: issues() его назовёт, человек поправит
    if before in (":", ",", ";"):
        return " "
    return ". " if (not after or after.isupper()) else ", "


def clean(text: str, lang: str = "ru") -> str:
    """Исправляет запрещённое в стиле, не меняя смысл. Неисправимое остаётся и попадает в `issues`."""
    t, urls = _mask(_INVISIBLE.sub("", text or "").replace(" ", " ").replace(" ", " "))
    t = _EMOJI.sub("", t)
    t = re.sub(r"(?m)^\s*(?:[-*•]|#{1,6})\s+", "", t)
    for mark in ("**", "__", "~~", "`", "*"):
        t = t.replace(mark, "")
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"…|\.{2,}", ".", t)

    # «Наказание по правилам: —.» без значения: фразу целиком убираем, пустое тире не подставляем
    parts = [s for s in re.split(r"(?<=[.!?])\s+", t) if not _PLACEHOLDER_SENTENCE.match(s.strip())]
    t = " ".join(parts)

    t = _range_words(t, lang)
    t = _DASH_ANY.sub(_dash_sub, t)

    word = _OR.get(lang, "или")
    t = re.sub(r"\bи/или\b", "или", t, flags=re.I)
    t = re.sub(r"\band/or\b", "or", t, flags=re.I)
    t = re.sub(r"(\S)\s*/\s*(\S)", lambda m: m.group(0) if m.group(1).isdigit() and m.group(2).isdigit()
               else f"{m.group(1)} {word} {m.group(2)}", t)
    t = re.sub(r"(?<!\d)/|/(?!\d)|\\", " ", t)

    t = re.sub(r"!{2,}", "!", t)
    t = re.sub(r"\?!|!\?", "?", t)
    t = re.sub(r"\?{2,}", "?", t)
    first = t.find("!")
    if first != -1:
        t = t[:first + 1] + t[first + 1:].replace("!", ".")

    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:])\s*([.!?])", r"\2", t)
    t = re.sub(r"([.!?])\s*\.", r"\1", t)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"[ \t]{2,}", " ", t).strip(" ,")
    return _unmask(t, urls)


def issues(text: str, lang: str = "ru") -> list[str]:
    """Что в тексте всё ещё нарушает стиль. Пустой список: текст чист."""
    t, _ = _mask(text or "")
    out = []
    if (any(ch in t for ch in _DASH_CHARS) or re.search(r"-{2,}| - |(?m:^\s*-\s)", t) or _NUM_HYPHEN.search(t)):
        out.append("dash: тире или диапазон через дефис")
    if "/" in t or "\\" in t:
        out.append("slash: слеш вне ссылки")
    if _EMOJI.search(t):
        out.append("emoji: эмодзи или стрелка")
    if _MARKUP.search(t):
        out.append("markup: разметка или остатки JSON")
    if "…" in t or ".." in t:
        out.append("ellipsis: многоточие")
    if t.count("!") > 1:
        out.append("exclaim: больше одного восклицательного знака")
    for rx in _STAMPS:
        m = rx.search(t)
        if m:
            out.append(f"stamp: штамп чат-бота «{m.group(0).lower()}»")
            break
    return out


def enforce(text: str, lang: str = "ru") -> tuple[str, list[str]]:
    """Очищенный текст и то, что исправить не удалось."""
    cleaned = clean(text, lang)
    return cleaned, issues(cleaned, lang)


def apply_draft(d):
    """Применяется к черновику в конвейере. Если осталось неисправимое, автоотправка снимается."""
    text, left = enforce(d.text, d.lang)
    alts = [dict(a, text=clean(a["text"], d.lang)) for a in d.alternatives]
    reasons = list(d.reasons)
    auto_ok = d.auto_ok
    if left:
        reasons.append("стиль: " + "; ".join(left) + "; отправка только после проверки человеком")
        auto_ok = False
    return replace(d, text=text, alternatives=alts, reasons=reasons, auto_ok=auto_ok)
