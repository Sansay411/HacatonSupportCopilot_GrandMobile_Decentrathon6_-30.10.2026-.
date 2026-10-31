"""База знаний для вопросов по механике: только то, что админы реально отвечали.

Записи собраны из ответов администраторов на репорты в train (50 582 репорта):
ответы с маршрутом в навигаторе и с инструкциями сгруппированы, в базу попали
темы, которые подтверждены минимум двумя независимыми ответами админов.
Поле support хранит число таких ответов, оно попадает в reasons.
Нумерация пунктов меню в ответах админов разная на разных серверах,
поэтому в базе только названия разделов.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .textnorm import for_matching


@dataclass(frozen=True)
class KBEntry:
    key: str
    pattern: str
    path: str | None          # маршрут в навигаторе (GPS)
    answer: dict | None       # готовый ответ по языкам, если это не маршрут
    support: int


KB: list[KBEntry] = [
    KBEntry("weapon_license", r"лиценз\w* на оруж|оружейн\w* лиценз|litsenziya|qurol|паспорт\w*|выйти\W+(?:из\W+|с\W+)?(?:фам|семь)|ливнуть\W+(?:из\W+|с\W+)?(?:фам|семь)|покинуть\W+(?:фам|семь)|pasport|төлқұжат|weapon\s+licen[sc]e", "Государственные организации > Правительство", None, 32),
    KBEntry("fines", r"штраф|jarima|айыппұл|\bfines?\b", "Государственные организации > Полиция", None, 11),
    KBEntry("tuning", r"тюнинг|\bсто\b|дрифт ?мод|покрас|фары|tyuning", "Автосалоны / стоянки > СТО", None, 8),
    KBEntry("car_market", r"(прода\w*|прод\w*ть|купить|sotib|sotish|сатып|сату|\bbuy\b|\bsell\b)\W+(\w+\W+)?(машин|тачк|авто|mashin|moshin|көлік|\bcar\b)|(?:машин\w*|тачк\w*|авто|mashin\w*|moshin\w*|көлік\w*)\W+(?:\w+\W+){0,3}?(?:sotib|sotish|сатып|сату)|авторын|б/?у рын|avtobozor|mashina\s+bozor|көлік\s+базар", "Общественные места > Авторынок", None, 6),
    KBEntry("driving_school", r"автошкол|на права|сдать на прав|сдавать на прав|права получ|получить права|получения прав|права на (?:воздуш|вертол|самол|мото|легков|груз|машин|авто|катер|лодк)|avtomaktab|\bprava\b|автомектеп|жүргізуші\s+куәліг|driving\s+school|driver'?s?\s+licen[sc]e", "Общественные места > Автошкола", None, 5),
    KBEntry("shops", r"магазин (одежд|оруж)|кирк|патрон|kiyim\s+do['ʻ’‘]?kon|qurol\s+do['ʻ’‘]?kon|киім\s+дүкен|қару\s+дүкен", "Бизнесы", None, 9),
    KBEntry("casino", r"казино|казик|колесо удач|kazino|\bcasino\b", "Развлечения > Grand Casino", None, 3),
    KBEntry("my_cars", r"(где|как)\W+(\w+\W+)?(мои машин|моя машин|посмотреть мои машин|найти (мою )?машин)", "Автосалоны / стоянки > Стоянка", None, 3),
    KBEntry("wedding", r"жени|пожени|свадьб|церк|nikoh|to['ʻ’‘]?y|үйлен|той\b", "Общественные места > Церковь", None, 3),
    KBEntry("trucker", r"дальнобо|dalnoboy|жүк\s+көліг", "Работы > Дальнобойщик", None, 2),
    KBEntry("black_market", r"ч[её]рн\w* рын|qora\s+bozor|қара\s+базар", "Криминальные организации > Чёрный рынок", None, 2),
    KBEntry("notary", r"нотари|натари|notarius", "Нотариальное агентство", None, 2),
    KBEntry("scooter", r"скутер|аренд\w* (мото|скут)|skuter", "Вокзалы", None, 2),
    KBEntry("taxes", r"налог|опла[тч]\w* (за )?(квартир|дом)|квартплат|soliq|салық", "Общественные места > Банк", None, 2),
    KBEntry("hospital", r"где\W+(\w+\W+)?больниц|медицинск\w* страхов|shifoxona|kasalxona|аурухана", "Государственные организации > Больница", None, 2),
    KBEntry("mine_quarry", r"каменоломн|шахт[аеуы]\b|kamenolomn|shaxta|шахта", "Начальные работы > Шахта", None, 22),
    KBEntry("factory", r"\bзавод\w*|zavod|зауыт", "Начальные работы > Завод", None, 14),
    KBEntry("military_office", r"военкомат|военн\w*\s+билет|voyenkomat|harbiy\s+bilet|әскери\s+билет", "Общественные места > Военкомат", None, 25),
    KBEntry("rules", r"(что (значит|означает)|где (почитать|посмотреть|найти) правил|правила|како[еяй]\W+наказани\w*\W+за|что\W+будет\W+если\W+(?:\w+\W+){0,5}?(?:варн|бан|мут|дм|дб|ск|тк|рк|фсб|мвд|арми|опг))", None, {
        "ru": "С правилами проекта можно ознакомиться в лаунчере игры.",
        "kk": "Жоба ережелерімен ойын лаунчерінде танысуға болады.",
        "uz": "Loyiha qoidalari bilan o‘yin launcherida tanishishingiz mumkin.",
        "en": "You can read the project rules in the game launcher.",
        "es": "Puedes leer las reglas del proyecto en el launcher del juego.",
        "pt": "Você pode ler as reglas do projeto no launcher do jogo.",
    }, 22),
]

_PATH_TPL = {
    "ru": "Откройте навигатор (GPS): {path}.",
    "kk": "Навигаторды (GPS) ашыңыз: «{path}».",
    "uz": "Navigatorni (GPS) oching: «{path}».",
    "en": "Open the navigator (GPS): \"{path}\".",
    "es": "Abre el navegador (GPS): «{path}».",
    "pt": "Abra o navegador (GPS): \"{path}\".",
}


# Вопрос о том, где что находится и как что-то сделать. Одного слова темы мало: «админ, в казино стрельба» и «у нас свадьба»
# получали маршрут к казино и церкви без человека. На train (50 582 репорта) совпадение с маршрутом админа было у 18 % ответов,
# после этого условия оно выросло, а число ответов упало (цифры: docs/audit/FINAL_POLISH.md, раздел 2).
_ASKS_HOW_OR_WHERE = re.compile(
    r"\bгде\b|\bкуда\b|\bоткуда\b"
    r"|\bкак\W+(?:\w+\W+){0,3}?(?:найти|найду|добраться|доехать|попасть|пройти|получить|получу|купить|куплю|продать|продам|сдать|сдавать|"
    r"арендовать|взять|открыть|оплатить|оплачивать|заплатить|платить|жениться|пожениться|записаться|устроиться|устроится|работать|поработать|"
    r"выйти|ливнуть|уйти|покинуть)"
    r"|\bчто\W+(?:такое|значит|означает)\b"
    r"|\bкако[еяй]\W+(?:наказани\w*|штраф\w*)\b|\bчто\W+будет\W+если\b"
    r"|\bqayer\w*|\bqanday\b|қайда|қалай|\bwhere\b|\bhow\s+(?:do|can|to)\b"
    r"|sotib\s+ol\w*|sotish\w*|olish\w*|o['ʻ’‘]?tish|ishga\s+kir\w*|ауыстыр\w*|сатып\s+ал\w*|сату\w*|алу\w*|тапсыр\w*|жұмысқа\s+тұр\w*|\bbuy\b|\bsell\b|\bget\b|\bfind\b|\bpay\b", re.I)

_INJECTION_GUARD = re.compile(
    r"\bsystem\s*:|\b(?:забудь|игнорируй|отмени|обойди)\s+(?:(?:все|предыдущие|свои)\s+){0,2}(?:правила|инструкци\w*|ограничени\w*|указани\w*)"
    r"|\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|rules|prompts)",
    re.I,
)


def lookup(text: str, lang: str) -> tuple[str, KBEntry] | None:
    t = for_matching(text)
    if _INJECTION_GUARD.search(t):
        return None
    if not _ASKS_HOW_OR_WHERE.search(t):
        return None
    for e in KB:
        if re.search(e.pattern, t):
            if e.path:
                return _PATH_TPL.get(lang, _PATH_TPL["ru"]).format(path=e.path), e
            return e.answer.get(lang, e.answer["ru"]), e
    return None
