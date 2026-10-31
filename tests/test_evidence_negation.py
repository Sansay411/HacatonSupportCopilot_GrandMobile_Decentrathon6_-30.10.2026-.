"""Отрицание доказательств в тексте игрока: «Доказательств пока нет» не должно давать extracted.has_evidence = true.

Найдено при записи демо-видео: регулярка no_evidence_word ловила «доказательств нет» и не ловила «доказательств пока нет»,
поэтому предупреждение «нарушение подтверждается без доказательств» не срабатывало. Сама регулярка подаётся признаком
в обученную модель, поэтому её не меняем: отрицание для has_evidence считается отдельным полем Signals.evidence_denied.
"""
import pytest

from copilot import signals


def ev(rb, text, **kw):
    return signals.extract(text, rb, **kw).has_evidence


DENIED = [
    "Игрок Player_One оскорблял мою семью в игровом чате. Прошу проверить ситуацию. Доказательств пока нет",
    "Test_Cheat летает, доказательств у меня нет",
    "доказательств ещё нет, но прошу разобраться",
    "Нет пока доказательств, но он точно читерит",
    "видео пока нет, Test_Cheat летает",
    "скринов нет, Test_Dm убил меня",
    "записи нет, оскорблял в войсе",
    "жалоба без скринов: Test_Dm убил меня без причины",
    "не успел записать, но Test_Dm убил меня",
    "Доказательств нет",                        # старая форма продолжает работать
]

NOT_DENIED = [
    "Arman_Petrov оскорблял меня и мою семью в чате, скрины есть, 2.1 ОП",
    "Test_Cheat летает, видео есть, доказательств достаточно",
    "нет сомнений, что Test_Dm убил меня, видео приложил",       # «нет» не про доказательства
    "видео нет, но скрины есть",                                  # доказательства всё же заявлены
    "прикрепил видео, записи хватает",
]


@pytest.mark.parametrize("text", DENIED)
def test_denied_evidence_is_not_counted_as_evidence(rb, text):
    assert ev(rb, text) is False, text


@pytest.mark.parametrize("text", NOT_DENIED)
def test_stated_evidence_still_counts(rb, text):
    assert ev(rb, text) is True, text


def test_attachments_and_links_win_over_the_words(rb):
    """Файл или ссылка в обращении это объективный факт, слова «пока нет» его не отменяют."""
    assert ev(rb, "доказательств пока нет, но вот ссылка https://youtu.be/abc") is True
    assert ev(rb, "доказательств пока нет", images=1) is True


def test_model_features_are_unchanged(rb):
    """Теги тем идут в обученную модель: новое отрицание не должно менять набор тем, иначе модель нужно переобучать."""
    before = signals.extract("Игрок оскорблял мою семью. Доказательств пока нет", rb).topics
    assert "no_evidence_word" not in before and "evidence_word" in before


def test_scenario_text_gets_policy_warning(boot):
    """Через HTTP: текст из демо-видео получает предупреждение политики Sentra: наказание предложено, а вложений нет."""
    c, _ = boot()
    r = c.post("/tickets", json={"kind": "complaint", "reporter": "p-1",
                                 "text": "Игрок Player_One оскорблял мою семью в игровом чате. Прошу проверить ситуацию. Доказательств пока нет"})
    assert r.status_code == 201, r.text
    t = r.json()["ticket"]
    assert t["response"]["extracted"]["has_evidence"] is False
    assert t["needs_human"] is True
    if t["response"]["_meta"]["intent"] == "approve":
        assert any("вложений и ссылок в обращении нет" in x for x in t["response"]["_meta"]["policy"])
        assert "приложенным материалам" not in t["response"]["draft_reply"]["text"]
