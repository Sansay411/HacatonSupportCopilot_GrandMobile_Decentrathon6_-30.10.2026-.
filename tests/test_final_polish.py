"""Финальная полировка: шаблоны без неподтверждённых утверждений и благодарностей, краткость, язык ответа, базовый поиск пункта.

Проверки идут по всем шести языкам и по всем шаблонам i18n.T, а не по отдельным примерам.
"""
from __future__ import annotations

import re
import shutil

import pytest

from copilot import guard, i18n, lang
from copilot.pipeline import Copilot
from tests.support import FIXTURE_RULES

LANGS = ["ru", "kk", "uz", "en", "es", "pt"]
# вариант appeal_reject выбирает администратор, проверивший наказание: он единственный объявляет итог и закрытие
EXCEPT_FOR_ADMIN_CHOICE = {"appeal_reject"}

THANKS = re.compile(r"спасибо|благодар|рахмет|rahmat|thank|gracias|obrigad", re.I)
CLOSED = re.compile(r"жалоба закрыта|шағым жабылды|shikoyat yopildi|is closed|está cerrada|está encerrada", re.I)
# сервис не видит вложения: «по приложенным материалам видно» это неподтверждённая проверка доказательств
EVIDENCE_CHECKED = re.compile(
    r"по приложенным материалам|по скриншот|видно нарушение|тіркелген материалдардан|ilova qilingan materiallarda|"
    r"attached materials show|materiales adjuntos muestran|materiais anexados mostram", re.I)
# сервис не знает, кто сейчас в сети и что происходит на сервере
PRESENCE = re.compile(
    r"на связи|aloqada|байланыста|сейчас постарается|is on it|está atento|está acompanhando|hozir yordam|қазір көмек|"
    r"оставайтесь на месте|stay where you are|quédate donde|fique onde|орныңыздан кетпеңіз|joyingizdan ketmang", re.I)
FILLER = re.compile(r"следите за объявлениями|хабарландыруларын қадағалаңыз|e.lonlarini kuzatib|watch for administrator announcements|"
                    r"atento a los anuncios|acompanhe os anúncios", re.I)

SAMPLES = dict(cite="п. 2.1 Общих правил", cite_gen="2.1", title="тест", nick_part="", sanction="мут", term="DM", what="",
               cite_req="п. 1.3.1", cite_platform="п. 1.2.1", cite_time="п. 1.2.6", pid_part="", support="https://s", discord="https://d")


def render(l: str, key: str) -> str:
    out = i18n.T[l][key]
    for k, v in SAMPLES.items():
        out = out.replace("{" + k + "}", v)
    return out


@pytest.mark.parametrize("l", LANGS)
def test_templates_have_no_thanks_closure_or_unverified_claims(l):
    for key in i18n.T[l]:
        if key in EXCEPT_FOR_ADMIN_CHOICE or key in ("hello", "bye", "cite", "what", "nick_part", "pid_part"):
            continue
        text = render(l, key)
        for name, rx in (("благодарность", THANKS), ("закрытие", CLOSED), ("проверка вложений", EVIDENCE_CHECKED),
                         ("присутствие админа", PRESENCE), ("общая фраза", FILLER)):
            assert not rx.search(text), f"{l}.{key}: {name}: {text}"
        assert not guard.claims_action(text), f"{l}.{key}: утверждение о действии: {text}"


@pytest.fixture()
def cp(tmp_path):
    shutil.copy(FIXTURE_RULES, tmp_path / "rules.json")
    return Copilot(tmp_path, tmp_path / "no_models")


def ask(cp, kind, text, server_lang=None, att=1, nick=None):
    p = {"kind": kind, "messages": [{"role": "player", "text": text, "attachments": att}], "reporter_hash": "r-polish"}
    if server_lang:
        p["server_lang"] = server_lang
    if nick:
        p["reported_nick"] = nick
    return cp.triage(p, use_dedup=False)


@pytest.mark.parametrize("l,text", [("ru", "Bad_Guy оскорблял меня в чате, скрины есть, 2.1 ОП"),
                                    ("kk", "Bad_Guy мені чатта балағаттады, скриншот бар, 2.1"),
                                    ("uz", "Bad_Guy meni chatda haqorat qildi, skrinshot bor, 2.1")])
def test_approve_is_short_and_states_only_what_the_service_knows(cp, l, text):
    r = ask(cp, "complaint", text, l, att=2)
    d = r["draft_reply"]["text"]
    assert r["_meta"]["intent"] == "approve" and r["needs_human"] is True
    assert len(d) <= 240, d       # было 230: срок словами («15 dan 30 daqiqagacha») на 9 знаков длиннее тире
    assert not EVIDENCE_CHECKED.search(d) and not THANKS.search(d) and not CLOSED.search(d)
    assert "2.1" in d and r["draft_reply"]["cited"] == ["2.1"]                  # конкретный пункт остаётся


def test_short_scenarios_stay_short_in_the_three_main_languages(cp):
    caps = {"report_watch": 125, "help_ack": 100, "event_tp": 85}
    cases = {"report_watch": ("report", "Ivan_Test [123] читерит, проследите"),
             "help_ack": ("report", "помогите пожалуйста"), "event_tp": ("report", "+")}
    for intent, (kind, text) in cases.items():
        r = ask(cp, kind, text, "ru", att=0)
        assert r["_meta"]["intent"] == intent, (intent, r["_meta"]["intent"])
        assert len(r["draft_reply"]["text"]) <= caps[intent], (intent, r["draft_reply"]["text"])
        assert r["needs_human"] is True


def test_event_teleport_and_help_do_not_state_server_or_admin_state(cp):
    for text in ("+", "помогите пожалуйста", "помоги", "Ivan_Test [123] читерит"):
        d = ask(cp, "report", text, "ru", att=0)["draft_reply"]["text"]
        assert not PRESENCE.search(d) and not FILLER.search(d), d


# ---------------------------------------------------------------- язык ответа
@pytest.mark.parametrize("text,server,expected", [
    ("Ivan_Test [123] чит қолданып жатыр", "kk", "kk"),              # одна «қ» без других примет раньше давала uz
    ("Ivan_Test [123] чит қолданып жатыр", None, "kk"),
    ("ойында чит ғана қолданады", None, "kk"),
    ("Ў ўйинчи қоидани бузди", None, "uz"),                          # «ў» есть только в узбекской кириллице
    ("хато бузилиш қилди", "uz", "uz"),                              # сервер uz: узбекская кириллица
    ("жалоба на игрока, он читерит", "kk", "ru"),                    # казахский сервер, русский текст: по-русски
])
def test_kazakh_and_uzbek_cyrillic_are_told_apart(text, server, expected):
    assert lang.detect(text, server) == expected


def test_kazakh_report_with_a_latin_nick_is_answered_in_kazakh(cp):
    r = ask(cp, "report", "Ivan_Test [123] чит қолданып жатыр", "kk", att=0)
    assert r["draft_reply"]["lang"] == "kk" and r["lang"] == "kk"


# ---------------------------------------------------------------- базовый поиск пункта
def test_rule_search_stays_conservative_on_the_prelabeled_set():
    """Действующий поиск не выдаёт пункт там, где его нет; этот тест ловит смягчение порога без измеренного выигрыша.
    Эксперимент и сравнение с кандидатом: experiments/final_polish/rag_eval.py (кандидат не принят, см. docs/audit/FINAL_POLISH.md)."""
    from tests.support import HAS_DATA, ROOT
    if not HAS_DATA:
        pytest.skip("нужны реальные rules.json")
    import sys
    sys.path.insert(0, str(ROOT / "experiments" / "final_polish"))
    import rag_eval
    from copilot.rules import load
    rb = load(str(ROOT / "data" / "rules.json"))
    out, _ = rag_eval.evaluate("baseline", rag_eval.baseline, rb)
    assert out["false_on_neg"] == 0, out
    assert out["false_cites_total"] <= 1, out
    assert out["precision"] is None or out["precision"] >= 0.8, out


# ---------------------------------------------------------------- база знаний отвечает на вопрос о маршруте, а не на упоминание темы
@pytest.mark.parametrize("text", [
    "в казино у входа затеяли драку",                     # упоминание темы, а не вопрос
    "в церкви сейчас идёт чья-то свадьба",
    "на авторынке снова стоят пустые стенды",
    "мой скутер уехал без меня",
    "почему отклонили оформление при продаже авто",
    "когда будет обнова штрафы",
])
def test_kb_does_not_answer_a_topic_mention(text):
    from copilot import kb
    assert kb.lookup(text, "ru") is None


@pytest.mark.parametrize("text,key", [
    ("где церковь", "wedding"),
    ("как найти аренду скутера", "scooter"),
    ("как мне получить лицензию на оружие", "weapon_license"),
    ("как пожениться", "wedding"),
    ("где оплатить штраф", "fines"),
    ("что значит ДМ", "rules"),
    ("qurol litsenziyasi qayerda olinadi", "weapon_license"),
])
def test_kb_still_answers_route_questions(text, key):
    from copilot import kb
    hit = kb.lookup(text, "ru")
    assert hit is not None and hit[1].key == key, (text, hit)


def test_topic_mention_in_a_question_report_is_not_auto_answered_from_kb():
    from copilot import drafts
    from copilot.rules import load
    from copilot.signals import Signals
    rb = load(str(FIXTURE_RULES))
    sig = Signals(topics={"question"}, words=5)
    d = drafts.build("report", "report.question", sig, "в казино у входа затеяли драку", "ru", rb, None, None, False)
    assert d.intent != "question_kb"
