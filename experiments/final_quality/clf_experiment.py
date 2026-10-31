"""Эксперимент с классификатором категории. Production-модель не меняется.

Протокол (зафиксирован до запуска, чтобы не подгонять под valid):
* Одно и то же разбиение train по ГРУППАМ повторов (одинаковый текст или пара заявитель+нарушитель): 85 % обучение,
  15 % отложенная часть. Все кандидаты учатся на одних и тех же строках.
* Выбор кандидата только по отложенной части train (метки слабые: правила + исход админа), valid используется как
  подтверждение и не участвует в выборе. Разметка valid собственная (valid_gold.json), официальной нет.
* Метрики valid считаются целиком и отдельно на «чистых» тикетах, чей текст не встречался в train.
* Решение считается через production-логику CategoryModel.predict (модель + жёсткие правила), а не только по сырой модели.
* Устойчивость к транслитерации (кириллица -> латиница) только измеряется, на выбор не влияет.

Запуск: python experiments/final_quality/clf_experiment.py [--only A_prod,D_svc_cal]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from common import ROOT  # noqa: E402

import numpy as np  # noqa: E402
from scipy.sparse import hstack  # noqa: E402
from sklearn.calibration import CalibratedClassifierCV  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import accuracy_score, f1_score  # noqa: E402
from sklearn.svm import LinearSVC  # noqa: E402

from copilot.classifier import CategoryModel  # noqa: E402
from copilot.signals import extract  # noqa: E402
from copilot.taxonomy import priority_rules  # noqa: E402
from copilot.ticket import from_dict  # noqa: E402

FOCUS = ["complaint.other", "complaint.invalid", "report.question", "complaint.admin", "report.payment", "report.account",
         "report.help", "report.offtopic", "complaint.scam", "complaint.cheat"]


def vecs(name: str):
    if name == "prod":     # ровно как scripts/train.py
        return (TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_features=60000, sublinear_tf=True,
                                token_pattern=r"(?u)[\w.']+"),
                TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, max_features=120000, sublinear_tf=True))
    if name == "wide":     # шире n-граммы: тест гипотезы «не хватает контекста у коротких жалоб»
        return (TfidfVectorizer(analyzer="word", ngram_range=(1, 3), min_df=2, max_features=100000, sublinear_tf=True,
                                token_pattern=r"(?u)[\w.']+"),
                TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 6), min_df=3, max_features=200000, sublinear_tf=True))
    raise KeyError(name)


CANDIDATES = {
    "A_prod": ("prod", lambda: LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced", random_state=0)),
    "A_C1": ("prod", lambda: LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced", random_state=0)),
    "A_C16": ("prod", lambda: LogisticRegression(max_iter=2000, C=16.0, class_weight="balanced", random_state=0)),
    "D_svc_cal": ("prod", lambda: CalibratedClassifierCV(
        LinearSVC(C=0.3, class_weight="balanced", random_state=0), method="sigmoid", cv=3)),
    "V_wide_LR": ("wide", lambda: LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced", random_state=0)),
}

_CYR = dict(zip("абвгдезийклмнопрстуфхъыьэ", "abvgdezijklmnoprstufh'y'e"))
_CYR.update({"ё": "yo", "ж": "zh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ю": "yu", "я": "ya",
             "қ": "q", "ғ": "g'", "ң": "ng", "ө": "o'", "ұ": "u", "ү": "u", "ә": "a", "һ": "h", "і": "i"})


def translit(text: str) -> str:
    return "".join(_CYR.get(ch.lower(), ch) for ch in text)


def fit_candidate(name, train, tr_idx):
    vname, make = CANDIDATES[name]
    models = {}
    for kind in ("complaint", "report"):
        ix = [i for i in tr_idx if train[i]["kind"] == kind]
        texts = [train[i]["mtext"] for i in ix]
        y = [train[i]["y_weak"] for i in ix]
        w, c = vecs(vname)
        X = hstack([w.fit_transform(texts), c.fit_transform(texts)]).tocsr()
        t0 = time.time()
        clf = make().fit(X, y)
        print(f"  [{name}] {kind}: n={len(ix)} fit {time.time() - t0:.0f}s", flush=True)
        models[kind] = {"word": w, "char": c, "clf": clf}
    return models


def decide(models, items):
    """items: [(t, sig)] -> [(category, confidence)] через production CategoryModel.predict."""
    cm = CategoryModel(None)
    cm.models = models
    out = []
    for t, sig in items:
        r = cm.predict(t, sig)
        out.append((r.category, r.confidence))
    return out


def ece(conf, correct, bins=10):
    conf, correct = np.asarray(conf), np.asarray(correct, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            e += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return round(float(e), 4)


def holdout_objects(ho_idx, rb):
    """(t, sig) для отложенных строк train: перечитываем исходный файл только для нужных индексов."""
    want = set(int(i) for i in ho_idx)
    out = {}
    for i, d in enumerate(C.iter_jsonl(ROOT / "data/tickets_train.jsonl.gz")):
        if i in want:
            t = from_dict(d)
            out[i] = (t, extract(t.player_text, rb, t.rule_refs_raw, t.images, t.reported_nick))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--smoke", action="store_true", help="быстрый прогон на малой выборке для проверки кода")
    ap.add_argument("--seed", type=int, default=C.SEED, help="seed группового разбиения train (повторы для устойчивости)")
    args = ap.parse_args()
    prefix = ("smoke_" if args.smoke else "") + ("" if args.seed == C.SEED else f"seed{args.seed}_")
    names = [n for n in (args.only.split(",") if args.only else CANDIDATES) if n]

    rb = C.load_rb()
    train = C.load_train(rb)
    valid = C.load_valid(rb)
    flags = C.leak_flags(valid, train)
    for r, f in zip(valid, flags):
        r["leak"] = f
    tr_idx, ho_idx, _ = C.group_holdout(train, 0.15, seed=args.seed)
    if args.smoke:
        rng = np.random.default_rng(0)
        tr_idx, ho_idx = np.sort(rng.choice(tr_idx, 6000, replace=False)), np.sort(rng.choice(ho_idx, 1500, replace=False))
    print(f"train {len(train)}: fit {len(tr_idx)}, holdout {len(ho_idx)} (group split, seed {C.SEED})", flush=True)
    ho_obj = holdout_objects(ho_idx, rb)
    ho_items = [ho_obj[int(i)] for i in ho_idx]
    ho_y = [train[int(i)]["y_weak"] for i in ho_idx]
    ho_lang = [train[int(i)]["server_lang"] for i in ho_idx]
    v_items = [(r["t"], r["sig"]) for r in valid]
    v_y = [r["gold_cat"] for r in valid]
    v_yp = [r["gold_pri"] for r in valid]
    clean = np.array([r["leak"] == "clean" for r in valid])
    v_lang = np.array([r["server_lang"] for r in valid])

    # транслитерация: те же чистые ru-тикеты, но текст латиницей (диагностика)
    tl_idx = [i for i, r in enumerate(valid) if r["leak"] == "clean" and r["server_lang"] == "ru"]
    tl_items = []
    for i in tl_idx:
        d = dict(valid[i]["t"].raw)
        d["messages"] = [dict(m, text=translit(m.get("text") or "")) if m.get("role", "player") == "player" else m
                         for m in d["messages"]]
        t = from_dict(d)
        tl_items.append((t, extract(t.player_text, rb, t.rule_refs_raw, t.images, t.reported_nick)))

    for name in names:
        t0 = time.time()
        models = fit_candidate(name, train, tr_idx)
        # 1. отложенная часть train, решение production (метки слабые)
        ho_pred = decide(models, ho_items)
        ho_cat = [p[0] for p in ho_pred]
        hold = C.metrics_cat(ho_y, ho_cat)
        hold["by_lang"] = {lg: {"n": sum(1 for x in ho_lang if x == lg),
                                "accuracy": round(float(accuracy_score([y for y, g in zip(ho_y, ho_lang) if g == lg],
                                                                       [p for p, g in zip(ho_cat, ho_lang) if g == lg])), 4),
                                "macro_f1": round(float(f1_score([y for y, g in zip(ho_y, ho_lang) if g == lg],
                                                                 [p for p, g in zip(ho_cat, ho_lang) if g == lg],
                                                                 average="macro")), 4)}
                           for lg in ("ru", "uz", "kk") if any(x == lg for x in ho_lang)}
        # 2. valid, собственная разметка
        vp = decide(models, v_items)
        v_cat = [p[0] for p in vp]
        v_conf = [p[1] for p in vp]
        v_pri = [priority_rules(c, sig) for c, (_, sig) in zip(v_cat, v_items)]
        res_valid = {}
        for label, mask in (("all", np.ones(len(valid), bool)), ("clean", clean)):
            ix = np.where(mask)[0]
            m = C.metrics_cat([v_y[i] for i in ix], [v_cat[i] for i in ix])
            m["priority_macro_f1"] = round(float(f1_score([v_yp[i] for i in ix], [v_pri[i] for i in ix], average="macro")), 4)
            m["priority_accuracy"] = round(float(accuracy_score([v_yp[i] for i in ix], [v_pri[i] for i in ix])), 4)
            m["ece"] = ece([v_conf[i] for i in ix], [v_cat[i] == v_y[i] for i in ix])
            res_valid[label] = m
        res_valid["clean_by_lang"] = {}
        for lg in ("ru", "uz", "kk"):
            ix = np.where(clean & (v_lang == lg))[0]
            if len(ix):
                res_valid["clean_by_lang"][lg] = {"n": int(len(ix)),
                                                   "accuracy": round(float(accuracy_score([v_y[i] for i in ix], [v_cat[i] for i in ix])), 4)}
        # 3. транслитерация
        tp = decide(models, tl_items)
        base_pred = [v_cat[i] for i in tl_idx]
        res_tl = {"n": len(tl_idx),
                  "accuracy_original": round(float(accuracy_score([v_y[i] for i in tl_idx], base_pred)), 4),
                  "accuracy_translit": round(float(accuracy_score([v_y[i] for i in tl_idx], [p[0] for p in tp])), 4),
                  "same_prediction_share": round(float(np.mean([a == b[0] for a, b in zip(base_pred, tp)])), 4)}
        # задержка одного предсказания
        t1 = time.perf_counter()
        decide(models, v_items[:200])
        lat_ms = (time.perf_counter() - t1) / 200 * 1000
        result = {"candidate": name, "vectorizer": CANDIDATES[name][0], "fit_seconds": round(time.time() - t0),
                  "holdout_weak_labels": hold, "valid_own_labels": res_valid, "translit_probe_clean_ru": res_tl,
                  "predict_ms_per_ticket": round(lat_ms, 3)}
        (C.CACHE / f"{prefix}clf_{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        (C.CACHE / f"{prefix}clf_{name}_preds.pkl").write_bytes(pickle.dumps(
            {"valid": {"cat": v_cat, "conf": v_conf, "pri": v_pri}, "holdout": {"cat": ho_cat, "y": ho_y}}))
        print(f"[{name}] holdout acc={hold['accuracy']} F1={hold['macro_f1']} | valid all acc={res_valid['all']['accuracy']} "
              f"F1={res_valid['all']['macro_f1']} | clean acc={res_valid['clean']['accuracy']} F1={res_valid['clean']['macro_f1']} "
              f"| total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
