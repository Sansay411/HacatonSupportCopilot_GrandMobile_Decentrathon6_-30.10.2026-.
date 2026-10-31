"""Сводка эксперимента с классификаторами: таблицы, парный бутстреп относительно A_prod, ошибки по классам.

Правило решения зафиксировано до просмотра результатов: кандидат заменяет production-модель, только если
(1) на отложенной части train (n≈17,7 тыс., группы повторов отделены) macro-F1 выше и 95 %-интервал разности не содержит 0;
(2) на «чистых» тикетах valid (n=627) точечная разность accuracy и macro-F1 не отрицательна;
(3) ни один из фокусных классов не теряет более 0,05 recall на valid;
(4) задержка предсказания не растёт заметно. Иначе остаётся A_prod.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import numpy as np  # noqa: E402
from sklearn.metrics import accuracy_score, f1_score  # noqa: E402

FOCUS = ["complaint.other", "complaint.invalid", "report.question", "complaint.admin", "report.payment", "report.account",
         "report.help", "report.offtopic", "complaint.scam", "complaint.cheat"]
NAMES = ["A_prod", "A_C1", "A_C16", "D_svc_cal", "V_wide_LR"]


def mf1(y, p):
    return f1_score(y, p, average="macro", zero_division=0)


def main():
    rb = C.load_rb()
    valid = C.load_valid(rb)
    train = C.load_train(rb)
    flags = C.leak_flags(valid, train)
    clean = np.array([f == "clean" for f in flags])
    y_v = np.array([r["gold_cat"] for r in valid])
    res, preds = {}, {}
    for n in NAMES:
        f = C.CACHE / f"clf_{n}.json"
        if f.exists():
            res[n] = json.loads(f.read_text(encoding="utf-8"))
            preds[n] = pickle.loads((C.CACHE / f"clf_{n}_preds.pkl").read_bytes())
    base = "A_prod"
    out = {"protocol": __doc__.strip(), "label_note": "valid: собственная разметка; holdout: слабая разметка train (правила + исход админа)",
           "candidates": {}}
    for n, r in res.items():
        v, h = r["valid_own_labels"], r["holdout_weak_labels"]
        pv, ph = preds[n]["valid"], preds[n]["holdout"]
        entry = {
            "holdout": {"accuracy": h["accuracy"], "macro_f1": h["macro_f1"], "n": h["n"], "by_lang": h["by_lang"]},
            "valid_all": {k: v["all"][k] for k in ("accuracy", "macro_f1", "priority_macro_f1", "priority_accuracy", "ece")},
            "valid_clean": {k: v["clean"][k] for k in ("accuracy", "macro_f1", "priority_macro_f1", "priority_accuracy", "ece")},
            "valid_clean_by_lang": v["clean_by_lang"],
            "translit_probe_clean_ru": r["translit_probe_clean_ru"],
            "focus_recall_valid_all": {c: v["all"]["per_class"].get(c, {}).get("r") for c in FOCUS},
            "focus_f1_valid_clean": {c: v["clean"]["per_class"].get(c, {}).get("f1") for c in FOCUS},
            "focus_f1_holdout": {c: h["per_class"].get(c, {}).get("f1") for c in FOCUS},
            "predict_ms_per_ticket": r["predict_ms_per_ticket"],
        }
        if n != base:
            pb, hb = preds[base]["valid"], preds[base]["holdout"]
            idx = np.where(clean)[0]
            entry["vs_A_prod"] = {
                "holdout_macro_f1": C.paired_bootstrap(hb["y"], hb["cat"], ph["cat"], mf1, n=300),
                "holdout_accuracy": C.paired_bootstrap(hb["y"], hb["cat"], ph["cat"], accuracy_score, n=300),
                "valid_all_accuracy": C.paired_bootstrap(y_v, pb["cat"], pv["cat"], accuracy_score),
                "valid_clean_accuracy": C.paired_bootstrap(y_v[idx], np.array(pb["cat"])[idx], np.array(pv["cat"])[idx], accuracy_score),
                "valid_clean_macro_f1": C.paired_bootstrap(y_v[idx], np.array(pb["cat"])[idx], np.array(pv["cat"])[idx], mf1),
            }
            b_rec = res[base]["valid_own_labels"]["all"]["per_class"]
            drops = {c: round((v["all"]["per_class"].get(c, {}).get("r", 0) or 0) - (b_rec.get(c, {}).get("r", 0) or 0), 3)
                     for c in FOCUS if c in b_rec and b_rec[c]["n"] >= 10}
            entry["focus_recall_delta_vs_A_prod"] = drops
            d = entry["vs_A_prod"]
            entry["decision_rule"] = {
                "1_holdout_f1_ci_above_0": d["holdout_macro_f1"]["ci95"][0] > 0,
                "2_clean_point_deltas_nonneg": d["valid_clean_accuracy"]["delta"] >= 0 and d["valid_clean_macro_f1"]["delta"] >= 0,
                "3_no_focus_recall_drop_over_0.05": all(x >= -0.05 for x in drops.values()),
                "4_latency_ok": r["predict_ms_per_ticket"] <= 1.5 * res[base]["predict_ms_per_ticket"] + 1,
            }
            entry["adopt"] = all(entry["decision_rule"].values())
        out["candidates"][n] = entry
    (C.OUT / "classifier_experiment.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'candidate':11s} | holdout acc  F1    | valid-all acc  F1    priF1 | valid-clean acc  F1    priF1 | ECE(c) | ms | adopt")
    for n, e in out["candidates"].items():
        print(f"{n:11s} | {e['holdout']['accuracy']:.4f} {e['holdout']['macro_f1']:.4f} | {e['valid_all']['accuracy']:.3f} "
              f"{e['valid_all']['macro_f1']:.3f} {e['valid_all']['priority_macro_f1']:.3f} | {e['valid_clean']['accuracy']:.3f} "
              f"{e['valid_clean']['macro_f1']:.3f} {e['valid_clean']['priority_macro_f1']:.3f} | {e['valid_clean']['ece']:.3f} | "
              f"{e['predict_ms_per_ticket']:.2f} | {e.get('adopt', '(база)')}")
    for n, e in out["candidates"].items():
        if "vs_A_prod" in e:
            print(n, json.dumps(e["vs_A_prod"], ensure_ascii=False))
            print("   rule:", e["decision_rule"], "focus recall delta:", e["focus_recall_delta_vs_A_prod"])
    print("translit probe:", {n: e["translit_probe_clean_ru"] for n, e in out["candidates"].items()})
    print("focus f1 clean:")
    for n, e in out["candidates"].items():
        print(" ", n, {k: v for k, v in e["focus_f1_valid_clean"].items() if v is not None})


if __name__ == "__main__":
    main()
