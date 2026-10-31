"""Раскрывает ключ X/Y -> A/B для оценок судьи и считает средние. Запускается только после того, как оценки записаны."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

import numpy as np  # noqa: E402

CRIT = ["relevance", "completeness", "naturalness", "language", "fact_support"]


def main(scores_path, key_path, pairs_path, out_path):
    sc = json.loads(Path(scores_path).read_text(encoding="utf-8"))["scores"]
    key = json.loads(Path(key_path).read_text(encoding="utf-8"))
    pairs = {json.loads(l)["pair_id"]: json.loads(l) for l in Path(pairs_path).read_text(encoding="utf-8").splitlines() if l}
    per = {"A": [], "B": []}
    by_lang = defaultdict(lambda: {"A": [], "B": []})
    wins = Counter()
    wins_lang = defaultdict(Counter)
    for pid, s in sc.items():
        k = key[pid]
        lang = pairs[pid]["lang"]
        for side in ("X", "Y"):
            sysname = k[side]
            per[sysname].append(s[side])
            by_lang[lang][sysname].append(s[side])
        pref = s["pref"]
        w = "tie" if pref == "tie" else k[pref]
        wins[w] += 1
        wins_lang[lang][w] += 1
    def avg(rows):
        a = np.array(rows, float)
        return {c: round(float(a[:, i].mean()), 2) for i, c in enumerate(CRIT)} | {"overall": round(float(a.mean()), 2), "n": len(rows)}
    out = {"unofficial": "оценки LLM-судьи, не оценка жюри; слепота неполная",
           "pairs": len(sc), "preference": dict(wins),
           "preference_by_lang": {l: dict(c) for l, c in wins_lang.items()},
           "A_templates": avg(per["A"]), "B_qwen": avg(per["B"]),
           "by_lang": {l: {"A_templates": avg(v["A"]), "B_qwen": avg(v["B"])} for l, v in by_lang.items()}}
    # знаковая проверка без ничьих
    a_w, b_w = wins.get("A", 0), wins.get("B", 0)
    from math import comb
    n = a_w + b_w
    p = sum(comb(n, k) for k in range(max(a_w, b_w), n + 1)) / 2 ** n * 2 if n else 1.0
    out["sign_test_p_two_sided"] = round(min(1.0, p), 4)
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:5])
