"""Независимый Red Team аудит: обязательная эскалация (P0), ложные сигналы, RAG/разделы, дедупликация и Unicode."""
from __future__ import annotations

import pytest

from copilot.dedup import DedupStore
from copilot.pipeline import Copilot
from copilot.rules import load as load_rules
from copilot.verify import verify_text
from tests.support import FIXTURE_RULES


@pytest.fixture(scope="module")
def rb():
    return load_rules(str(FIXTURE_RULES))


@pytest.fixture()
def cp(tmp_path):
    import shutil
    shutil.copy(FIXTURE_RULES, tmp_path / "rules.json")
    return Copilot(tmp_path, tmp_path / "no_models")


def _triage(cp: Copilot, kind: str, text: str, *, reporter: str | None = None, reported_nick: str | None = None,
            server_lang: str | None = None, created_at: str | None = None, use_dedup: bool = True) -> dict:
    payload = {
        "kind": kind,
        "messages": [{"role": "player", "text": text, "attachments": 0}],
    }
    if reporter is not None:
        payload["reporter_hash"] = reporter
    if reported_nick is not None:
        payload["reported_nick"] = reported_nick
    if server_lang is not None:
        payload["server_lang"] = server_lang
    if created_at is not None:
        payload["created_at"] = created_at
    return cp.triage(payload, use_dedup=use_dedup)


# ==============================================================================
# 1. P0 — ОБЯЗАТЕЛЬНАЯ ЭСКАЛАЦИЯ (26 кейсов Tera + расширенная матрица)
# Инварианты:
# - Платежи, апелляции наказаний, взломы/доступ к аккаунту и жалобы на админов
#   ВСЕГДА требуют человека (needs_human=True).
# - Дедупликация, классификатор и шаблон ответа не могут отменить эскалацию.
# ==============================================================================

TERA_P0_CASES = [
    ("payment_report", "report", "ru", "Оплатил донат, деньги списались, но Grand Coins не пришли."),
    ("payment_complaint", "complaint", "ru", "Купил донат пакет, деньги списались, но монеты не пришли."),
    ("account_report", "report", "ru", "Меня взломали, не могу войти в аккаунт и пропало имущество."),
    ("account_complaint", "complaint", "ru", "Мой аккаунт взломали и сменили пароль, помогите вернуть доступ."),
    ("admin_complaint", "complaint", "ru", "Администратор без причины выдал наказание, прошу проверить его действия."),
    ("appeal_complaint_ru", "complaint", "ru", "Я не согласен с баном, прошу пересмотреть наказание."),
    ("appeal_report_ru", "report", "ru", "Я не согласен с баном, прошу пересмотреть наказание."),
    ("appeal_report_alt_ru", "report", "ru", "Разбаньте пожалуйста, наказание выдано ошибочно."),
    ("appeal_kk", "report", "kk", "Мен банмен келіспеймін, жазаны қайта қарауды сұраймын."),
    ("appeal_uz", "report", "uz", "Men ban bilan rozi emasman, jazoni qayta ko‘rib chiqing."),
    ("irl_threat_report", "report", "ru", "Игрок угрожает найти меня в реальной жизни и расправиться."),
    ("irl_threat_complaint", "complaint", "ru", "Игрок угрожает мне в реальной жизни и пишет мой адрес."),
    ("Mixed_payment_appeal", "report", "ru", "После оплаты доната аккаунт забанили по ошибке, прошу проверить."),
]


@pytest.mark.parametrize("name,kind,lang,text", TERA_P0_CASES)
def test_p0_tera_26_cases_single_and_duplicate(cp, name, kind, lang, text):
    """Инвариант P0: все 13 базовых и 13 повторных (итого 26) сценариев Tera обязаны возвращать needs_human=True."""
    known = set(cp.rules.points)
    r1 = _triage(cp, kind, text, reporter=f"tera_{name}", server_lang=lang, created_at="2026-10-31T10:00:00Z")
    r2 = _triage(cp, kind, text, reporter=f"tera_{name}", server_lang=lang, created_at="2026-10-31T10:05:00Z")
    assert r1["needs_human"] is True, f"{name}_single failed mandatory escalation: {r1}"
    assert r2["needs_human"] is True, f"{name}_duplicate failed mandatory escalation: {r2}"
    assert r2["is_spam_or_duplicate"] is True
    for cite in r1["draft_reply"]["cited"] + r2["draft_reply"]["cited"]:
        assert cite in known


@pytest.mark.parametrize("kind,lang,text,inv", [
    # Апелляции в репортах (разные категории классификатора: question, complaint, help, offtopic)
    ("report", "ru", "за что меня посадили в деморган без причины? выпустите", "appeal in report.complaint/question"),
    ("report", "ru", "вытащите из тюрьмы я ничего не делал а меня посадили", "appeal in report.help must not be auto help_vehicle"),
    ("report", "ru", "снимите мут пожалуйста и тп ко мне если можете", "appeal in report.help must not be auto help_service"),
    ("report", "ru", "За что бан?", "short appeal in report.offtopic/question"),
    ("report", "kk", "Банды алып тастаңыздар өтінемін, мен кінәлі емеспін", "kk appeal in report via _APPEAL_EXTRA"),
    ("report", "uz", "Ban nohaq berildi, banni yechib bering iltimos", "uz appeal in report via _APPEAL_EXTRA"),
    ("report", "ru", "Please lift my ban, the ban was unfair", "en appeal in report"),
    ("report", "ru", "menya zabanili bez prichiny, razbante pozhaluysta", "translit appeal in report"),
    ("report", "ru", "kogda snimite mut? dal mut prosto tak", "translit penalty question in report"),
    # Апелляции в жалобах, где упоминается само нарушение (оскорбление, читы, ДМ)
    ("complaint", "kk", "Мен ешкімді балағаттамадым, банды алып тастаңыздар өтінемін", "kk appeal with insult word"),
    ("complaint", "uz", "Men hech kimni haqorat qilmadim, banni olib tashlang iltimos", "uz appeal with insult word"),
    ("complaint", "ru", "Почему бан за читы? Объясните причину блокировки", "ru penalty question with cheat word"),
    ("complaint", "ru", "Я не оскорблял его родных, за что мне выдали бан?", "ru negation + appeal"),
    ("complaint", "ru", "za chto mne dali ban, ya ne chiteril i ne oskorblyal", "translit complaint appeal"),
    # Платежи в complaint и report (включая вопросы, отрицания, kk/uz, транслит)
    ("complaint", "ru", "Оплатил донат, почему деньги списали, а донат не пришёл?", "payment question in complaint.invalid"),
    ("complaint", "ru", "Я не покупал випку, но с карты списались деньги за донат!", "payment with negation in complaint"),
    ("complaint", "kk", "Донат төледім, бірақ монеталар түспеді, не істеймін?", "kk payment in complaint"),
    ("complaint", "uz", "Donat uchun pul to'ladim, lekin tangalar tushmadi, yordam bering", "uz payment in complaint"),
    ("report", "ru", "oplatil donat dengi spisali a gk ne prishli", "translit payment in report"),
    ("complaint", "ru", "oplatil donat dengi spisali a gk ne prishli", "translit payment in complaint"),
    # Взлом и доступ к аккаунту в complaint и report (включая вопросы, отрицания, «верните», kk/uz, транслит)
    ("complaint", "ru", "Мой аккаунт взломали, что мне теперь делать?", "account hack question in complaint.invalid"),
    ("complaint", "ru", "Меня не взламывали, но я забыл пароль и не могу войти в аккаунт", "account access with negation"),
    ("report", "ru", "Угнали аккаунт, верните доступ пожалуйста!", "account hijack with stuck word верните"),
    ("complaint", "kk", "Аккаунтымды бұзды, құпиясөзді ауыстырып жіберді, кіре алмаймын", "kk account hack in complaint"),
    ("complaint", "uz", "Hisobimni buzishdi, akauntga kira olmayapman, yordam bering", "uz account hack in complaint"),
    ("report", "ru", "vzlomali akkaunt i ukrali mashinu, ne mogu voiti v akk", "translit account hack in report"),
    ("complaint", "ru", "vzlomali akkaunt i smenili parol, pomogite vernut akk", "translit account hack in complaint"),
    # Жалобы на администрацию в report и complaint (включая взятки, блат, kk/uz, транслит)
    ("report", "ru", "Администратор берёт взятки за разбан игроков, проверьте логи", "admin bribery in report"),
    ("complaint", "ru", "Администратор блатит свою семью и игнорирует нарушения", "admin blat in complaint"),
    ("report", "kk", "Әкімші мені себепсіз банға жіберді, үстінен шағым жазамын", "kk admin complaint in report"),
    ("report", "uz", "Admin meni sababsiz qamoqqa tiqdi, administrator ustidan shikoyat", "uz admin complaint in report"),
    ("complaint", "ru", "zhaloba na admina, admin blatit i oskorbil menya", "translit admin complaint"),
])
def test_p0_extended_matrix_single_and_duplicate(cp, kind, lang, text, inv):
    """Инвариант P0 по всем измерениям: первый и повторный тикет всегда требуют человека (needs_human=True)."""
    rep = f"ext_{ abs(hash((kind, lang, text))) % 100000 }"
    r1 = _triage(cp, kind, text, reporter=rep, server_lang=lang, created_at="2026-10-31T11:00:00Z")
    r2 = _triage(cp, kind, text, reporter=rep, server_lang=lang, created_at="2026-10-31T11:10:00Z")
    assert r1["needs_human"] is True, f"[{inv}] single failed: {r1}"
    assert r2["needs_human"] is True, f"[{inv}] duplicate failed: {r2}"
    if "appeal" in inv and kind == "complaint":
        assert r1["_meta"]["intent"] == "appeal", f"[{inv}] expected appeal intent, got {r1['_meta']['intent']}"


def test_p0_duplicate_followup_inherits_mandatory_escalation(cp):
    """Инвариант P0: если первый тикет требовал обязательной эскалации, его дубль тоже требует человека."""
    r1 = _triage(cp, "report", "Меня взломали, украли аккаунт и имущество!", reporter="rep_follow",
                 reported_nick="Some_Hacker", created_at="2026-10-31T12:00:00Z")
    r2 = _triage(cp, "report", "Ну что там, ответьте быстрее пожалуйста", reporter="rep_follow",
                 reported_nick="Some_Hacker", created_at="2026-10-31T12:05:00Z")
    assert r1["needs_human"] is True
    assert r2["is_spam_or_duplicate"] is True
    assert r2["needs_human"] is True


# ==============================================================================
# 2. ADVERSARIAL ML: ЛОЖНЫЕ СИГНАЛЫ, ЛОЖНЫЙ ВЗЛОМ, UNICODE, ТРАНСЛИТ
# ==============================================================================

@pytest.mark.parametrize("text,inv", [
    ("Вертолет не может взлететь с крыши, помогите", "слово «взлететь» не должно включать сигнал взлома аккаунта (\\bвзл)"),
    ("Самолет взлетел и застрял в воздухе", "слово «взлетел» не взлом аккаунта"),
    ("Где находится почта на карте?", "вопрос про игровую почту не взлом аккаунта"),
    ("Как устроиться курьером на почту?", "работа на почте не взлом аккаунта"),
    ("Можно ли мне устроиться почтальоном, если состою в банде?", "слово «почтальон» не взлом аккаунта"),
    ("Не могу войти в здание мэрии, пикап не работает", "вход в здание не вход в аккаунт"),
    ("Пропал звук в игре, что делать?", "пропал звук не пропажа имущества/аккаунта"),
    ("Пропал худ и радар на экране", "пропал худ не пропажа имущества/аккаунта"),
])
def test_adversarial_no_false_account_hack_detection(cp, text, inv):
    """Инвариант: бытовые игровые фразы («взлететь», «почта», «войти в здание», «пропал звук») не дают report.account / p0."""
    r = _triage(cp, "report", text, use_dedup=False)
    assert r["category"] != "report.account", f"[{inv}] got report.account: {r}"
    assert r["_meta"]["intent"] != "account", f"[{inv}] got account intent: {r}"
    assert r["priority"] != "p0", f"[{inv}] got p0 priority: {r}"


@pytest.mark.parametrize("kind,text,inv", [
    ("report", "548 чек", "сленг «548 чек» (проследите за ID 548) не платёж"),
    ("report", "чек жб", "сленг «чек жб» (проверьте жалобу) не платёж"),
    ("complaint", "ОСК РОД ЧЕК ЧАТ", "«чек чат» в жалобе на оскорбление не платёж"),
])
def test_adversarial_slang_check_is_not_payment(cp, kind, text, inv):
    """Инвариант: сленговое «чек» без платёжного контекста не включает сценарий платежа."""
    r = _triage(cp, kind, text, use_dedup=False)
    assert r["category"] != "report.payment", f"[{inv}] got report.payment: {r}"
    assert r["_meta"]["intent"] != "payment", f"[{inv}] got payment intent: {r}"


@pytest.mark.parametrize("text", [
    "застрял в текстурах, вытащите пожалуйста",
    "я застрял в текстуре, вытащите",
    "застрял без машины, помогите",
    "вытащите из тюрьмы я ничего не делал а меня посадили",
])
def test_adversarial_character_stuck_with_pull_out_is_not_vehicle_tow(cp, text):
    """Инвариант: персонаж в текстурах, тюрьме или «без машины» не получает автоответ про кнопку эвакуатора транспорта."""
    r = _triage(cp, "report", text, use_dedup=False)
    assert r["_meta"]["intent"] != "help_vehicle", f"unexpected help_vehicle for {text!r}: {r}"
    assert r["needs_human"] is True


def test_adversarial_unicode_zero_width_does_not_bypass_escalation_or_verify(cp, rb):
    """Инвариант: невидимые Unicode-символы (ZWSP, soft hyphen) не обходят детекцию взлома и фильтр обещаний."""
    r = _triage(cp, "report", "Мо\u200bй ак\u00adкаунт вз\u200bломали и ук\u200cрали ма\ufeffшину", use_dedup=False)
    assert r["category"] == "report.account" and r["needs_human"] is True
    v = verify_text("Здравствуйте! Мы обязательно раз\u200bбаним ваш ак\u00adкаунт.", rb)
    assert not v.ok and any(x.code == "promise" for x in v.violations)


@pytest.mark.parametrize("text", [
    "kogda snimite mut",
    "kuda pisat zhalobu",
    "oplatil donat dengi spisali a gk ne prishli",
    "vzlomali akkaunt ukrali mashinu",
])
def test_adversarial_russian_translit_detected_as_ru(cp, text):
    """Инвариант: русский транслит со словами kogda/kuda или союзом «a» определяется как ru, а не uz или pt."""
    r = _triage(cp, "report", text, use_dedup=False)
    assert r["lang"] == "ru" and r["draft_reply"]["lang"] == "ru", (text, r["lang"], r["draft_reply"]["lang"])


# ==============================================================================
# 3. RAG & DRAFT SECURITY: РАЗДЕЛЫ ПРАВИЛ И НЕРЕЛЕВАНТНЫЕ ПУНКТЫ
# ==============================================================================

@pytest.mark.parametrize("text,expected_refs", [
    ("Игрок нарушил GZ 1.2, связал меня на рынке", ["GZ 1.2"]),
    ("Подаю по ЖБ 1.2.3, нет описания", ["ЖБ 1.2.3"]),
    ("Подаю по ЖБ 1.2, накажите игрока", []),
    ("Игрок нарушил ПГО 1.2 при задержании", []),
])
def test_rag_section_prefix_before_number_is_not_confused_with_general_rules(rb, text, expected_refs):
    """Инвариант: префикс раздела перед номером («GZ 1.2», «ПГО 1.2», «ЖБ 1.2») не превращается в п. 1.2 Общих правил."""
    from copilot.rules import RulePoint
    rb.points.setdefault("1.2", RulePoint(30, "1.2", "Запрещено выдавать себя за администрацию проекта."))
    rb.points.setdefault("GZ 1.2", RulePoint(32, "1.2", "Запрещены криминальные действия в Зелёной Зоне."))
    refs = rb.parse_refs(text)
    assert refs == expected_refs, (text, refs)


@pytest.mark.parametrize("text,forbid_cite,forbid_substr", [
    ("Игрок толкает мою машину на парковке, нарушил 1.2 ОП https://youtu.be/test123", "1.2", "представляясь администрацией"),
    ("Игрок перекрыл дорогу фурой, нарушил 5.6 ОП", "5.6", "аморальные отыгровки"),
    ("Он обозвал меня дураком в чате, нарушил 2.6 ОП", "2.6", "угрозы в реальной жизни"),
])
def test_rag_irrelevant_rule_cited_by_player_is_not_confirmed(cp, text, forbid_cite, forbid_substr):
    """Инвариант: нерелевантный пункт из текста игрока без признаков этой темы не подтверждается в черновике."""
    r = _triage(cp, "complaint", text, use_dedup=False)
    assert forbid_cite not in r["draft_reply"]["cited"], r
    assert forbid_substr not in r["draft_reply"]["text"].lower(), r["draft_reply"]["text"]


# ==============================================================================
# 4. DEDUPLICATION: РАЗНЫЕ НАРУШИТЕЛИ, ОТРИЦАНИЯ, РАЗНЫЕ ИНЦИДЕНТЫ
# ==============================================================================

def test_dedup_different_offenders_are_not_duplicates():
    """Инвариант: жалобы одного заявителя на разных нарушителей не считаются дубликатами даже при одинаковом тексте."""
    d = DedupStore()
    m1 = d.match_and_add(reporter="alice", reported="offender_1", text="Игрок меня оскорбил в чате",
                         kind="complaint", created_at="2026-10-31T10:00:00Z", category="complaint.insult", ref="T1")
    m2 = d.match_and_add(reporter="alice", reported="offender_2", text="Игрок меня оскорбил в чате",
                         kind="complaint", created_at="2026-10-31T10:01:00Z", category="complaint.insult", ref="T2")
    assert m1 is None and m2 is None


def test_dedup_different_offender_nicks_in_text_are_not_duplicates(cp):
    """Инвариант: если ники разных нарушителей указаны в самом тексте, жалобы не склеиваются как дубли."""
    r1 = _triage(cp, "complaint", "Ivan_Petrov убил меня без причины у больницы", reporter="alice",
                 created_at="2026-10-31T10:00:00Z")
    r2 = _triage(cp, "complaint", "Petr_Sidorov убил меня без причины у больницы", reporter="alice",
                 created_at="2026-10-31T10:02:00Z")
    assert r1["is_spam_or_duplicate"] is False
    assert r2["is_spam_or_duplicate"] is False


def test_dedup_negation_vs_affirmation_is_not_duplicate():
    """Инвариант: утверждение нарушения и его отрицание («оскорбил» vs «не оскорбил») не являются дубликатами."""
    d = DedupStore()
    m1 = d.match_and_add(reporter="alice", reported=None, text="Игрок оскорбил меня",
                         kind="complaint", created_at="2026-10-31T10:00:00Z", category="complaint.insult", ref="T1")
    m2 = d.match_and_add(reporter="alice", reported=None, text="Игрок не оскорбил меня",
                         kind="complaint", created_at="2026-10-31T10:01:00Z", category="complaint.insult", ref="T2")
    assert m1 is None and m2 is None


def test_dedup_same_offender_different_problem_is_not_duplicate():
    """Инвариант: разные проблемы с одним нарушителем («украл машину» vs «угрожает мне») не являются дубликатами."""
    d = DedupStore()
    m1 = d.match_and_add(reporter="alice", reported="offender_1", text="Игрок украл машину",
                         kind="complaint", created_at="2026-10-31T10:00:00Z", category="complaint.scam", ref="T1")
    m2 = d.match_and_add(reporter="alice", reported="offender_1", text="Игрок угрожает мне",
                         kind="complaint", created_at="2026-10-31T10:01:00Z", category="complaint.insult", ref="T2")
    assert m1 is None and m2 is None
    # Даже если вызывающий передал одинаковую категорию-заглушку, но темы в тексте несовместимы:
    d2 = DedupStore()
    d2.match_and_add(reporter="alice", reported="offender_1", text="Игрок украл машину",
                     kind="report", created_at="2026-10-31T10:00:00Z", category="same", ref="T1")
    m3 = d2.match_and_add(reporter="alice", reported="offender_1", text="Игрок угрожает мне в реальной жизни",
                          kind="report", created_at="2026-10-31T10:01:00Z", category="same", ref="T2")
    assert m3 is None


def test_store_decision_updates_eff_needs_human(tmp_path):
    """Инвариант: при эскалации или переводе обращения в p0 / чувствительную категорию eff_needs_human становится True."""
    from copilot.store import Store
    s = Store(tmp_path / "test.db")
    try:
        t = s.insert_ticket(
            kind="report", source="manual", actor="tester",
            request={"kind": "report", "text": "привет"}, player_text="привет", meta={},
            response={}, derived={"category": "report.offtopic", "priority": "p3", "lang": "ru", "draft_lang": "ru",
                                  "intent": "offtopic_flood", "category_source": "rules", "needs_human": False,
                                  "needs_human_policy": False, "confidence": 0.9, "is_spam": False, "is_dup": False,
                                  "cited_count": 1, "guard_missing": False, "guard_promise": False,
                                  "guard_text_ref": False, "proposes_penalty": False, "llm": False,
                                  "latency_ms": 1.0, "rules_fingerprint": "test", "model_loaded": False},
            draft={"intent": "offtopic_flood", "lang": "ru", "text": "Здравствуйте!", "cited": []},
            dup=None,
        )
        assert t["needs_human"] is False
        updated = s.apply_decision(t["id"], expected_rev=t["rev"], action="escalate", to_status="escalated",
                                   actor="mod", final_priority="p0", reason_code="mandatory")
        assert updated["needs_human"] is True
        assert updated["priority"] == "p0"
    finally:
        s.close()
