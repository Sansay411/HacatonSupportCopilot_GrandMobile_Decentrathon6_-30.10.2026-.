"""Регрессии по аудиту качества черновиков (31.10.2026, docs/audit/DRAFT_QUALITY.md).

Каждый тест закрепляет подтверждённую проблему. Основные работают на тестовых правилах без ML-моделей (категорию задают
правила taxonomy), поэтому проходят в чистом окружении без data/ и models/; тесты на реальной базе и моделях пропускаются
без них.
"""
import re
import shutil
import sys

import pytest

from support import FIXTURE_RULES, HAS_DATA, ROOT
from copilot import drafts, guard, i18n
from copilot.pipeline import Copilot
from copilot.signals import Signals, extract

sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
from draft_probes import PROBES  # noqa: E402

# итог «наказание выдано верно» нельзя утверждать: сервис наказание не проверял
SETTLED = re.compile(
    r"выдано верно|оснований для (его )?снятия нет|jazo to‘g‘ri berilgan|жаза дұрыс берілген|penalty was issued correctly|"
    r"sanción se aplicó correctamente|punição foi aplicada corretamente", re.I)
# независимый список обещаний (не импортирует copilot.guard)
PROMISE = re.compile(
    r"будет снят|будут возвращ|разбаним|вернём|вернем|компенсируем|накажем|будет наказан|гарантируем|снимем|"
    r"olib tashlaymiz|qaytaramiz|jazolaymiz|қайтарамыз|алып тастаймыз|жазалаймыз|we will (unban|refund|ban|punish)", re.I)


@pytest.fixture(scope="module")
def cp(tmp_path_factory):
    d = tmp_path_factory.mktemp("draft-audit")
    shutil.copy(FIXTURE_RULES, d / "rules.json")
    return Copilot(data_dir=d, models_dir=d / "нет")


def triage(cp, kind, text, *, lang=None, images=1, **extra):
    payload = {"kind": kind, "messages": [{"role": "player", "text": text}]}
    if kind == "complaint":
        payload["images_count"] = images
    if lang:
        payload["server_lang"] = lang
    payload.update(extra)
    return cp.triage(payload, use_dedup=False)


def intent(r):
    return r["_meta"]["intent"]


def text(r):
    return r["draft_reply"]["text"]


# ------------------------------------------------------------- 1. обжалование: итог не утверждаем
APPEAL_CASES = [
    ("не согласен с наказанием, снимите бан", None),
    ("опру", None),
    ("за что мне бан? я ничего не делал", None),
    ("ban nohaq berildi, yechib bering", "uz"),
    ("жазамен келіспеймін, банды алып тастаңыздар", "kk"),
    ("I disagree with the ban, I did not cheat", None),
]


@pytest.mark.parametrize("msg,lang", APPEAL_CASES)
def test_appeal_draft_does_not_assert_a_decision(cp, msg, lang):
    r = triage(cp, "complaint", msg, lang=lang)
    assert intent(r) == "appeal", (msg, intent(r))
    assert not SETTLED.search(text(r))
    assert r["needs_human"] is True
    assert set(r["draft_reply"]["cited"]) <= {"ЖБ 1.3.1", "ЖБ 1.2.6"}


def test_appeal_reject_stays_available_as_alternative(cp):
    r = triage(cp, "complaint", "не согласен с наказанием, снимите бан")
    alts = {a["intent"]: a for a in r["_meta"]["alternatives"]}
    assert "appeal_reject" in alts and SETTLED.search(alts["appeal_reject"]["text"])


@pytest.mark.parametrize("lang", ["ru", "kk", "uz", "en", "es", "pt"])
def test_appeal_templates_neutral_in_every_language(lang, rb):
    sig = Signals(topics={"appeal"}, words=5)
    d = drafts.build("complaint", "complaint.admin", sig, "не согласен с наказанием", lang, rb, "approve", None, False)
    assert d.intent == "appeal" and not SETTLED.search(d.text) and d.auto_ok is False
    assert any(a["intent"] == "appeal_reject" for a in d.alternatives)


@pytest.mark.parametrize("msg", ["почему бан? поясните", "когда снимете бан?", "за что мут, объясните"])
def test_question_about_own_penalty_is_not_deflected_to_discord(cp, msg):
    r = triage(cp, "complaint", msg)
    assert intent(r) == "appeal", (msg, intent(r))
    assert "Discord" not in text(r) and r["needs_human"] is True


def test_accusation_of_bribery_is_an_admin_complaint_not_an_appeal(cp):
    r = triage(cp, "complaint", "администратор берёт взятки за разбан")
    assert intent(r) == "admin_complaint" and r["needs_human"] is True


# ------------------------------------------------------------- 2. отрицания
@pytest.mark.parametrize("msg", ["я не оскорблял, он врёт", "я даже не убивал его", "я играю без читов, это просто лаги"])
def test_first_person_denial_is_not_confirmed_as_violation(cp, msg):
    r = triage(cp, "complaint", msg)
    assert intent(r) not in ("approve", "need_evidence"), (msg, intent(r))
    assert intent(r) == "appeal" and r["needs_human"] is True


def test_third_person_denial_asks_to_clarify(cp):
    r = triage(cp, "complaint", "это не читер, он просто хорошо играет")
    assert intent(r) == "clarify" and r["needs_human"] is True
    assert "стороннее ПО" not in text(r)


@pytest.mark.parametrize("msg", [
    "он не отстаёт, матерится в чате",
    "он оскорбил мою родню, я ничего не писал в ответ",
    "он не оскорблял меня, но написал гадости про мою мать",
    "не успел записать видео, он оскорбляет меня",
    "Он написал, что это не скам, я передал машину за ключи, а он ушёл",     # пересказ чужих слов, а не отрицание
])
def test_negation_elsewhere_does_not_hide_a_real_violation(cp, msg):
    assert intent(triage(cp, "complaint", msg)) in ("approve", "need_evidence"), msg


# ------------------------------------------------------------- 3. репорты: ID, помощь, нарушитель
@pytest.mark.parametrize("msg", [
    "проверьте мою вчерашнюю жалобу, жду ответа уже 30 минут",
    "жду ответа 2 часа",
    "уже 5 раз пишу, никто не отвечает",
    "через 10 минут сервер упал",
    "770000 рублей",
    "дай мне бан на 9 сек пж",
    "играю уже 2 часа, как открыть кейс?",
])
def test_durations_and_counts_are_not_player_ids(msg, rb):
    assert extract(msg, rb).report_id is None, msg


def test_real_player_id_still_extracted(rb):
    assert extract("8417 дб", rb).report_id == "8417"
    assert extract("поможете мне? 347ид застрял", rb).report_id == "347"
    assert extract("id 42 читер", rb).report_id == "42"
    assert extract("255 развяжите", rb).report_id == "255"       # «раз…» не счётчик
    assert extract("55 разбан", rb).report_id == "55"


def test_status_inquiry_does_not_invent_a_player_to_watch(cp):
    r = triage(cp, "report", "проверьте мою вчерашнюю жалобу, жду ответа уже 30 минут")
    assert "[30]" not in text(r) and "проследит за игроком" not in text(r)


def test_player_id_in_watch_draft(cp):
    r = triage(cp, "report", "8417 дб")
    assert intent(r) == "report_watch" and "[8417]" in text(r)


@pytest.mark.parametrize("msg,want", [
    ("Помогите, на меня напали у больницы", {"help_ack", "report_watch"}),
    ("адмін, поможіть мені", {"help_ack"}),
    ("машина упала в воду", {"help_vehicle"}),
    ("Test_Harasser пристаёт ко мне, забаньте пожалуйста", {"report_watch"}),
])
def test_report_is_not_answered_with_discord_deflection(cp, msg, want):
    r = triage(cp, "report", msg)
    assert intent(r) in want, (msg, intent(r))
    assert "Discord" not in text(r)
    assert r["needs_human"] is True or intent(r) == "help_vehicle"


@pytest.mark.parametrize("msg", ["застрял в текстурах, помогите", "я застрял в текстуре"])
def test_character_stuck_is_not_answered_with_the_vehicle_tow_button(cp, msg):
    """Кнопка эвакуатора только для транспорта: персонажу в текстурах она не поможет."""
    r = triage(cp, "report", msg)
    assert intent(r) != "help_vehicle", (msg, text(r))


def test_nick_is_kept_in_watch_draft(cp):
    r = triage(cp, "report", "Test_Harasser пристаёт ко мне, забаньте пожалуйста")
    assert "Test_Harasser" in text(r)


@pytest.mark.parametrize("msg", [
    "кто-то зашёл в мой аккаунт и продал дом, верните имущество",
    "украли бизнес, верните его пожалуйста",              # «верните» из признака stuck не отменяет кражу
])
def test_account_hijack_phrase_goes_to_account_flow(cp, msg):
    r = triage(cp, "report", msg)
    assert r["category"] == "report.account" and intent(r) == "account" and r["needs_human"] is True
    assert not PROMISE.search(text(r))


def test_report_about_admin_misconduct_is_not_a_service_refusal(cp):
    r = triage(cp, "report", "админ Ivan_Petrov12 телепортировал меня и ограбил")
    assert intent(r) != "help_service" and r["needs_human"] is True


# ------------------------------------------------------------- 4. конкретика в запросе доказательств
@pytest.mark.parametrize("msg,lang,cite", [
    ("Test_Cheat использует софт, летает, 5.2 ОП", None, "5.2"),
    ("Test_Cheat софт қолданады, ұшып жүр, 5.2 ОП", "kk", "5.2"),
    ("Test_Cheat softdan foydalanyapti, uchib yuribdi, 5.2 OP", "uz", "5.2"),
    ("Test_Cheat uses soft hack, flying, rule 5.2", None, "5.2"),
])
def test_need_evidence_names_the_violation_in_every_language(cp, msg, lang, cite):
    """Пункт назвал сам игрок, поэтому нарушение называется и при неуверенной категории (модели в тесте нет)."""
    r = triage(cp, "complaint", msg, lang=lang)
    assert intent(r) == "need_evidence", (msg, intent(r))
    assert i18n.RULE_TITLES[cite][r["draft_reply"]["lang"]] in text(r)


@pytest.mark.parametrize("lang", ["es", "pt"])
def test_need_evidence_names_the_violation_for_es_pt(lang, rb):
    d = drafts.build("complaint", "complaint.cheat", Signals(topics={"cheat"}, words=4), "soft hack", lang, rb, "need_evidence",
                     None, False)
    assert d.intent == "need_evidence" and i18n.RULE_TITLES["5.2"][lang] in d.text


def test_need_evidence_for_rp_term_names_the_term(rb):
    sig = Signals(topics={"dm"}, words=4)
    ru = drafts.build("complaint", "complaint.dm", sig, "Test_Player убил меня без причины", "ru", rb, "need_evidence", None,
                      False, cat_conf=0.9)
    assert ru.intent == "need_evidence" and "(убийство без RP-причины)" in ru.text
    uz = drafts.build("complaint", "complaint.dm", sig, "Test_Player sababsiz otdi", "uz", rb, "need_evidence", None, False,
                      cat_conf=0.9)
    assert "RP sababisiz o‘ldirish" in uz.text


def test_violation_is_not_named_when_category_is_unreliable(rb):
    sig = Signals(topics={"cheat"}, words=4)
    low = drafts.build("complaint", "complaint.cheat", sig, "soft hack", "ru", rb, "need_evidence", None, False, cat_conf=0.55)
    assert low.intent == "need_evidence" and "нарушение (" not in low.text
    own = Signals(topics={"cheat"}, words=4, rule_refs=["5.2"])      # пункт назвал сам игрок
    assert "стороннее ПО" in drafts.build("complaint", "complaint.cheat", own, "5.2 soft", "ru", rb, "need_evidence", None, False,
                                          cat_conf=0.55).text


def test_need_evidence_without_known_violation_stays_generic(rb):
    d = drafts.build("complaint", "complaint.other", Signals(words=5), "что-то странное", "ru", rb, "need_evidence", None, False)
    assert d.intent == "need_evidence" and "нарушение (" not in d.text and "{" not in d.text


def test_rule_titles_are_tidy():
    assert drafts._tidy_title("убивать/наносить урон до начала мероприятия участникам других семей.") == \
        "убивать/наносить урон до начала мероприятия участникам других семей"
    cut = drafts._tidy_title("заезжать/заходить на территорию проведения семейных войн после 40-ой минуты (под конец мероприятия)")
    assert cut.count("(") == cut.count(")") and len(cut) <= 90 and not cut.endswith((" ", ",", "("))
    src = "заезжать/заходить на территорию проведения семейных войн после 40-ой минуты (под конец мероприятия)"
    assert src.startswith(cut)
    long = "любые посторонние аудиотрансляции в микрофон, включая музыку, крики, шумы, а также использование звуковых программ"
    assert drafts._tidy_title(long) == "любые посторонние аудиотрансляции в микрофон, включая музыку, крики, шумы"
    assert not drafts._tidy_title("передача валюты и имущества на безвозмездной основе и в подарок другим игрокам сервера на мероприятии").endswith(" и")


# ------------------------------------------------------------- 5. утверждения о передаче и закрытии требуют человека
CLAIMS = [
    "Ваше обращение также передано администратору.",
    "Жалоба на действия администратора принята и передана старшей администрации на проверку.",
    "Передал администратору, он проследит за игроком.",
    "Жалоба рассмотрена. По приложенным материалам видно нарушение п. 2.1. Жалоба закрыта.",
    "Murojaatingiz administratorga yetkazildi.",
    "Өтінішіңіз әкімшіге де берілді.",
    "Your request has also been passed to an administrator.",
]


@pytest.mark.parametrize("claim", CLAIMS)
def test_guard_flags_claims_of_handoff_and_closure(claim):
    assert guard.claims_action(claim)


@pytest.mark.parametrize("neutral", [
    "Уточните, пожалуйста, ваш вопрос или жалобу: что случилось?",
    "Если транспорт застрял или перевернулся, нажмите кнопку эвакуатора на спидометре.",
    "Ответ на этот вопрос можно узнать у игроков или в Discord-сервере игры.",
])
def test_guard_does_not_flag_neutral_text(neutral):
    assert not guard.claims_action(neutral)


def test_llm_text_with_handoff_claim_cannot_be_sent_automatically(cp):
    class FakeLLM:
        intents = ("clarify",)

        def polish(self, d, t, sig, cat, rb):
            from dataclasses import replace
            return replace(d, text="Здравствуйте! Ваше обращение передано администратору.", auto_ok=True)

    cp.llm = FakeLLM()
    try:
        r = triage(cp, "report", "+++ ???")
    finally:
        cp.llm = None
    if intent(r) == "clarify":
        assert r["needs_human"] is True
        assert any("передач" in x or "закрыт" in x for x in r["reasons"])


# ------------------------------------------------------------- 6. шаблоны во всех языках
@pytest.mark.parametrize("lang", ["ru", "kk", "uz", "en", "es", "pt"])
def test_every_template_is_free_of_promises_and_placeholders(lang):
    for key, tpl in i18n.T[lang].items():
        filled = tpl
        for k, v in dict(cite="п. 2.1 Общих правил", cite_req="п. 1.3.1 Правил подачи жалоб", cite_time="п. 1.2.6",
                         cite_platform="п. 1.2.1", cite_gen="п. 2.1", title="x", nick_part="", sanction="мут", term="DM",
                         discord="https://d", support="https://s", pid_part="", what="", nick="N", ref="2.1", section="Общих правил",
                         pid="1").items():
            filled = filled.replace("{" + k + "}", v)
        assert "{" not in filled, (lang, key)
        assert not PROMISE.search(filled), (lang, key)


@pytest.mark.parametrize("lang", ["ru", "kk", "uz", "en", "es", "pt"])
def test_no_template_claims_a_completed_handoff(lang):
    for key, tpl in i18n.T[lang].items():
        assert not HANDOFF_CLAIM.search(tpl), (lang, key, tpl)


def test_template_keys_are_identical_in_all_languages():
    base = set(i18n.T["ru"])
    for lang, table in i18n.T.items():
        assert set(table) == base, (lang, base ^ set(table))


# ------------------------------------------------------------- 7. набор проб (инварианты на всех языках)
# сервис ничего не передаёт: в основных черновиках нет утверждений о совершённой передаче (независимый список, не из guard)
HANDOFF_CLAIM = re.compile(
    r"передан[оаы]?\s|передал\s|yuborildi|yetkazildi|жіберілді|берілді\b|бердім|passed (this )?to|forwarded|enviad[oa]|encaminhad[oa]|"
    r"se pasó|pasó a la|avisado|avisei", re.I)


@pytest.mark.parametrize("probe", PROBES, ids=lambda p: f"{p['group']}:{p['text'][:30]}")
def test_probe_invariants(cp, probe):
    payload = {"kind": probe["kind"], "messages": [{"role": "player", "text": probe["text"]}]}
    if probe["server_lang"]:
        payload["server_lang"] = probe["server_lang"]
    if probe["images"] is not None:
        payload["images_count"] = probe["images"]
    r = cp.triage(payload, use_dedup=False)
    reply = text(r)
    assert not PROMISE.search(reply), reply
    for f in probe["forbid"]:
        assert f.lower() not in reply.lower(), (f, reply)
    assert all(cp.rules.exists(c) for c in r["draft_reply"]["cited"])
    assert not HANDOFF_CLAIM.search(reply), reply
    for alt in r["_meta"]["alternatives"]:
        assert not HANDOFF_CLAIM.search(alt["text"]), alt["text"]
    if guard.claims_action(reply):
        assert r["needs_human"] is True, reply


@pytest.mark.skipif(not HAS_DATA, reason="нет data/ и models/")
def test_probe_intents_with_real_models(copilot_full):
    """Сценарии проб на настоящих правилах и моделях: не менее 95 % допустимых."""
    scored = bad = 0
    misses = []
    for p in PROBES:
        if p["ok"] is None:
            continue
        payload = {"kind": p["kind"], "messages": [{"role": "player", "text": p["text"]}]}
        if p["server_lang"]:
            payload["server_lang"] = p["server_lang"]
        if p["images"] is not None:
            payload["images_count"] = p["images"]
        r = copilot_full.triage(payload, use_dedup=False)
        scored += 1
        if intent(r) not in p["ok"]:
            bad += 1
            misses.append((p["text"], intent(r)))
    assert bad / scored <= 0.05, misses


# ------------------------------------------------------------- 8. пункт, выбранный игроком, против текста
@pytest.fixture(scope="module")
def rb_insult(tmp_path_factory):
    """Тестовые правила плюс 2.2 и 2.4: в мини-фикстуре их нет."""
    import json
    from copilot.rules import load
    data = json.loads(FIXTURE_RULES.read_text(encoding="utf-8"))
    data["rules"][0]["points"] += [{"ref": "2.2", "text": "Запрещена пропаганда запрещённых тем."},
                                   {"ref": "2.4", "text": "Запрещены расизм, ксенофобия и оскорбление религии."}]
    p = tmp_path_factory.mktemp("rules-insult") / "rules.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return load(str(p))


@pytest.mark.parametrize("msg,ref,want", [
    ("оскорбил меня и маму, 2.2 оп", "2.2", "2.1"),                  # пропаганды в тексте нет: админы ставят 2.1
    ("в чате пропаганда 18+ контента, 2.2 оп", "2.2", "2.2"),
    ("оскорбил меня, 2.4 оп", "2.4", "2.1"),
    ("обозвал расистскими словами, нацист, 2.4 оп", "2.4", "2.4"),
])
def test_player_chosen_topical_rule_needs_support_in_the_text(rb_insult, msg, ref, want):
    sig = extract(msg, rb_insult)
    assert ref in sig.rule_refs
    rule, term = drafts.pick_violation("complaint.insult", sig, msg, rb_insult)
    assert (rule, term) == (want, None)
