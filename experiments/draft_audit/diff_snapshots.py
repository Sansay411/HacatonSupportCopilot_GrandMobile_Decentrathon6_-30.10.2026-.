"""Сравнение снимков before/after: что изменилось по категориям, needs_human, сценариям. Только агрегаты на экран/в reports/draft_audit."""
import collections, json
import common as C
B = {r["ticket_id"]: r for r in map(json.loads, open(C.PRIVATE/"valid_before.jsonl", encoding="utf-8"))}
A = {r["ticket_id"]: r for r in map(json.loads, open(C.PRIVATE/"valid_after.jsonl", encoding="utf-8"))}
cat_changed = [k for k in B if B[k]["category"] != A[k]["category"]]
prio_changed = [k for k in B if B[k]["priority"] != A[k]["priority"]]
nh = collections.Counter((B[k]["needs_human"], A[k]["needs_human"]) for k in B if B[k]["needs_human"] != A[k]["needs_human"])
trans = collections.Counter((B[k]["intent"], A[k]["intent"]) for k in B if B[k]["intent"] != A[k]["intent"])
text_changed = sum(1 for k in B if B[k]["text"] != A[k]["text"])
print("category changed:", len(cat_changed), "priority changed:", len(prio_changed), "needs_human changed:", dict(nh))
print("text changed:", text_changed, "of", len(B))
for (b, a), n in trans.most_common(): print(f"  {b} -> {a}: {n}")
out = {"category_changed": len(cat_changed), "priority_changed": len(prio_changed), "needs_human_changed": {f"{k[0]}->{k[1]}": v for k, v in nh.items()},
       "text_changed": text_changed, "intent_transitions": {f"{b}->{a}": n for (b, a), n in trans.most_common()}}
(C.PUBLIC/"snapshot_diff.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
