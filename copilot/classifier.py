"""Классификатор категории: модель TF-IDF + логрегрессия поверх правил.

Порядок решения:
1. Жёсткие правила с высокой точностью (обжалование, платёж, аккаунт,
   пустой текст) переопределяют модель: ошибка там дорогая.
2. Иначе берём модель; при низкой уверенности модели и согласии правил
   с одним из двух лучших классов модели берём правила.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

from scipy.sparse import hstack

from .features import model_text
from .signals import Signals
from .taxonomy import label_rules


@dataclass
class CategoryResult:
    category: str
    confidence: float
    source: str
    rules_category: str


_HARD = {"report.payment", "report.account"}


class CategoryModel:
    def __init__(self, path: str | Path | None):
        self.models = None
        if path and Path(path).exists():
            with open(path, "rb") as f:
                self.models = pickle.load(f)

    @property
    def loaded(self) -> bool:
        return self.models is not None

    def _proba(self, kind: str, text: str):
        m = self.models[kind]
        X = hstack([m["word"].transform([text]), m["char"].transform([text])]).tocsr()
        p = m["clf"].predict_proba(X)[0]
        return sorted(zip(m["clf"].classes_, p), key=lambda x: -x[1])

    def predict(self, t, sig: Signals) -> CategoryResult:
        rules_cat = label_rules(t.kind, sig, t.player_text)
        if not self.loaded:
            return CategoryResult(rules_cat, 0.6, "rules", rules_cat)
        ranked = self._proba(t.kind, model_text(t, sig))
        top, p = ranked[0]
        if rules_cat in _HARD:
            return CategoryResult(rules_cat, max(p if top == rules_cat else 0.0, 0.85), "rules", rules_cat)
        if rules_cat == "complaint.admin" and "appeal" in sig.topics:
            return CategoryResult(rules_cat, max(p if top == rules_cat else 0.0, 0.8), "rules", rules_cat)
        if sig.content_free:
            invalid = "complaint.invalid" if t.kind == "complaint" else "report.offtopic"
            return CategoryResult(invalid, 0.9, "rules", rules_cat)
        if p < 0.55 and rules_cat in (ranked[1][0], top):
            conf = dict(ranked).get(rules_cat, p)
            return CategoryResult(rules_cat, float(conf), "rules+model", rules_cat)
        return CategoryResult(top, float(p), "model", rules_cat)
