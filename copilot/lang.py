"""Определение языка игрока и языка ответа.

Без внешних моделей: тексты короткие (медиана в несколько слов), со сленгом
и транслитом, а у fastText/langid на таких строках точность хуже простых
правил по алфавиту и словарю. Поле lang в данных тоже эвристика, и в нём
украинский попадает в kk, а «5.2 OP» в lat.
"""
from __future__ import annotations

import re

from .textnorm import for_matching

SUPPORTED_REPLY = ("ru", "kk", "uz", "en", "es", "pt")

_KK_LETTERS = set("әғқңөұүһі")
_KK_ONLY = set("әңөұһ")  # нет ни в узбекской, ни в украинской кириллице
_UZ_CYR = set("ўқғҳ")
_UA_LETTERS = set("іїєґ")

_KK_WORDS = set("""
және маған саған оған бұл осы жоқ керек емес үшін деп неге қалай қашан қайда кім
ойын ойыншы әкімші шағым көмек көмектесіңіз рахмет сәлем сәлеметсіз өтінемін берді
ұрды өлтірді сөкті балағаттады анамды әкемді туыстарымды себепсіз мені сені оны
жаза ақша ғой ғана күн күнге осындай деген бул бар жоқ берді берші беріңдер
""".split())

_UZ_WORDS = set("""
va men meni mani menga manga sen seni u uni bu shu nima nega qanday qachon qayerda kim
uchun bilan emas yoq yo'q bor kerak iltimos rahmat salom assalomu alaykum assalomaleykum
asalomu aleykum o'yinchi oyinchi o'yin oyin shikoyat admin adminlar administrator
qildi qilib qilyapti qilaman qilyapdi berdi beryapti berdilar berizla oldirdi o'ldirdi
uldirdi otdi urdi sokdi so'kdi sokindi so'kindi sukindi onamni onadan onamdan onasini
ota sababsiz be sabab hech yordam bering yordam bervoring jazo ban mute warn
qamadi qamoqqa kishan moshina mashina pul aldadi aldab ham lekin chunki endi hozir
iltimos qoidabuzarlik dalil dalillar video skrin
""".split())

_EN_WORDS = set("""
the and is are was were you your me my he she they him her it this that please help
stuck why what how where when can could admin kill killed insult insulted player cheat
cheater hacker hack account banned ban unban money pay paid not don't dont no yes
""".split())
_ES_WORDS = set("""
el la los las que por favor ayuda ayudame me mi tu es esta estoy jugador mato insulto
porque como donde cuando cuenta dinero pague no si gracias hola administrador
""".split())
_PT_WORDS = set("""
o a os as que por favor ajuda me meu minha voce você é está estou jogador matou
xingou porque como onde quando conta dinheiro paguei não sim obrigado olá oi
administrador
""".split())

# Русский транслитом и игровой сленг: латиница, но отвечать надо по-русски.
_RU_TRANSLIT = set("""
osk oskorblenie oskorbil rod rodni rodnyu mat dm db tk sk soft cheat chit fraps nonrp
nrp pg mg rk gz op pomogite pomogi pzh pls plz zastryal ubil ubivaet admin adm ban
mut mute varn warn skam scam kop koptsy pochemu kak gde privet spasibo nakazanie
""".split())

_TOKEN = re.compile(r"[a-zа-яёәғқңөұүһіїєґўҳ'ʻʼ‘’`]+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    t = for_matching(text)
    t = re.sub(r"<(url|email|handle|digits|nick)>", " ", t)
    t = t.replace("ʻ", "'").replace("ʼ", "'").replace("‘", "'").replace("’", "'").replace("`", "'")
    return _TOKEN.findall(t)


def detect(text: str, server_lang: str | None = None) -> str:
    """Возвращает ru | kk | uz | en | es | pt | uk | und."""
    toks = _tokens(text)
    letters = [ch for ch in for_matching(text) if ch.isalpha()]
    if not letters or not toks:
        return "und"
    cyr = sum(1 for ch in letters if "а" <= ch <= "я" or ch in "ёәғқңөұүһіїєґўҳ")
    lat = sum(1 for ch in letters if "a" <= ch <= "z")
    chars = set(letters)

    if cyr >= lat:
        kk_hits = sum(1 for w in toks if w in _KK_WORDS)
        kk_letters = sum(1 for ch in letters if ch in "әғқңөұүһ")
        # әңөұһ не бывают в русском и украинском: даже одной такой буквы достаточно («Төлем жасадым»)
        kk_only = sum(1 for ch in letters if ch in _KK_ONLY)
        if kk_letters >= 2 or kk_only >= 1 or (kk_letters == 1 and kk_hits >= 1) or kk_hits >= 2:
            # «қ», «ғ» есть и в узбекской кириллице
            if chars & {"ў", "ҳ"} and not chars & _KK_ONLY:
                return "uz"
            return "kk"
        if chars & _UZ_CYR:
            return "uz"
        if chars & _UA_LETTERS or "'" in "".join(toks) and any(w in {"що", "мені", "будь", "ласка"} for w in toks):
            return "uk"
        return "ru"

    scores = {
        "uz": sum(1 for w in toks if w in _UZ_WORDS or w.endswith(("ni", "ga", "da", "dan", "mi", "lar", "yapti", "yapdi", "dim", "di"))
                  and w not in _EN_WORDS and len(w) > 3),
        "en": sum(1 for w in toks if w in _EN_WORDS),
        "es": sum(1 for w in toks if w in _ES_WORDS),
        "pt": sum(1 for w in toks if w in _PT_WORDS),
        "ru": sum(1 for w in toks if w in _RU_TRANSLIT),
    }
    if "o'" in text.lower() or "g'" in text.lower() or "oʻ" in text or "gʻ" in text:
        scores["uz"] += 2
    if server_lang == "uz":
        scores["uz"] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        # одни коды правил и ссылки: ответ на языке сервера
        return {"uz": "uz", "kk": "ru"}.get(server_lang or "", "ru") if lat else "und"
    if best in ("es", "pt") and scores["es"] == scores["pt"]:
        return "pt" if any(ch in text for ch in "ãõç") else "es"
    return best


def reply_lang(text_lang: str, server_lang: str | None = None) -> str:
    """Язык черновика. Украинский и неопределённый уходят в язык сервера,
    казахский сервер без казахского текста отвечает по-русски, как и админы."""
    if text_lang in SUPPORTED_REPLY:
        return text_lang
    if text_lang == "uk":
        return "ru"
    if server_lang == "uz":
        return "uz"
    return "ru"
