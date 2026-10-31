"""Категории и приоритеты: правила по taxonomy.json.

label_rules() используется в двух местах:
1. Как слабая разметка train: там есть исход из ответа админа (violation,
   verdict), он сильнее текста игрока, потому что игроки ошибаются с пунктами.
2. Как запасной классификатор в рантайме, если модель не уверена.
"""
from __future__ import annotations

import re

from .signals import Signals

COMPLAINT_CATS = [
    "complaint.insult", "complaint.cheat", "complaint.dm", "complaint.scam", "complaint.rmt_ads",
    "complaint.admin", "complaint.other", "complaint.invalid",
]
REPORT_CATS = [
    "report.question", "report.help", "report.complaint", "report.account", "report.payment", "report.offtopic",
]
ALL_CATS = COMPLAINT_CATS + REPORT_CATS
PRIORITIES = ["p0", "p1", "p2", "p3"]
# названия категорий для интерфейса и поиска по названию
CATEGORY_LABELS = {
    "complaint.insult": "Оскорбление", "complaint.cheat": "Читы и сторонний софт", "complaint.dm": "Убийство без причины",
    "complaint.scam": "Мошенничество", "complaint.rmt_ads": "Реклама и продажа за реальные деньги",
    "complaint.admin": "Жалоба на администратора", "complaint.invalid": "Некорректная жалоба", "complaint.other": "Другое",
    "report.account": "Аккаунт и взлом", "report.complaint": "Жалоба в репорте", "report.help": "Просьба о помощи",
    "report.offtopic": "Оффтоп", "report.payment": "Платёж и донат", "report.question": "Вопрос игрока",
}

# пункт правил -> категория жалобы
_REF_TO_CAT = {
    "2.1": "complaint.insult", "2.2": "complaint.insult", "2.4": "complaint.insult", "2.6": "complaint.insult",
    "5.2": "complaint.cheat",
    "4.1": "complaint.scam", "4.2": "complaint.scam",
    "2.3": "complaint.rmt_ads", "4.4": "complaint.rmt_ads",
    "5.1": "complaint.dm", "5.1.1": "complaint.dm", "5.3": "complaint.dm", "5.4": "complaint.dm",
    "5.4.1": "complaint.dm", "5.5": "complaint.dm",
    "3.4": "complaint.admin",
    "1.6": "complaint.other", "5.6": "complaint.other", "5.7": "complaint.other", "5.8": "complaint.other",
    "5.9": "complaint.other", "2.5": "complaint.other", "3.2": "complaint.other", "3.3": "complaint.other",
    "1.2": "complaint.other", "4.3": "complaint.other", "4.5": "complaint.other", "4.6": "complaint.other",
    "4.7": "complaint.other", "4.8": "complaint.other",
}
# разделы с РП-нарушениями: зелёная зона, госорганизации, семьи, ОПГ, бизвар, фургон
_RP_PREFIXES = ("GZ ", "ПГО ", "ФВ ", "ОПГ ", "БВБ ", "ПБФ ", "ПЛ ", "ГВ ")


def ref_category(cite: str) -> str | None:
    if cite in _REF_TO_CAT:
        return _REF_TO_CAT[cite]
    if cite.startswith(_RP_PREFIXES):
        return "complaint.dm"
    if cite.startswith("ЖБ "):
        return None
    return None


_TOPIC_ORDER = [("rmt_ads", "complaint.rmt_ads"), ("cheat", "complaint.cheat"), ("scam", "complaint.scam"),
                ("insult", "complaint.insult"), ("dm", "complaint.dm")]

_OUTCOME_CODE = re.compile(r"(\d+(?:\.\d+)+)\s*([a-zа-яё]*)", re.I)


def outcome_category(violation: str | None, rule_base) -> str | None:
    if not violation:
        return None
    for cite in rule_base.parse_refs(violation):
        cat = ref_category(cite)
        if cat:
            return cat
    v = violation.lower()
    if re.search(r"\bdm\b|\bдм\b|nonrp|нонрп|non rp|\bdb\b|\bдб\b|\bsk\b|\bск\b|\btk\b|\bтк\b", v):
        return "complaint.dm"
    return None


# явный взлом: слово «верните» из stuck-признака рядом с ним не превращает репорт в просьбу о помощи
_HIJACK = re.compile(r"взлом|украл\w*\s+(?:мо\w+\s+)?(?:акк|машин|дом|деньг|бизнес|имущ)|(?:зашел|зашёл|залез|вошел|вошёл|влез|заходил|зашли|вошли)\s+(?:\w+\s+){0,2}?(?:в|на)\s+(?:мо\w+\s+)?(?:аккаунт|акк\b)")


def label_rules(kind: str, sig: Signals, text: str, verdict: str | None = None,
                violation: str | None = None, rule_base=None) -> str:
    t = text.lower()
    if kind == "complaint":
        if verdict in ("appeal_rejected", "appeal_approved"):
            return "complaint.admin"
        if "appeal" in sig.topics:
            return "complaint.admin"
        if sig.content_free or (sig.words == 0 and not sig.rule_refs):
            return "complaint.invalid"
        if rule_base is not None:
            oc = outcome_category(violation, rule_base)
            if oc and oc != "complaint.admin":
                return oc
        if "admin_subject" in sig.topics:
            return "complaint.admin"
        # пункт, который назвал сам игрок, если он согласуется с текстом
        topic_cats = [cat for topic, cat in _TOPIC_ORDER if topic in sig.topics]
        ref_cats = [c for c in (ref_category(r) for r in sig.rule_refs) if c]
        for c in ref_cats:
            if not topic_cats or c in topic_cats:
                return c
        if topic_cats:
            return topic_cats[0]
        if ref_cats:
            return ref_cats[0]
        if "admin" in sig.topics:
            return "complaint.admin"
        if "question" in sig.topics or "greeting_offtopic" in sig.topics or sig.words <= 2:
            return "complaint.invalid"
        if verdict in ("rejected", "invalid_format") and sig.words <= 4:
            return "complaint.invalid"
        return "complaint.other"

    # report
    if "payment" in sig.topics:
        return "report.payment"
    if "account" in sig.topics and not ("stuck" in sig.topics and not _HIJACK.search(t)):
        return "report.account"
    if "threat_irl" in sig.topics:
        return "report.complaint"
    if "stuck" in sig.topics and re.search(r"сним|переверн|вытащ|(до|да)ста|почин|спавн|респ|\bтп\b|телепорт|застрял", t) \
            and not sig.topics & {"insult", "cheat", "scam"}:
        return "report.help"
    if sig.topics & {"insult", "dm", "cheat", "scam", "rmt_ads"} or (sig.player_id and sig.words >= 1 and "stuck" not in sig.topics):
        return "report.complaint"
    if "stuck" in sig.topics:
        return "report.help"
    if "question" in sig.topics and sig.words >= 2:
        return "report.question"
    if sig.content_free or "greeting_offtopic" in sig.topics or ("help_word" in sig.topics and sig.words <= 3):
        return "report.offtopic"
    if sig.words >= 4:
        return "report.question"
    return "report.offtopic"


def priority_rules(category: str, sig: Signals) -> str:
    if category in ("report.account", "report.payment"):
        return "p0"
    if sig.topics & {"threat_irl", "mass_issue"}:
        return "p0"
    if category in ("complaint.cheat", "complaint.scam", "complaint.rmt_ads"):
        return "p1"
    if category == "report.complaint" and sig.topics & {"cheat", "scam", "rmt_ads"}:
        return "p1"
    if category in ("complaint.invalid", "report.question", "report.offtopic"):
        return "p3"
    return "p2"
