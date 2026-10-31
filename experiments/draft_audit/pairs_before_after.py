"""60 слепых пар: что изменилось в шаблонном ответе A (Sentra) между «до» и «после». Тексты выводятся только на экран.

    python experiments/draft_audit/pairs_before_after.py [--show]
"""
import argparse, csv, json, collections
import common as C

ap = argparse.ArgumentParser(); ap.add_argument("--show", action="store_true"); a = ap.parse_args()
base = C.ROOT / "reports" / "private" / "final_quality"
key = json.loads((base / "blind_pairs_real.KEY.json").read_text(encoding="utf-8"))
with open(base / "human_review_pairs.csv", encoding="utf-8-sig") as f:
    pairs = list(csv.DictReader(f))
B = {r["ticket_id"]: r for r in map(json.loads, open(C.PRIVATE/"valid_before.jsonl", encoding="utf-8"))}
A = {r["ticket_id"]: r for r in map(json.loads, open(C.PRIVATE/"valid_after.jsonl", encoding="utf-8"))}
changed, trans = [], collections.Counter()
for p in pairs:
    tid = key[p["pair_id"]]["id"]
    b, af = B[tid], A[tid]
    if b["text"] != af["text"]:
        changed.append((p, b, af))
        trans[(b["intent"], af["intent"])] += 1
print(f"пар: {len(pairs)}, ответ A изменился: {len(changed)}")
for (x, y), n in trans.most_common(): print(f"  {x} -> {y}: {n}")
if a.show:
    for p, b, af in changed:
        pt = " ".join(p["player_text"].split())[:130]
        print(f"[{p['pair_id']} {p['language']}] {pt}\n   ДО   : {b['text'][:200]}\n   ПОСЛЕ: {af['text'][:260]}")
