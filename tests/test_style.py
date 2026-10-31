"""Фильтр стиля: ни тире, ни слешей, ни эмодзи, ни ИИ-штампов в ответе. Тексты придуманы, данных кейса здесь нет."""
import re

import pytest

from copilot import i18n, style
from copilot.drafts import Draft

DASHES = "—–―‒−"


def no_dash(text: str) -> bool:
    return not any(ch in text for ch in DASHES) and "--" not in text and " - " not in text


def test_em_dash_replaced():
    out = style.clean("Нарушение подтверждено — мут 30 минут.", "ru")
    assert no_dash(out) and out == "Нарушение подтверждено, мут 30 минут."


def test_dash_before_capital_becomes_sentence_break():
    out = style.clean("Проверим запись — Администратор ответит позже.", "ru")
    assert no_dash(out) and "запись. Администратор" in out


def test_numeric_range_in_russian_gets_words():
    assert style.clean("Мут 15–30 минут.", "ru") == "Мут от 15 до 30 минут."
    assert style.clean("Мут от 15–30 минут.", "ru") == "Мут от 15 до 30 минут."
    assert style.clean("Мут 15-30 минут.", "ru") == "Мут от 15 до 30 минут."


def test_spaced_hyphen_and_double_hyphen_replaced_but_word_hyphen_kept():
    out = style.clean("Кто-то нарушил правила - мы проверим -- спасибо.", "ru")
    assert no_dash(out) and "Кто-то" in out


def test_slash_replaced_outside_urls_only():
    assert style.clean("Напишите нам и/или в чат.", "ru") == "Напишите нам или в чат."
    assert style.clean("Пришлите скрин/видео.", "ru") == "Пришлите скрин или видео."
    url = "https://support.grnd.gg/"
    assert style.clean(f"Поддержка: {url}.", "ru") == f"Поддержка: {url}."


def test_emoji_and_arrows_removed():
    assert style.clean("Готово 🙂 → проверим ✅", "ru") == "Готово проверим"


def test_markdown_removed():
    out = style.clean("**Важно**: проверим `запись`.\n# Итог", "ru")
    assert "*" not in out and "`" not in out and "#" not in out


def test_ellipsis_becomes_period():
    assert style.clean("Проверим запись… и ответим...", "ru") == "Проверим запись. и ответим."


def test_only_first_exclamation_kept():
    assert style.clean("Здравствуйте! Спасибо! Проверим!", "ru") == "Здравствуйте! Спасибо. Проверим."


def test_placeholder_dash_sentence_dropped():
    out = style.clean("Нарушение: читы. Наказание по правилам: —. Срок назначит администратор.", "ru")
    assert out == "Нарушение: читы. Срок назначит администратор."


@pytest.mark.parametrize("text,code", [
    ("Конечно! Рад помочь с вашим вопросом.", "stamp"),
    ("Важно отметить, что запись нужна.", "stamp"),
    ("Не стесняйтесь обращаться снова.", "stamp"),
    ("As an AI model I cannot do that.", "stamp"),
    ("Certainly! Feel free to ask.", "stamp"),
    ("Вот ответ: {\"text\": \"x\"}", "markup"),
])
def test_slop_is_reported(text, code):
    assert any(i.startswith(code) for i in style.issues(text, "ru"))


def test_clean_text_has_no_issues():
    assert style.issues("Здравствуйте! Нарушение подтверждено по п. 2.1. Мут чата от 15 до 30 минут.", "ru") == []


@pytest.mark.parametrize("lang,raw,want", [
    ("uz", "Jazo: mute (15–30 daqiqa).", "Jazo: mute (15 dan 30 daqiqagacha)."),
    ("uz", "Bloklash 3-10 kun.", "Bloklash 3 dan 10 kungacha."),
    ("kk", "Жаза: мут (30–60 минут).", "Жаза: мут (30 минуттан 60 минутқа дейін)."),
    ("kk", "Бұғаттау 3–10 күн.", "Бұғаттау 3 күннен 10 күнге дейін."),
    ("en", "A mute of 15–30 minutes.", "A mute of 15 to 30 minutes."),
    ("es", "Silencio de 15–30 minutos.", "Silencio de 15 a 30 minutos."),
    ("pt", "Silenciamento 15–30 minutos.", "Silenciamento de 15 a 30 minutos."),
])
def test_numeric_range_keeps_meaning_in_every_language(lang, raw, want):
    """Диапазон нельзя заменять запятой: «15, 30 минут» читается как два отдельных срока."""
    out = style.clean(raw, lang)
    assert out == want and not any(ch in out for ch in DASHES)


def test_sanction_ranges_are_dash_free_at_the_source():
    from copilot import sanctions
    for lang in ("ru", "kk", "uz", "en", "es", "pt"):
        for unit in ("min", "day"):
            text = sanctions._span(sanctions.Sanction("mute", 15, 30, unit=unit), lang)
            assert text and not any(ch in text for ch in DASHES), (lang, unit, text)


def test_range_with_unknown_unit_is_left_and_reported():
    out = style.clean("Jazo 15–30 sekund.", "uz")
    assert "15–30" in out and any(i.startswith("dash") for i in style.issues(out, "uz"))


def test_apply_draft_cleans_text_and_alternatives():
    d = Draft(lang="ru", text="Здравствуйте! Мут — 30 минут 🙂", cited=["2.1"], intent="approve", auto_ok=True,
              alternatives=[{"intent": "appeal_reject", "text": "Отказ — решение принято.", "cited": []}])
    out = style.apply_draft(d)
    assert no_dash(out.text) and "🙂" not in out.text
    assert no_dash(out.alternatives[0]["text"])
    assert out.auto_ok is True and out.reasons == d.reasons


def test_apply_draft_blocks_auto_send_when_stamp_remains():
    d = Draft(lang="ru", text="Здравствуйте! Конечно, рад помочь.", intent="clarify", auto_ok=True)
    out = style.apply_draft(d)
    assert out.auto_ok is False and any("стиль" in r for r in out.reasons)


def _fill(tpl: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: i18n.SUPPORT_URL if m.group(1) == "support" else
                  i18n.DISCORD_URL if m.group(1) == "discord" else "п. 2.1", tpl)


@pytest.mark.parametrize("lang", sorted(i18n.T))
def test_every_template_is_clean_after_filter(lang):
    """Регрессия: ни один встроенный шаблон не должен нарушать стиль, иначе запретное окажется в ответе жюри."""
    bad = []
    for key, tpl in i18n.T[lang].items():
        if not isinstance(tpl, str):
            continue
        text = style.clean(_fill(tpl), lang)
        found = style.issues(text, lang)
        if found:
            bad.append((key, found))
    assert not bad, bad
