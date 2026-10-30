"""Проверка текста черновика (пункты, обещания) и маскирование секретов. Работает на синтетических правилах."""
import pytest

from support import FIXTURE_RULES
from copilot.redact import redact
from copilot.verify import extract_refs, find_promise, text_ref_issues, verify_text


# ---------- verify ----------
def test_existing_rule_in_text_is_confirmed(rb):
    v = verify_text("Здравствуйте! Видно нарушение п. 2.1 Общих правил (оскорбление). Спасибо.", rb)
    assert v.ok and v.cited == ["2.1"]


def test_missing_rule_number_blocks(rb):
    v = verify_text("Нарушен п. 99.9 Общих правил, игрок будет разбанен.", rb)
    assert not v.ok
    codes = {x.code for x in v.violations}
    assert "rule_missing" in codes and "promise" in codes
    assert v.cited == []


def test_section_prefix_resolves_to_right_section(rb):
    # ЖБ 1.2.3 есть в правилах жалоб, а в Общих правилах пункта 1.2.3 нет
    ok = verify_text("Жалоба не рассмотрена: нет описания (п. 1.2.3 Правил подачи жалоб).", rb)
    assert ok.ok and ok.cited == ["ЖБ 1.2.3"]
    wrong = verify_text("Жалоба не рассмотрена по п. 1.2.3 Общих правил.", rb)
    assert not wrong.ok and wrong.violations[0].code == "rule_missing"


def test_kazakh_and_uzbek_suffix_forms(rb):
    assert verify_text("Жалпы ережелердің 2.1-тармағы бойынша бұзушылық бар.", rb).cited == ["2.1"]
    assert verify_text("Umumiy qoidalarning 2.1-bandi buzilgan.", rb).cited == ["2.1"]
    assert not verify_text("Umumiy qoidalarning 7.7-bandi buzilgan.", rb).ok


def test_english_and_spanish_forms(rb):
    assert verify_text("This breaks rule 2.1 of the General Rules.", rb).cited == ["2.1"]
    assert not verify_text("This breaks rule 8.8 of the General Rules.", rb).ok
    assert verify_text("Se aplica el punto 2.1 de las Reglas generales.", rb).cited == ["2.1"]


def test_plain_numbers_are_not_refs(rb):
    t = "Подождите 1.5 часа, обжаловать можно в течение 48 часов, версия 3.14."
    assert extract_refs(t, rb) == []
    assert verify_text(t, rb).ok


@pytest.mark.parametrize("text", [
    "Бан будет снят в течение дня.",
    "Мы вернём деньги на ваш счёт.",
    "Нарушитель будет наказан по всей строгости.",
    "Мы накажем этого игрока.",
    "We will unban you tomorrow.",
    "The player will be banned.",
    "Гарантируем возврат средств.",
])
def test_promises_are_blocked(rb, text):
    v = verify_text("Здравствуйте! " + text, rb)
    assert not v.ok and any(x.code == "promise" for x in v.violations), text


def test_neutral_text_is_not_a_promise():
    assert find_promise("Наказание по правилам: блокировка персонажа от 3 до 10 дней. Срок назначит администратор.") is None
    assert find_promise("Передали обращение старшей администрации, ожидайте ответа.") is None


def test_empty_and_too_long_text(rb):
    assert verify_text("  ", rb).violations[0].code == "empty"
    assert any(x.code == "too_long" for x in verify_text("а" * 4001, rb).violations)


def test_text_ref_issues_for_pipeline_drafts(rb):
    assert text_ref_issues("Видно нарушение п. 2.1 Общих правил.", ["2.1"], rb) == []
    assert "99.9" in text_ref_issues("См. п. 99.9 Общих правил.", ["2.1"], rb)[0]
    assert "не входит" in text_ref_issues("См. п. 3.1 Общих правил.", ["2.1"], rb)[0]


# ---------- redact ----------
def test_api_keys_and_jwt_are_masked():
    r = redact("мой ключ sk-abcdefghijklmnop1234567890 и токен ghp_abcdefghijklmnopqrstuvwxyz1234")
    assert "sk-abcdef" not in r.text and "ghp_" not in r.text and r.counts["token"] == 2
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
    assert jwt not in redact("вот " + jwt).text


def test_card_number_masked_only_if_luhn_valid():
    r = redact("списали с карты 4111 1111 1111 1111 деньги")
    assert "4111 1111" not in r.text and "****1111" in r.text and r.counts["card"] == 1
    # не карта: идентификатор заказа без верной контрольной суммы остаётся
    assert redact("заказ 1234567890123456").text == "заказ 1234567890123456"


def test_password_after_label_is_masked():
    r = redact("мой пароль: Qwerty123 взломали аккаунт")
    assert "Qwerty123" not in r.text and "взломали аккаунт" in r.text and r.counts["secret"] == 1
    assert "hunter2024" not in redact("password hunter2024").text
    assert "4821" not in redact("пин-код 4821").text


def test_ordinary_text_is_untouched():
    t = "Arman_Petrov оскорблял меня в чате, 2.1 ОП, скрины есть. Пароль не менял, пароль не помню."
    r = redact(t)
    assert r.text == t and not r.changed
