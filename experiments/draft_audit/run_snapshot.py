"""Снимок черновиков на valid: пишет приватный файл с текстами и публичный агрегат.

    python experiments/draft_audit/run_snapshot.py --tag before
    python experiments/draft_audit/run_snapshot.py --tag after
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import time

import common as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    rows = C.load_valid()
    t0 = time.perf_counter()
    res = C.run(rows)
    dt = time.perf_counter() - t0
    recs = []
    for r, x in zip(rows, res):
        recs.append({
            "ticket_id": r.get("ticket_id"), "kind": r["kind"], "server_lang": r.get("server_lang"),
            "player_text": C.player_text(r), "images": r.get("images_count"),
            "verdict_admin": r.get("verdict"), "violation_admin": r.get("violation"), "punishment_admin": r.get("punishment"),
            "category": x["category"], "priority": x["priority"], "needs_human": x["needs_human"],
            "intent": x["_meta"]["intent"], "reply_lang": x["draft_reply"]["lang"], "text": x["draft_reply"]["text"],
            "cited": x["draft_reply"]["cited"], "reasons": x["reasons"],
            "alternatives": x["_meta"]["alternatives"], "latency_ms": x["_meta"]["latency_ms"],
            "is_dup": x["is_spam_or_duplicate"],
        })
    C.dump(C.PRIVATE / f"valid_{args.tag}.jsonl", recs)
    lat = sorted(r["latency_ms"] for r in recs)
    agg = {
        "tag": args.tag, "n": len(recs), "wall_s": round(dt, 2),
        "latency_ms_p50": lat[len(lat) // 2], "latency_ms_p95": lat[int(len(lat) * 0.95)],
        "intents": dict(collections.Counter(r["intent"] for r in recs).most_common()),
        "needs_human_share": round(sum(r["needs_human"] for r in recs) / len(recs), 4),
        "category": dict(collections.Counter(r["category"] for r in recs).most_common()),
        "mean_len": round(statistics.mean(len(r["text"]) for r in recs), 1),
    }
    C.PUBLIC.mkdir(parents=True, exist_ok=True)
    (C.PUBLIC / f"snapshot_{args.tag}.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
