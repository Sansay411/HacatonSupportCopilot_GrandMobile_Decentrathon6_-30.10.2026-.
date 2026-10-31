"""Как работает RuleBase.search в pick_violation на train: точность top-1 против пункта, названного админом.

Gold: поле violation одобренных жалоб train, ровно один пункт. Поиск вызывается только для категории complaint.other
после всех явных правил в drafts.pick_violation; здесь вызовы перехватываются, код продукта не меняется.
Тексты не сохраняются, печатаются только счётчики.

    python experiments/final_polish/rag_train_curve.py [--limit 30000]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "draft_audit"))
import common as C  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=20261101)
    a = ap.parse_args()
    from copilot.pipeline import Copilot

    cp = Copilot()
    with gzip.open(ROOT / "data" / "tickets_train.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    rows = [r for r in rows if r["kind"] == "complaint" and r.get("verdict") == "approved" and r.get("violation")]
    random.Random(a.seed).shuffle(rows)
    rows = rows[:a.limit]
    rows.sort(key=lambda r: r.get("created_at") or "")

    calls: list[dict] = []
    orig = cp.rules.search

    def spy(query, k=5, sections=None):
        res = orig(query, k=k, sections=sections)
        spy.last = [(p.cite, round(s, 2)) for p, s in res]
        return res

    cp.rules.search = spy
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from rag_candidate import Candidate
    cand = Candidate(cp.rules)
    orig_spy = spy

    def spy2(query, k=5, sections=None):
        res = orig_spy(query, k=k, sections=sections)
        spy.cand = cand.search(query)[0]
        return res

    cp.rules.search = spy2
    seen_cats = collections.Counter()
    for r in rows:
        admin = cp.rules.parse_refs(r["violation"])
        if len(admin) != 1:
            continue
        spy.last = None
        x = cp.triage(C.player_payload(r))
        seen_cats[str(x["category"])] += 1
        if spy.last is None:
            continue
        top = spy.last[0] if spy.last else None
        calls.append({"admin": admin[0], "cand": getattr(spy, "cand", None), "top": top[0] if top else None,
                      "score": top[1] if top else 0.0,
                      "second": spy.last[1][1] if len(spy.last) > 1 else 0.0, "intent": x["_meta"]["intent"],
                      "cited": x["draft_reply"]["cited"]})
    print("тикетов с одним пунктом админа по категориям:", dict(seen_cats.most_common(6)))
    print("вызовов search:", len(calls), "из них пункт админа в разделе общих правил:",
          sum(1 for c in calls if c["admin"] in cp.rules.points and cp.rules.points[c["admin"]].section_id == 30))
    for thr in (4, 6, 8, 10, 12, 14, 16, 20):
        hit = [c for c in calls if c["score"] >= thr]
        ok = sum(1 for c in hit if c["top"] == c["admin"])
        print(f"  порог {thr:>2}: выдано {len(hit):>5}, верно {ok:>5}, точность {ok / max(1, len(hit)):.3f}")
    print("  оракул (пункт админа есть среди top-1 при любом score):", sum(1 for c in calls if c["top"] == c["admin"]), "из", len(calls))
    cc = [c for c in calls if c["cand"]]
    print(f"  кандидат: выдано {len(cc)}, верно {sum(1 for c in cc if c['cand'] == c['admin'])}, "
          f"точность {sum(1 for c in cc if c['cand'] == c['admin']) / max(1, len(cc)):.3f}")
    print("  пункты админа в этих вызовах:", collections.Counter(c["admin"] for c in calls).most_common(12))
    print("  top-1 поиска:", collections.Counter(c["top"] for c in calls).most_common(8))
    print("  сценарий черновика в этих вызовах:", collections.Counter(c["intent"] for c in calls).most_common(6))


if __name__ == "__main__":
    main()
