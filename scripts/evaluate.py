"""Оценка всего сервиса на tickets_valid.jsonl.

Метрики:
- категория: accuracy, приоритет: macro-F1 (по dev-разметке data/labels/valid_gold.json);
- согласие сценария черновика с реальным вердиктом админа (вердикт есть в valid);
- доля needs_human и автоответов, латентность p50/p95, стоимость;
- галлюцинации: доля цитат, которых нет в rules.json (должна быть 0);
- язык черновика против языка реального ответа админа.
Результат: reports/metrics.json и печать в консоль.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sklearn.metrics import accuracy_score, f1_score  # noqa: E402

from copilot import lang as lang_mod  # noqa: E402
from copilot.pipeline import Copilot  # noqa: E402

INTENT_TO_VERDICT = {
    "approve": "approved", "need_evidence": "need_evidence", "no_description": "invalid_format",
    "toxic": "invalid_format", "not_complaint": "rejected", "duplicate": "duplicate", "appeal": "appeal",
    "appeal_reject": "appeal",
}
VERDICT_GROUP = {
    "approved": "approved", "already_punished": "approved", "need_evidence": "need_evidence",
    "invalid_format": "reject", "rejected": "reject", "duplicate": "duplicate",
    "appeal_rejected": "appeal", "appeal_approved": "appeal",
}


def main():
    cp = Copilot()
    rows = [json.loads(l) for l in open(ROOT / "data/tickets_valid.jsonl", encoding="utf-8")]
    gold_path = ROOT / "data/labels/valid_gold.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8")) if gold_path.exists() else {}
    rows.sort(key=lambda d: d.get("created_at") or "")
    preds, lat = [], []
    for d in rows:
        payload = {k: v for k, v in d.items() if k not in ("verdict", "punishment", "violation", "category", "priority")}
        payload["messages"] = [m for m in d["messages"] if m["role"] != "admin"]
        t0 = time.perf_counter()
        r = cp.triage(payload)
        lat.append((time.perf_counter() - t0) * 1000)
        preds.append((d, r))

    out = {}
    if gold:
        y = [gold[d["ticket_id"]]["category"] for d, _ in preds]
        p = [r["category"] for _, r in preds]
        yp = [gold[d["ticket_id"]]["priority"] for d, _ in preds]
        pp = [r["priority"] for _, r in preds]
        out["category_accuracy"] = round(accuracy_score(y, p), 3)
        out["category_macro_f1"] = round(f1_score(y, p, average="macro"), 3)
        out["priority_macro_f1"] = round(f1_score(yp, pp, average="macro"), 3)
        out["priority_accuracy"] = round(accuracy_score(yp, pp), 3)

    # сценарий против вердикта админа (только жалобы с распознанным вердиктом)
    agree = total = 0
    by_intent = defaultdict(Counter)
    for d, r in preds:
        if d["kind"] != "complaint":
            continue
        vg = VERDICT_GROUP.get(d.get("verdict"))
        it = r["_meta"]["intent"]
        by_intent[it][d.get("verdict")] += 1
        if not vg:
            continue
        iv = INTENT_TO_VERDICT.get(it)
        iv = {"invalid_format": "reject", "rejected": "reject"}.get(iv, iv)
        total += 1
        agree += int(iv == vg)
    out["draft_scenario_matches_admin_verdict"] = round(agree / max(1, total), 3)
    out["draft_scenario_n"] = total

    cited = [c for _, r in preds for c in r["draft_reply"]["cited"]]
    out["citations_total"] = len(cited)
    out["citations_nonexistent"] = sum(1 for c in cited if not cp.rules.exists(c))
    out["drafts_with_citation_share"] = round(sum(1 for _, r in preds if r["draft_reply"]["cited"]) / len(preds), 3)
    out["needs_human_share"] = round(sum(r["needs_human"] for _, r in preds) / len(preds), 3)
    out["needs_human_share_by_kind"] = {
        k: round(sum(r["needs_human"] for d, r in preds if d["kind"] == k) / max(1, sum(1 for d, _ in preds if d["kind"] == k)), 3)
        for k in ("complaint", "report")}
    out["spam_or_duplicate_share"] = round(sum(r["is_spam_or_duplicate"] for _, r in preds) / len(preds), 3)
    dup_true = [d for d, _ in preds if d.get("verdict") == "duplicate"]
    out["duplicate_recall_vs_admin"] = round(
        sum(1 for d, r in preds if d.get("verdict") == "duplicate" and r["is_spam_or_duplicate"]) / max(1, len(dup_true)), 3)

    # язык: черновик против языка, на котором ответил админ
    lang_ok = lang_n = 0
    for d, r in preds:
        admin = [m["text"] for m in d["messages"] if m["role"] == "admin"]
        if not admin:
            continue
        al = lang_mod.detect(admin[0], d.get("server_lang"))
        if al in ("ru", "uz", "kk", "en"):
            lang_n += 1
            lang_ok += int(al == r["draft_reply"]["lang"])
    out["draft_lang_equals_admin_reply_lang"] = round(lang_ok / max(1, lang_n), 3)
    out["draft_lang_distribution"] = dict(Counter(r["draft_reply"]["lang"] for _, r in preds))

    lat_sorted = sorted(lat)
    out["latency_ms_p50"] = round(statistics.median(lat_sorted), 1)
    out["latency_ms_p95"] = round(lat_sorted[int(0.95 * len(lat_sorted)) - 1], 1)
    out["cost_usd_per_ticket"] = 0.0 if cp.llm is None else None
    out["intents"] = dict(Counter(r["_meta"]["intent"] for _, r in preds))
    out["intent_vs_admin_verdict"] = {k: dict(v) for k, v in by_intent.items()}

    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))

    # примеры с реальными текстами: только в приватную папку (не коммитится)
    priv = ROOT / "reports/private"
    priv.mkdir(parents=True, exist_ok=True)
    with open(priv / "valid_predictions.jsonl", "w", encoding="utf-8") as f:
        for d, r in preds:
            f.write(json.dumps({"ticket_id": d["ticket_id"], "player": d["messages"][0]["text"],
                                "admin": next((m["text"] for m in d["messages"] if m["role"] == "admin"), None),
                                "verdict": d.get("verdict"), "pred": r}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
