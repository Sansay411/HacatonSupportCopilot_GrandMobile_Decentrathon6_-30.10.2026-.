"""Снимок «до/после» финальной полировки качества: одинаковые входы, сравнение по тегам.

    python experiments/final_polish/snapshot.py --tag pre
    python experiments/final_polish/snapshot.py --tag post
    python experiments/final_polish/compare.py pre post

Что прогоняется (в порядке created_at, дедупликация включена, как в scripts/predict.py):
  * valid: 1000 обращений;
  * train: случайные 8000 обращений (seed 20261101), ответы админов из входа вырезаны;
  * синтетические пробы tests/fixtures/draft_probes.py и 13 + 13 сценариев Tera (одиночный и повторный).

Тексты игроков пишутся только в reports/private/final_polish/ (в .gitignore); наружу идут агрегаты в reports/final_polish/.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "draft_audit"))
import common as C  # noqa: E402

PRIVATE = ROOT / "reports" / "private" / "final_polish"
PUBLIC = ROOT / "reports" / "final_polish"
TRAIN_SEED, TRAIN_N = 20261101, 8000


def record(row: dict, x: dict) -> dict:
    return {
        "ticket_id": row.get("ticket_id"), "kind": row["kind"], "server_lang": row.get("server_lang"),
        "player_text": C.player_text(row), "images": row.get("images_count"),
        "verdict_admin": row.get("verdict"), "violation_admin": row.get("violation"),
        "category": x["category"], "priority": x["priority"], "needs_human": x["needs_human"],
        "confidence": x["confidence"], "intent": x["_meta"]["intent"], "reply_lang": x["draft_reply"]["lang"],
        "text": x["draft_reply"]["text"], "cited": x["draft_reply"]["cited"], "rule_refs": x["extracted"]["rule_refs"],
        "has_evidence": x["extracted"]["has_evidence"], "reasons": x["reasons"],
        "alt_intents": [a["intent"] for a in x["_meta"]["alternatives"]], "latency_ms": x["_meta"]["latency_ms"],
        "is_dup": x["is_spam_or_duplicate"],
    }


def load_train() -> list[dict]:
    with gzip.open(ROOT / "data" / "tickets_train.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    random.Random(TRAIN_SEED).shuffle(rows)
    return rows[:TRAIN_N]


def run_synth(cp) -> list[dict]:
    from probes import PROBES
    out = []
    for i, p in enumerate(PROBES):
        payload = {"kind": p["kind"], "messages": [{"role": "player", "text": p["text"]}]}
        if p["server_lang"]:
            payload["server_lang"] = p["server_lang"]
        if p["images"] is not None:
            payload["images_count"] = p["images"]
        if p["nick"]:
            payload["reported_nick"] = p["nick"]
        r = cp.triage(payload, use_dedup=False)
        out.append({"i": i, "group": p["group"], "text": p["text"], "category": r["category"], "priority": r["priority"],
                    "intent": r["_meta"]["intent"], "needs_human": r["needs_human"], "reply": r["draft_reply"]["text"],
                    "cited": r["draft_reply"]["cited"], "ok": sorted(p["ok"]) if p["ok"] else None})
    return out


def run_tera(cp) -> list[dict]:
    from tests.test_redteam_audit import TERA_P0_CASES
    out = []
    for name, kind, lang, text in TERA_P0_CASES:
        base = {"kind": kind, "server_lang": lang, "reporter_hash": f"tera_{name}",
                "messages": [{"role": "player", "text": text, "attachments": 0}]}
        r1 = cp.triage(dict(base, created_at="2026-10-31T10:00:00Z"))
        r2 = cp.triage(dict(base, created_at="2026-10-31T10:05:00Z"))
        for tag, r in (("single", r1), ("duplicate", r2)):
            out.append({"name": name, "variant": tag, "category": r["category"], "priority": r["priority"],
                        "intent": r["_meta"]["intent"], "needs_human": r["needs_human"], "is_dup": r["is_spam_or_duplicate"],
                        "cited": r["draft_reply"]["cited"], "reply": r["draft_reply"]["text"]})
    return out


def pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(len(s) * q))], 2)


def aggregate(recs: list[dict]) -> dict:
    by_intent = collections.defaultdict(list)
    for r in recs:
        by_intent[r["intent"]].append(len(r["text"]))
    lat = [r["latency_ms"] for r in recs]
    return {
        "n": len(recs),
        "intents": {k: {"n": len(v), "median_len": int(statistics.median(v)), "mean_len": round(statistics.mean(v), 1)}
                    for k, v in sorted(by_intent.items(), key=lambda kv: -len(kv[1]))},
        "median_len_all": int(statistics.median(len(r["text"]) for r in recs)),
        "median_len_complaint": int(statistics.median(len(r["text"]) for r in recs if r["kind"] == "complaint")),
        "median_len_report": int(statistics.median(len(r["text"]) for r in recs if r["kind"] == "report")),
        "distinct_texts": len({r["text"] for r in recs}),
        "needs_human_share": round(sum(r["needs_human"] for r in recs) / len(recs), 4),
        "latency_ms_p50": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    from copilot.pipeline import Copilot

    PRIVATE.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    agg: dict = {"tag": a.tag}
    for name, rows in (("valid", C.load_valid()), ("train", load_train())):
        t0 = time.perf_counter()
        res = C.run(rows, Copilot())
        wall = time.perf_counter() - t0
        recs = [record(r, x) for r, x in zip(rows, res)]
        C.dump(PRIVATE / f"{a.tag}_{name}.jsonl", recs)
        agg[name] = dict(aggregate(recs), wall_s=round(wall, 2))
        print(name, json.dumps(agg[name], ensure_ascii=False)[:400])
    cp = Copilot()
    synth, tera = run_synth(cp), run_tera(cp)
    (PRIVATE / f"{a.tag}_synth.json").write_text(json.dumps(synth, ensure_ascii=False, indent=1), encoding="utf-8")
    (PRIVATE / f"{a.tag}_tera.json").write_text(json.dumps(tera, ensure_ascii=False, indent=1), encoding="utf-8")
    scored = [s for s in synth if s["ok"]]
    agg["synth"] = {"n": len(synth), "scenario_ok": f"{sum(s['intent'] in s['ok'] for s in scored)}/{len(scored)}"}
    agg["tera"] = {"n": len(tera), "needs_human_all": all(t["needs_human"] for t in tera),
                   "duplicates_flagged": sum(t["is_dup"] for t in tera if t["variant"] == "duplicate")}
    (PUBLIC / f"{a.tag}_aggregate.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("synth", agg["synth"], "tera", agg["tera"])


if __name__ == "__main__":
    main()
