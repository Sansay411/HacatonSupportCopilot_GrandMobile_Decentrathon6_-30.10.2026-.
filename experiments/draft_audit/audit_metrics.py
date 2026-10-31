"""Сводка аудита: одни и те же проверки над черновиками «до» и «после» на valid (1000) и на независимой выборке train.

Читает приватные снимки (reports/private/draft_audit/*.jsonl), пишет только агрегаты в reports/draft_audit/audit_metrics.json.

    python experiments/draft_audit/audit_metrics.py
"""
from __future__ import annotations

import json
import re
import sys

import common as C

sys.path.insert(0, str(C.ROOT / "tests" / "fixtures"))
from draft_probes import PROBES  # noqa: E402

SETTLED = re.compile(
    r"выдано верно|оснований для (его )?снятия нет|jazo to‘g‘ri berilgan|жаза дұрыс берілген|penalty was issued correctly|"
    r"sanción se aplicó correctamente|punição foi aplicada corretamente", re.I)
TIME_UNIT = r"(?:мин(?:ут\w*)?|час\w*|сек(?:унд\w*)?|раз|дн\w*|день|недел\w*|месяц\w*|год|лет)(?![а-яa-z])"
INTENT_TO_VERDICT = {"approve": "approved", "need_evidence": "need_evidence", "no_description": "reject", "toxic": "reject",
                     "not_complaint": "reject", "duplicate": "duplicate", "appeal": "appeal", "appeal_reject": "appeal"}
VERDICT_GROUP = {"approved": "approved", "already_punished": "approved", "need_evidence": "need_evidence", "invalid_format": "reject",
                 "rejected": "reject", "duplicate": "duplicate", "appeal_rejected": "appeal", "appeal_approved": "appeal"}


def load(name):
    return [json.loads(x) for x in open(C.PRIVATE / name, encoding="utf-8")]


def pct(a, b):
    return round(a / b, 4) if b else None


def measure(recs, cp):
    n = len(recs)
    out = {"n": n}
    out["settled_decision_drafts"] = sum(bool(SETTLED.search(r["text"])) for r in recs)
    out["settled_decision_but_admin_lifted_penalty"] = sum(
        bool(SETTLED.search(r["text"])) and (r.get("verdict") or r.get("verdict_admin")) == "appeal_approved" for r in recs)
    bad_id = 0
    for r in recs:
        m = re.search(r"\[(\d{1,4})\]", r["text"])
        if m and re.search(rf"\b{m.group(1)}\s*{TIME_UNIT}", r["player_text"].lower()):
            bad_id += 1
    out["watch_drafts_with_id_taken_from_a_duration"] = bad_id
    ne = [r for r in recs if r["intent"] == "need_evidence"]
    named = [r for r in ne if re.search(r"(нарушение|Qoidabuzarlikni|Бұзушылықты|violation|infracción|violação) \(", r["text"])]
    out["need_evidence_n"] = len(ne)
    out["need_evidence_names_violation"] = pct(len(named), len(ne))
    for lang in ("ru", "uz", "kk"):
        sub = [r for r in ne if r["reply_lang"] == lang]
        nm = [r for r in sub if r in named]
        out[f"need_evidence_names_violation_{lang}"] = f"{len(nm)}/{len(sub)}"
    out["handoff_claim_without_human"] = sum(bool(C.HANDOFF.search(r["text"])) and not r["needs_human"] for r in recs)
    out["promise_drafts"] = sum(bool(C.PROMISE.search(r["text"])) for r in recs)
    out["nonexistent_citations"] = sum(1 for r in recs for c in r["cited"] if not cp.rules.exists(c))
    out["needs_human_share"] = pct(sum(r["needs_human"] for r in recs), n)
    out["auto_send_candidates"] = sum(not r["needs_human"] for r in recs)
    agree = total = 0
    for r in recs:
        if r["kind"] != "complaint":
            continue
        v = r.get("verdict") or r.get("verdict_admin")
        vg = VERDICT_GROUP.get(v)
        if not vg:
            continue
        total += 1
        agree += INTENT_TO_VERDICT.get(r["intent"]) == vg
    out["scenario_matches_admin_verdict"] = pct(agree, total)
    out["scenario_matches_n"] = total
    return out


def probes(path):
    recs = json.load(open(path, encoding="utf-8"))
    ok = scored = 0
    for r in recs:
        p = PROBES[r["i"]]
        if p["ok"] is None:
            continue
        scored += 1
        ok += r["intent"] in p["ok"] and not any(f.lower() in r["reply"].lower() for f in p["forbid"])
    return {"scored": scored, "acceptable": ok}


def main():
    from copilot.pipeline import Copilot
    cp = Copilot()
    res = {"valid": {}, "train_sample": {}, "probes": {}}
    for tag in ("before", "after"):
        res["valid"][tag] = measure(load(f"valid_{tag}.jsonl"), cp)
        res["train_sample"][tag] = measure(load(f"train_{tag}.jsonl"), cp)
        res["probes"][tag] = probes(C.PRIVATE / f"probes_{tag}.json")
    for ds in ("valid", "train_sample"):
        b, a = load(f"{'valid' if ds == 'valid' else 'train'}_before.jsonl"), load(f"{'valid' if ds == 'valid' else 'train'}_after.jsonl")
        key = "ticket_id"
        bm = {r[key]: r for r in b}
        am = {r[key]: r for r in a}
        res[ds]["category_changed"] = sum(bm[k]["category"] != am[k]["category"] for k in bm)
        res[ds]["priority_changed"] = sum(bm[k]["priority"] != am[k]["priority"] for k in bm)
        res[ds]["text_changed"] = sum(bm[k]["text"] != am[k]["text"] for k in bm)
        res[ds]["needs_human_changed_to_true"] = sum((not bm[k]["needs_human"]) and am[k]["needs_human"] for k in bm)
        res[ds]["needs_human_changed_to_false"] = sum(bm[k]["needs_human"] and not am[k]["needs_human"] for k in bm)
    for ds, name in (("valid", "valid"), ("train_sample", "train")):
        for tag in ("before", "after"):
            lat = sorted(r["latency_ms"] for r in load(f"{name}_{tag}.jsonl"))
            res[ds][tag]["latency_ms_p50"] = round(lat[len(lat) // 2], 2)
            res[ds][tag]["latency_ms_p95"] = round(lat[int(len(lat) * 0.95)], 2)
    C.PUBLIC.mkdir(parents=True, exist_ok=True)
    (C.PUBLIC / "audit_metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
