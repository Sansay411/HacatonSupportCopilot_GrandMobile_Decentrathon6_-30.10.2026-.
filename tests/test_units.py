"""Юнит-тесты на синтетике: данные кейса не нужны."""
from copilot import guard, sanctions
from copilot.dedup import DedupStore, is_spam
from copilot.lang import detect, reply_lang
from copilot.signals import extract
from copilot.textnorm import clean


def test_cp1251_kazakh_restored_on_kz_server():
    assert clean("маѕан кґмектесіѕіз", region="kz") == "маңан кғмектесіңіз"


def test_uzbek_cyrillic_untouched_elsewhere():
    assert clean("ўйинчи", region="uz") == "ўйинчи"


def test_cp1251_detected_without_region():
    assert "қ" in clean("ќайда", region=None)


def test_lang_detection():
    assert detect("оскорбил меня и мою семью") == "ru"
    assert detect("onadan so'kdi ban bering iltimos") == "uz"
    assert detect("Бұл әкімші шағымды жапты") == "kk"
    assert detect("Поможіть ти мені") == "uk"
    assert detect("<url>") == "und"
    assert detect("osk rod", "ru") == "ru"
    assert reply_lang("uk", "ru") == "ru"
    assert reply_lang("und", "uz") == "uz"


def test_rule_refs_parsing(rb):
    assert rb.parse_refs("2.1оп и 1.1 gz") == ["2.1", "GZ 1.1"]
    assert rb.parse_refs("1.2.3 ППЖ") == ["ЖБ 1.2.3"]
    assert rb.parse_refs("9.9 оп, 357, 3,5,7") == []


def test_signals(rb):
    s = extract("231 дм без причины", rb)
    assert "dm" in s.topics and s.player_id == "231"
    s = extract("не согласен с наказанием, снимите бан", rb)
    assert "appeal" in s.topics
    s = extract("оплатил гк, не пришло", rb)
    assert "payment" in s.topics


def test_sanction_choice_and_render(rb):
    s = sanctions.choose(rb.get("2.1"), "оскорбил мою семью")
    assert sanctions.render(s, "ru") == "блокировка персонажа от 3 до 10 дней"
    s = sanctions.choose(rb.get("5.2"), "софт")
    assert sanctions.render(s, "ru") == "блокировка персонажа от 7 до 31 дня"
    s = sanctions.choose(rb.get("GZ 1.1"), "дм")
    assert sanctions.render(s, "uz") == "demorgan (60 daqiqa) + WARN"


def test_guard_blocks_promises_and_fake_rules(rb):
    valid, reasons = guard.check("Наказание будет снято, вернём машину", ["2.1", "99.9"], rb)
    assert valid == ["2.1"]
    assert len(reasons) == 2
    valid, reasons = guard.check("Жалоба рассмотрена.", ["2.1"], rb)
    assert valid == ["2.1"] and reasons == []


def test_dedup_window():
    st = DedupStore()
    kw = dict(reporter="r1", reported="x", kind="complaint", category="complaint.insult")
    assert st.check_and_add(text="оск родни", created_at="2026-08-01T10:00:00", **kw) is None
    assert st.check_and_add(text="оск родни", created_at="2026-08-01T10:30:00", **kw)
    assert st.check_and_add(text="оск родни", created_at="2026-08-01T12:00:00", **kw) is None
    assert st.check_and_add(text="оск", created_at="2026-08-01T12:01:00", reporter=None, reported="x",
                            kind="complaint", category="complaint.insult") is None


def test_spam():
    assert is_spam("Как дела? Как дети? Как кошка? Как собака? Как мама? Как папа? Как бабушка? Как дедушка? Как брат?")
    assert not is_spam("Игрок оскорбил мою маму в чате, скрины прилагаю")
