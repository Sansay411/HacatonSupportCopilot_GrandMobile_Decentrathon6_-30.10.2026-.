"""Триаж одного обращения: вход по контракту POST /triage, выход по контракту."""
from __future__ import annotations

import json
import logging
import os
import pickle
import time
from pathlib import Path

from scipy.sparse import csr_matrix, hstack

from . import dedup as dedup_mod
from . import drafts, guard, lang as lang_mod
from .classifier import CategoryModel
from .features import model_text
from .rules import load as load_rules
from .signals import extract
from .taxonomy import priority_rules
from .ticket import from_dict

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("copilot")
NEEDS_HUMAN_ALWAYS = {"report.account", "report.payment", "complaint.admin"}


class Copilot:
    def __init__(self, data_dir: str | Path | None = None, models_dir: str | Path | None = None, llm=None):
        data_dir = Path(data_dir or os.environ.get("COPILOT_DATA", ROOT / "data"))
        models_dir = Path(models_dir or os.environ.get("COPILOT_MODELS", ROOT / "models"))
        if not (data_dir / "rules.json").exists():
            raise FileNotFoundError(f"нет {data_dir / 'rules.json'}: положите выдачу кейса в data/ "
                                    f"(rules.json, taxonomy.json) или задайте COPILOT_DATA")
        self.rules = load_rules(str(data_dir / "rules.json"))
        tax_path = data_dir / "taxonomy.json"
        if tax_path.exists():
            tax = json.loads(tax_path.read_text(encoding="utf-8"))
            NEEDS_HUMAN_ALWAYS.update(tax.get("needs_human_always", []))
        self.category_model = CategoryModel(models_dir / "category.pkl")
        if not self.category_model.loaded:
            log.warning("%s не найден: классификатор работает только по правилам, качество ниже (выполните make train)",
                        models_dir / "category.pkl")
        self.verdict_model = None
        vp = models_dir / "verdict.pkl"
        if vp.exists():
            with open(vp, "rb") as f:
                self.verdict_model = pickle.load(f)
        self.dedup = dedup_mod.DedupStore()
        self.llm = llm

    # ------------------------------------------------------------------
    def _verdict(self, t, sig) -> tuple[str | None, float]:
        if self.verdict_model is None:
            return ("approve" if sig.rule_refs or sig.topics & {"insult", "dm", "cheat", "scam"} else "need_evidence"), 0.5
        X = hstack([self.verdict_model["vec"].transform([model_text(t, sig)]),
                    csr_matrix([[min(t.images, 6) / 6, float(sig.has_url), float(sig.words <= 2), float(sig.words > 15),
                                 float(bool(sig.rule_refs))]])]).tocsr()
        clf = self.verdict_model["clf"]
        p = clf.predict_proba(X)[0]
        i = int(p.argmax())
        return clf.classes_[i], float(p[i])

    def triage(self, payload: dict, *, use_dedup: bool = True) -> dict:
        t0 = time.perf_counter()
        t = from_dict(payload)
        text_lang = lang_mod.detect(t.player_text, t.server_lang)
        reply_lang = lang_mod.reply_lang(text_lang, t.server_lang)
        sig = extract(t.player_text, self.rules, t.rule_refs_raw, t.images, t.reported_nick)
        cat = self.category_model.predict(t, sig)
        priority = priority_rules(cat.category, sig)

        spam = dedup_mod.is_spam(t.player_text)
        dup_reason = None
        if use_dedup:
            dup_reason = self.dedup.check_and_add(
                reporter=t.reporter_hash or payload.get("reporter"), reported=t.reported_hash or t.reported_nick,
                text=t.player_text, kind=t.kind, created_at=t.created_at, category=cat.category)

        verdict, vconf = (None, 1.0)
        if t.kind == "complaint" and cat.category not in ("complaint.admin", "complaint.invalid"):
            verdict, vconf = self._verdict(t, sig)

        category_for_draft = cat.category
        if spam and t.kind == "complaint" and category_for_draft != "complaint.admin":
            category_for_draft = "complaint.invalid"
        d = drafts.build(t.kind, category_for_draft, sig, t.player_text, reply_lang, self.rules,
                         verdict, t.reported_nick or sig.nickname, duplicate=bool(dup_reason),
                         verdict_conf=vconf)

        if self.llm is not None and d.intent in self.llm.intents:
            d = self.llm.polish(d, t, sig, cat.category, self.rules)

        cited, guard_reasons = guard.check(d.text, d.cited, self.rules)
        reasons = list(d.reasons) + guard_reasons
        if dup_reason:
            reasons.append(dup_reason)
        if spam:
            reasons.append("признаки спама или флуда")

        confidence = round(min(cat.confidence, vconf if verdict else 1.0), 2)
        needs_human = (not d.auto_ok) or bool(guard_reasons) or d.proposes_penalty
        if cat.category in NEEDS_HUMAN_ALWAYS:
            needs_human = True
            if "всегда" not in " ".join(reasons):
                reasons.append(f"категория {cat.category} всегда идёт человеку")
        if priority == "p0":
            needs_human = True
            reasons.append("приоритет p0")
        if "admin_subject" in sig.topics:
            needs_human = True
            reasons.append("обращение на действия администратора: решает старшая администрация")
        if confidence < 0.5 and not dup_reason:
            needs_human = True
            reasons.append(f"низкая уверенность классификации ({confidence})")

        extracted_refs = [r for r in sig.rule_refs if self.rules.exists(r)]
        return {
            "lang": text_lang if text_lang != "uk" else "ru",
            "category": cat.category,
            "priority": priority,
            "is_spam_or_duplicate": bool(spam or dup_reason),
            "extracted": {
                "nickname": t.reported_nick or sig.nickname,
                "rule_refs": extracted_refs,
                "has_evidence": bool(sig.has_evidence),
                "server": sig.server,
            },
            "draft_reply": {"lang": d.lang, "text": d.text, "cited": cited},
            "needs_human": needs_human,
            "confidence": confidence,
            "reasons": reasons,
            "_meta": {"intent": d.intent, "verdict_pred": verdict, "category_source": cat.source,
                      "alternatives": [dict(a, cited=[c for c in a["cited"] if self.rules.exists(c)]) for a in d.alternatives],
                      "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                      "llm": bool(self.llm and d.intent in getattr(self.llm, "intents", ()))},
        }
