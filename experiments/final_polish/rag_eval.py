"""Сравнение действующего поиска пункта и кандидата на заранее размеченном наборе tests/fixtures/rag_cases.py.

    python experiments/final_polish/rag_eval.py [--json reports/final_polish/rag_eval.json]

Действующий поиск: RuleBase.search(текст, k=1, sections={30}) с порогом 12,0, как в drafts.pick_violation.
Метрики считаются по набору: верных цитат среди ясных случаев (pos), ложных цитат на всём наборе, воздержаний на neg и neg_word.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rag_cases import CASES  # noqa: E402
from rag_candidate import Candidate  # noqa: E402
from copilot.rules import load  # noqa: E402

BASELINE_THRESHOLD = 12.0


def baseline(rb, text):
    hits = rb.search(text, k=1, sections={30})
    if hits and hits[0][1] >= BASELINE_THRESHOLD:
        return hits[0][0].cite, hits[0][1]
    return None, hits[0][1] if hits else 0.0


def judge(case, cite):
    acceptable = {case["gold"], *case["ok"]} - {None}
    if cite is None:
        return "abstain"
    return "correct" if cite in acceptable else "false"


def evaluate(name, fn, rb):
    res = collections.defaultdict(collections.Counter)
    detail = []
    t0 = time.perf_counter()
    for c in CASES:
        cite, score = fn(rb, c["text"])
        verdict = judge(c, cite)
        res[c["tag"]][verdict] += 1
        detail.append({"tag": c["tag"], "gold": c["gold"], "got": cite, "verdict": verdict})
    ms = (time.perf_counter() - t0) / len(CASES) * 1000
    pos = res["pos"]
    cited = sum(v["correct"] + v["false"] for v in res.values())
    correct = sum(v["correct"] for v in res.values())
    false = sum(v["false"] for v in res.values())
    out = {"name": name, "pos_correct": pos["correct"], "pos_total": sum(pos.values()), "false_cites_total": false,
           "false_on_neg": res["neg"]["false"], "false_on_neg_word": res["neg_word"]["false"],
           "cited": cited, "correct": correct, "precision": round(correct / cited, 3) if cited else None,
           "ms_per_query": round(ms, 3), "by_tag": {k: dict(v) for k, v in res.items()}}
    return out, detail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    rb = load(str(ROOT / "data" / "rules.json"))
    cand = Candidate(rb)
    results = []
    for name, fn in (("baseline (BM25, порог 12)", baseline), ("candidate (BM25 v2, покрытие 2, зазор 1,3)", lambda rb_, t: cand.search(t))):
        out, detail = evaluate(name, fn, rb)
        results.append(out)
        print(json.dumps(out, ensure_ascii=False))
        if a.verbose:
            for c, d in zip(CASES, detail):
                if d["verdict"] != "abstain" or c["tag"] == "pos":
                    print("   ", d["tag"], d["gold"], "->", d["got"], d["verdict"])
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
