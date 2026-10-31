"""Проверка кандидата D_svc_cal на уровне всего pipeline перед решением о внедрении.

Обучает D_svc_cal на ВСЁМ train (так же, как production обучает category.pkl), кладёт модель в var/final_quality/models_D
(production models/ не трогается), прогоняет valid через Copilot с этой моделью и с production-моделью в одинаковых условиях
и сравнивает: категорию, приоритет, needs_human, уверенность, сценарий черновика, задержку.
"""
from __future__ import annotations

import json
import pickle
import shutil
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
from common import ROOT  # noqa: E402

import numpy as np  # noqa: E402
from sklearn.metrics import accuracy_score, f1_score  # noqa: E402

import clf_experiment as E  # noqa: E402
from copilot.pipeline import Copilot  # noqa: E402

VERDICT_GROUP = {"approved": "approved", "already_punished": "approved", "need_evidence": "need_evidence",
                 "invalid_format": "reject", "rejected": "reject", "duplicate": "duplicate",
                 "appeal_rejected": "appeal", "appeal_approved": "appeal"}
INTENT_TO_VERDICT = {"approve": "approved", "need_evidence": "need_evidence", "no_description": "reject", "toxic": "reject",
                     "not_complaint": "reject", "duplicate": "duplicate", "appeal": "appeal", "appeal_reject": "appeal"}


def run(cp, raw_rows):
    out, lat = {}, []
    for d in sorted(raw_rows, key=lambda d: d.get("created_at") or ""):
        p = {k: v for k, v in d.items() if k not in ("verdict", "punishment", "violation", "category", "priority")}
        p["messages"] = [m for m in d["messages"] if m["role"] != "admin"]
        t0 = time.perf_counter()
        out[d["ticket_id"]] = cp.triage(p)
        lat.append((time.perf_counter() - t0) * 1000)
    return out, lat


def block(valid, res, mask):
    ix = [i for i, m in enumerate(mask) if m]
    y = [valid[i]["gold_cat"] for i in ix]
    p = [res[valid[i]["ticket_id"]]["category"] for i in ix]
    yp = [valid[i]["gold_pri"] for i in ix]
    pp = [res[valid[i]["ticket_id"]]["priority"] for i in ix]
    return {"n": len(ix), "category_accuracy": round(float(accuracy_score(y, p)), 4),
            "category_macro_f1": round(float(f1_score(y, p, average="macro")), 4),
            "priority_macro_f1": round(float(f1_score(yp, pp, average="macro")), 4),
            "priority_accuracy": round(float(accuracy_score(yp, pp)), 4)}


def scen(raw, res):
    n = a = 0
    for d in raw:
        if d["kind"] != "complaint" or d.get("verdict") not in VERDICT_GROUP:
            continue
        n += 1
        a += int(INTENT_TO_VERDICT.get(res[d["ticket_id"]]["_meta"]["intent"]) == VERDICT_GROUP[d["verdict"]])
    return {"n": n, "agreement": round(a / max(1, n), 4)}


def main():
    rb = C.load_rb()
    train = C.load_train(rb)
    valid = C.load_valid(rb)
    flags = C.leak_flags(valid, train)
    mdir = C.CACHE / "models_D"
    mdir.mkdir(exist_ok=True)
    t0 = time.time()
    models = E.fit_candidate("D_svc_cal", train, np.arange(len(train)))
    (mdir / "category.pkl").write_bytes(pickle.dumps(models))
    shutil.copy(ROOT / "models/verdict.pkl", mdir / "verdict.pkl")
    print(f"D_svc_cal fitted on full train in {time.time() - t0:.0f}s; category.pkl {(mdir / 'category.pkl').stat().st_size / 1e6:.1f} MB "
          f"(production LR: {(ROOT / 'models/category.pkl').stat().st_size / 1e6:.1f} MB)", flush=True)

    raw = list(C.iter_jsonl(ROOT / "data/tickets_valid.jsonl"))
    order = {r["ticket_id"]: i for i, r in enumerate(valid)}
    raw.sort(key=lambda d: order[d["ticket_id"]])
    res = {}
    lat = {}
    bad_cites = {}
    for name, md in (("production_LR", ROOT / "models"), ("D_svc_cal", mdir)):
        cp = Copilot(models_dir=md)
        res[name], lat[name] = run(cp, raw)
        bad_cites[name] = sum(1 for r in res[name].values() for c in r["draft_reply"]["cited"] if not cp.rules.exists(c))
    masks = {"all": [True] * len(valid), "clean": [f == "clean" for f in flags],
             "exact_or_near": [f != "clean" for f in flags]}
    out = {"valid_own_labels": {n: {k: block(valid, r, m) for k, m in masks.items()} for n, r in res.items()}}
    a, d = res["production_LR"], res["D_svc_cal"]
    ids = [v["ticket_id"] for v in valid]
    changed = [i for i in ids if a[i]["category"] != d[i]["category"]]
    gold = {v["ticket_id"]: v["gold_cat"] for v in valid}
    out["category_changes"] = {
        "changed": len(changed),
        "LR_right_to_SVC_wrong": sum(a[i]["category"] == gold[i] and d[i]["category"] != gold[i] for i in changed),
        "LR_wrong_to_SVC_right": sum(a[i]["category"] != gold[i] and d[i]["category"] == gold[i] for i in changed),
        "both_wrong": sum(a[i]["category"] != gold[i] and d[i]["category"] != gold[i] for i in changed),
        "transitions_top": Counter(f"{a[i]['category']}->{d[i]['category']}" for i in changed).most_common(8)}
    for name, r in res.items():
        confs = [r[i]["confidence"] for i in ids]
        out.setdefault("pipeline_behaviour", {})[name] = {
            "needs_human_share": round(float(np.mean([r[i]["needs_human"] for i in ids])), 4),
            "low_confidence_lt_0.5_share": round(float(np.mean([c < 0.5 for c in confs])), 4),
            "confidence_mean": round(float(np.mean(confs)), 4),
            "spam_or_duplicate_share": round(float(np.mean([r[i]["is_spam_or_duplicate"] for i in ids])), 4),
            "scenario_vs_admin_verdict": scen(raw, r),
            "latency_ms": {"p50": round(statistics.median(lat[name]), 2),
                           "p95": round(float(np.percentile(lat[name], 95)), 2), "p99": round(float(np.percentile(lat[name], 99)), 2)},
            "citations_nonexistent": bad_cites[name]}
    out["needs_human_flips"] = {"human_to_auto": sum(a[i]["needs_human"] and not d[i]["needs_human"] for i in ids),
                                "auto_to_human": sum((not a[i]["needs_human"]) and d[i]["needs_human"] for i in ids)}
    out["intent_changes"] = sum(a[i]["_meta"]["intent"] != d[i]["_meta"]["intent"] for i in ids)
    (C.OUT / "classifier_adoption_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
