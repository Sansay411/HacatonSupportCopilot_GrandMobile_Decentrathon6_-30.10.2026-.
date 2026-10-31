"""Независимая политика безопасной автоматизации (Stage 3).

Разделяет три ортогональных вопроса при принятии решения об автоответе:
1. can_draft              — может ли Sentra сформировать полезный черновик ответа без нарушений guard/verify;
2. has_verified_knowledge — опирается ли ответ на подтверждённое знание (rules.json, kb.py или детерминированную
                            инструкцию самообслуживания, не требующую живого действия администратора в игре);
3. allow_auto_reply       — разрешена ли отправка ответа игроку без участия человека (needs_human = not allow_auto_reply).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import drafts
from .signals import Signals

NEEDS_HUMAN_ALWAYS: set[str] = {"report.account", "report.payment", "complaint.admin"}

# Сценарии, где ответ полностью опирается на проверенное правило (rules.json), запись KB (kb.py)
# или детерминированную инструкцию самообслуживания (лаунчер / форум / кнопка эвакуатора)
VERIFIED_SELF_SERVICE_INTENTS: frozenset[str] = frozenset({
    "question_kb",
    "question_tech",
    "question_howto",
    "help_vehicle",
    "help_service",
    "not_complaint",
    "no_description",
    "toxic",
    "offtopic_flood",
    "report_rp",
    "clarify",
})

# Сценарии, в которых у Sentra есть точное знание правил/процедуры для черновика оператору,
# но финальное действие (проверка доказательств, вынесение/снятие наказания, проверка платежа/аккаунта)
# обязан выполнить человек
VERIFIED_HUMAN_DECISION_INTENTS: frozenset[str] = frozenset({
    "approve",
    "need_evidence",
    "appeal",
    "appeal_reject",
    "report_appeal",
    "admin_complaint",
    "payment",
    "account",
    "threat",
})

# Детерминированные сценарии с явным позитивным триггером (KB, правила подачи жалоб, техподдержка,
# кнопка эвакуатора, отказ в несервисной просьбе по п. 3.1), где корректность ответа определяется
# подтверждённым правилом/шаблоном, а не границей вероятностей классификатора между соседними классами
CONFIDENCE_EXEMPT_SAFE_INTENTS: frozenset[str] = frozenset({
    "question_kb",
    "question_tech",
    "question_howto",
    "help_vehicle",
    "help_service",
    "not_complaint",
    "no_description",
    "toxic",
    "offtopic_flood",
})

_KB_REASON_RE = re.compile(r"базы знаний «([^»]+)»")


@dataclass(frozen=True)
class AutomationDecision:
    can_draft: bool
    has_verified_knowledge: bool
    allow_auto_reply: bool
    needs_human: bool
    knowledge_source: str
    reasons: list[str] = field(default_factory=list)


def _detect_knowledge_source(draft: drafts.Draft) -> tuple[bool, str]:
    """Определяет, опирается ли черновик на подтверждённый источник знаний."""
    for r in draft.reasons:
        m = _KB_REASON_RE.search(r)
        if m:
            return True, f"kb:{m.group(1)}"
    if draft.intent == "question_kb":
        return True, "kb"
    if draft.cited:
        return True, "rules.json"
    if draft.intent in VERIFIED_SELF_SERVICE_INTENTS:
        # report_rp и clarify считаются подтверждёнными только тогда, когда сам сценарий разрешил auto_ok
        if draft.intent in ("report_rp", "clarify") and not draft.auto_ok:
            return False, "none"
        return True, "self_service"
    if draft.intent in VERIFIED_HUMAN_DECISION_INTENTS:
        return True, "rules.json"
    return False, "none"


def evaluate_automation_policy(
    *,
    kind: str,
    category: str,
    priority: str,
    confidence: float,
    sig: Signals,
    player_text: str,
    draft: drafts.Draft,
    guard_reasons: list[str],
    action_claim: bool,
    dup_reason: str | None = None,
    dup_mandatory_human: bool = False,
    id_notes: list[str] | None = None,
    spam: bool = False,
    needs_human_categories: set[str] | None = None,
) -> AutomationDecision:
    """Вычисляет решение о безопасной автоматизации по трём независимым уровням."""
    always_human = needs_human_categories if needs_human_categories is not None else NEEDS_HUMAN_ALWAYS
    reasons = list(draft.reasons) + list(guard_reasons)
    if dup_reason and dup_reason not in reasons:
        reasons.append(dup_reason)
    if spam and "признаки спама или флуда" not in reasons:
        reasons.append("признаки спама или флуда")

    # 1. Может ли система предложить безопасный черновик без нарушений guard/verify?
    can_draft = bool(draft.text and draft.text.strip()) and not bool(guard_reasons) and not action_claim

    # 2. Есть ли подтверждённое знание в rules.json, kb.py или правилах самообслуживания?
    has_verified_knowledge, knowledge_source = _detect_knowledge_source(draft)

    # 3. Разрешена ли отправка без человека?
    if action_claim and draft.auto_ok:
        reasons.append("в тексте утверждение о передаче, рассмотрении или закрытии: отправка только после проверки человеком")

    needs_human = (
        (not can_draft)
        or (not has_verified_knowledge)
        or (not draft.auto_ok)
        or draft.proposes_penalty
    )

    if category in always_human:
        needs_human = True
        if "всегда" not in " ".join(reasons):
            reasons.append(f"категория {category} всегда идёт человеку")
    if priority == "p0":
        needs_human = True
        if "приоритет p0" not in reasons:
            reasons.append("приоритет p0")
    if "admin_subject" in sig.topics:
        needs_human = True
        admin_msg = "обращение на действия администратора: решает старшая администрация"
        if admin_msg not in reasons:
            reasons.append(admin_msg)

    esc_reasons = drafts.mandatory_escalation_reasons(kind, category, sig, player_text, intent=draft.intent)
    if esc_reasons:
        needs_human = True
        for r in esc_reasons:
            if r not in reasons:
                reasons.append(r)

    if id_notes:
        needs_human = True
        for r in id_notes:
            if r not in reasons:
                reasons.append(r)

    if dup_mandatory_human:
        needs_human = True
        orig_msg = "исходное обращение в цепочке дублей требует проверки человеком"
        if orig_msg not in reasons:
            reasons.append(orig_msg)

    # Низкая уверенность классификатора отправляет обращение человеку во всех неоднозначных случаях,
    # кроме детерминированных сценариев самообслуживания/KB с явным позитивным триггером во внутриигровых репортах.
    # Для жалоб исключения нет: жалоба со ссылкой на видео и уверенностью 0,26 была закрыта автоответом «раздел жалоб
    # не для вопросов», а порог 0,5 как раз и отправляет такие случаи человеку (docs/MERGE_REVIEW.md).
    is_confidence_exempt = draft.intent in CONFIDENCE_EXEMPT_SAFE_INTENTS and kind == "report"
    if confidence < 0.5 and not dup_reason:
        if needs_human or not is_confidence_exempt:
            needs_human = True
            low_conf_msg = f"низкая уверенность классификации ({confidence})"
            if low_conf_msg not in reasons:
                reasons.append(low_conf_msg)

    allow_auto_reply = not needs_human
    return AutomationDecision(
        can_draft=can_draft,
        has_verified_knowledge=has_verified_knowledge,
        allow_auto_reply=allow_auto_reply,
        needs_human=needs_human,
        knowledge_source=knowledge_source,
        reasons=reasons,
    )
