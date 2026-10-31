"""Сводка по повторным разбиениям (A_prod против D_svc_cal) и точный тест McNemar на valid.

Запуск после clf_experiment.py (все seed) и clf_adopt_check.py: python experiments/final_quality/clf_summary.py
"""
from __future__ import annotations

import json
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    out = {"splits": {}}
    for seed, pre in ((C.SEED, ""), (11, "seed11_"), (12, "seed12_")):
        a = json.loads((C.CACHE / f"{pre}clf_A_prod.json").read_text(encoding="utf-8"))
        d = json.loads((C.CACHE / f"{pre}clf_D_svc_cal.json").read_text(encoding="utf-8"))
        row = {}
        for name, src in (("A_prod", a), ("D_svc_cal", d)):
            row[name] = {"holdout_acc": src["holdout_weak_labels"]["accuracy"], "holdout_macro_f1": src["holdout_weak_labels"]["macro_f1"],
                         "valid_all_acc": src["valid_own_labels"]["all"]["accuracy"], "valid_all_macro_f1": src["valid_own_labels"]["all"]["macro_f1"],
                         "valid_clean_acc": src["valid_own_labels"]["clean"]["accuracy"],
                         "valid_clean_macro_f1": src["valid_own_labels"]["clean"]["macro_f1"]}
        row["delta_D_minus_A"] = {k: round(row["D_svc_cal"][k] - row["A_prod"][k], 4) for k in row["A_prod"]}
        out["splits"][f"seed_{seed}"] = row
    chk = json.loads((C.OUT / "classifier_adoption_check.json").read_text(encoding="utf-8"))
    ch = chk["category_changes"]
    out["valid_pipeline_full_train"] = {
        "category_changed": ch["changed"], "LR_wrong_to_SVC_right": ch["LR_wrong_to_SVC_right"],
        "LR_right_to_SVC_wrong": ch["LR_right_to_SVC_wrong"], "both_wrong": ch["both_wrong"],
        "mcnemar_exact_p": round(mcnemar_exact(ch["LR_wrong_to_SVC_right"], ch["LR_right_to_SVC_wrong"]), 4)}
    out["gate_decision"] = {
        "adopt": False,
        "reason": "правило пользователя: любой невыполненный критерий оставляет baseline. Прирост accuracy на отложенной части train "
                  "значим во всех трёх разбиениях, но на valid с независимой разметкой он не значим (McNemar), а по заранее "
                  "заданному правилу не выполнен критерий задержки (5,5 мс против 1,75 мс на тикет, существенно только формально).",
        "ready_to_enable": "var/final_quality/models_D/category.pkl (обучена на всём train); включение: скопировать в models/ "
                           "или задать COPILOT_MODELS"}
    (C.OUT / "classifier_repeat_splits.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
