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
    KBEntry("weapon_license", r"лиценз\w* на оруж|оружейн\w* лиценз|litsenziya|qurol", "Государственные организации > Правительство", None, 20),
    KBEntry("fines", r"штраф", "Государственные организации > Полиция", None, 11),
    KBEntry("tuning", r"тюнинг|\bсто\b|дрифт ?мод|покрас|фары", "Автосалоны / стоянки > СТО", None, 8),
    KBEntry("car_market", r"(прода\w*|прод\w*ть|купить)\W+(\w+\W+)?(машин|тачк|авто)|авторын|б/?у рын", "Общественные места > Авторынок", None, 6),
    KBEntry("driving_school", r"автошкол|на права|сдать на прав|сдавать на прав|права получ", "Общественные места > Автошкола", None, 5),
    KBEntry("shops", r"магазин (одежд|оруж)|кирк|патрон", "Бизнесы", None, 9),
    KBEntry("casino", r"казино|казик|колесо удач", "Развлечения > Grand Casino", None, 3),
    KBEntry("my_cars", r"(где|как)\W+(\w+\W+)?(мои машин|моя машин|посмотреть мои машин|найти (мою )?машин)", "Автосалоны / стоянки > Стоянка", None, 3),
    KBEntry("wedding", r"жени|пожени|свадьб|церк", "Общественные места > Церковь", None, 3),
    KBEntry("trucker", r"дальнобо", "Работы > Дальнобойщик", None, 2),
    KBEntry("black_market", r"ч[её]рн\w* рын", "Криминальные организации > Чёрный рынок", None, 2),
    KBEntry("notary", r"нотари|натари", "Нотариальное агентство", None, 2),
    KBEntry("scooter", r"скутер|аренд\w* (мото|скут)", "Вокзалы", None, 2),
    KBEntry("taxes", r"налог|опла[тч]\w* (за )?(квартир|дом)|квартплат", "Общественные места > Банк", None, 2),
    KBEntry("hospital", r"где\W+(\w+\W+)?больниц|медицинск\w* страхов", "Государственные организации > Больница", None, 2),
    KBEntry("rules", r"(что (значит|означает)|где (почитать|посмотреть|найти) правил|правила)", None, {
        "ru": "С правилами проекта можно ознакомиться в лаунчере игры.",
        "kk": "Жоба ережелерімен ойын лаунчерінде танысуға болады.",
        "uz": "Loyiha qoidalari bilan o‘yin launcherida tanishishingiz mumkin.",
        "en": "You can read the project rules in the game launcher.",
        "es": "Puedes leer las reglas del proyecto en el launcher del juego.",
        "pt": "Você pode ler as regras do projeto no launcher do jogo.",
    }, 15),
]

_PATH_TPL = {
    "ru": "Откройте навигатор (GPS): {path}.",
    "kk": "Навигаторды (GPS) ашыңыз: «{path}».",
    "uz": "Navigatorni (GPS) oching: «{path}».",
    "en": "Open the navigator (GPS): \"{path}\".",
    "es": "Abre el navegador (GPS): «{path}».",
    "pt": "Abra o navegador (GPS): \"{path}\".",
}


def lookup(text: str, lang: str) -> tuple[str, KBEntry] | None:
    t = for_matching(text)
    for e in KB:
        if re.search(e.pattern, t):
            if e.path:
                return _PATH_TPL.get(lang, _PATH_TPL["ru"]).format(path=e.path), e
            return e.answer.get(lang, e.answer["ru"]), e
    return None
