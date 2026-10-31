"""Baseline Sentra: повтор существующей оценки и разложение по утечке train -> valid, языкам и классам.

Разметка категории и приоритета на valid СОБСТВЕННАЯ (data/labels/valid_gold.json, правила + ручные правки команды).
Официальной разметки в выдаче нет, поэтому отдельного блока «official» тут нет и быть не может: см. REPORT.md.
Единственный независимый от нашей разметки ориентир в данных это вердикт админа (verdict), его показываем отдельно.

Запуск: python experiments/final_quality/baseline_decompose.py
Пишет reports/final_quality/baseline.json (только агрегаты) и var/final_quality/valid_baseline_triage.pkl (с текстами,
не коммитится).
"""
from __future__ import annotations

import json
import pickle
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from common import ROOT  # noqa: E402

from sklearn.metrics import accuracy_score, f1_score  # noqa: E402

from copilot.pipeline import Copilot  # noqa: E402
from copilot.taxonomy import priority_rules  # noqa: E402

INTENT_TO_VERDICT = {"approve": "approved", "need_evidence": "need_evidence", "no_description": "invalid_format",
                     "toxic": "invalid_format", "not_complaint": "rejected", "duplicate": "duplicate", "appeal": "appeal",
                     "appeal_reject": "appeal"}
VERDICT_GROUP = {"approved": "approved", "already_punished": "approved", "need_evidence": "need_evidence",
                 "invalid_format": "reject", "rejected": "reject", "duplicate": "duplicate",
                 "appeal_rejected": "appeal", "appeal_approved": "appeal"}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def scen_agree(rows, triage):
    agree = total = 0
    for r in rows:
        if r["kind"] != "complaint":
            continue
        vg = VERDICT_GROUP.get(r["verdict"])
        if not vg:
            continue
        iv = INTENT_TO_VERDICT.get(triage[r["ticket_id"]]["_meta"]["intent"])
        iv = {"invalid_format": "reject", "rejected": "reject"}.get(iv, iv)
        total += 1
        agree += int(iv == vg)
    return {"n": total, "agreement": round(agree / max(1, total), 3)}


def block(rows, pred_cat, pred_pri):
    y = [r["gold_cat"] for r in rows]
    yp = [r["gold_pri"] for r in rows]
    m = C.metrics_cat(y, [pred_cat[r["ticket_id"]] for r in rows])
    m["priority_macro_f1"] = round(float(f1_score(yp, [pred_pri[r["ticket_id"]] for r in rows], average="macro")), 4)
    m["priority_accuracy"] = round(float(accuracy_score(yp, [pred_pri[r["ticket_id"]] for r in rows])), 4)
    return m


def main():
    rb = C.load_rb()
    valid = C.load_valid(rb)
    train = C.load_train(rb)
    flags = C.leak_flags(valid, train)
    for r, f in zip(valid, flags):
        r["leak"] = f

    cp = Copilot()
    # категория и приоритет: ровно та логика, что внутри Copilot.triage (дедуп на них не влияет)
    pred_cat, pred_pri = {}, {}
    for r in valid:
        res = cp.category_model.predict(r["t"], r["sig"])
        pred_cat[r["ticket_id"]] = res.category
        pred_pri[r["ticket_id"]] = priority_rules(res.category, r["sig"])

    # полный triage в порядке created_at (как evaluate.py) для сценариев и задержки
    raw = {d["ticket_id"]: d for d in C.iter_jsonl(ROOT / "data/tickets_valid.jsonl")}
    order = sorted(valid, key=lambda r: raw[r["ticket_id"]].get("created_at") or "")
    triage, lat = {}, []
    for r in order:
        d = raw[r["ticket_id"]]
        payload = {k: v for k, v in d.items() if k not in ("verdict", "punishment", "violation", "category", "priority")}
        payload["messages"] = [m for m in d["messages"] if m["role"] != "admin"]
        t0 = time.perf_counter()
        triage[r["ticket_id"]] = cp.triage(payload)
        lat.append((time.perf_counter() - t0) * 1000)
    assert all(triage[i]["category"] == pred_cat[i] for i in pred_cat), "категория в triage расходится с прямым расчётом"

    out = {
        "git_commit": git("rev-parse", "HEAD"), "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": git("status", "--short"), "python": platform.python_version(),
        "rules_fingerprint": cp.rules_fingerprint, "models_loaded": cp.category_model.loaded,
        "label_source": "own (data/labels/valid_gold.json: rules + manual overrides); official labels do not exist locally",
        "leak_counts": dict(Counter(flags)),
        "own_labels": {
            "all": block(valid, pred_cat, pred_pri),
            "exact_text_in_train": block([r for r in valid if r["leak"] == "exact"], pred_cat, pred_pri),
            "near_dup_in_train": block([r for r in valid if r["leak"] == "near"], pred_cat, pred_pri),
            "clean_not_in_train": block([r for r in valid if r["leak"] == "clean"], pred_cat, pred_pri),
        },
        "own_labels_by_lang": {
            lg: block([r for r in valid if r["server_lang"] == lg], pred_cat, pred_pri) for lg in ("ru", "uz", "kk")
            if any(r["server_lang"] == lg for r in valid)},
        "own_labels_clean_by_lang": {
            lg: block([r for r in valid if r["server_lang"] == lg and r["leak"] == "clean"], pred_cat, pred_pri)
            for lg in ("ru", "uz", "kk") if any(r["server_lang"] == lg and r["leak"] == "clean" for r in valid)},
        "admin_verdict_proxy": {
            "note": "согласие сценария черновика с вердиктом админа: это не категория и не оценка жюри",
            "all": scen_agree(valid, triage),
            "clean_not_in_train": scen_agree([r for r in valid if r["leak"] == "clean"], triage),
        },
        "latency_ms": {"p50": round(statistics.median(lat), 2), "p95": round(sorted(lat)[int(.95 * len(lat)) - 1], 2),
                       "p99": round(sorted(lat)[int(.99 * len(lat)) - 1], 2)},
        "intents": dict(Counter(triage[r["ticket_id"]]["_meta"]["intent"] for r in valid)),
    }
    (C.OUT / "baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    # приватный кэш с полными ответами baseline: нужен для сравнения черновиков (тексты игроков внутри)
    (C.CACHE / "valid_baseline_triage.pkl").write_bytes(pickle.dumps(
        {"triage": triage, "pred_cat": pred_cat, "pred_pri": pred_pri, "leak": {r["ticket_id"]: r["leak"] for r in valid}}))
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
