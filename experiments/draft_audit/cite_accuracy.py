"""Точность цитируемого пункта в черновике «approve» против пункта, который назвал админ (train, вердикт approved).

Admin-пункт берётся из поля violation. Считается, когда сценарий approve и в cited один пункт общих правил.
Выборка train не использовалась для подбора правок. Тексты не сохраняются.
"""
import collections, gzip, json, random, sys
import common as C
from copilot.pipeline import Copilot

cp = Copilot()
rows = [json.loads(x) for x in gzip.open(C.ROOT / "data" / "tickets_train.jsonl.gz", "rt", encoding="utf-8")]
rows = [r for r in rows if r["kind"] == "complaint" and r.get("verdict") == "approved" and r.get("violation")]
random.Random(11).shuffle(rows)
rows = rows[:6000]
rows.sort(key=lambda r: r.get("created_at") or "")
tot = collections.Counter(); ok = collections.Counter(); by_raw = collections.Counter(); raw_ok = collections.Counter()
for r in rows:
    admin_refs = cp.rules.parse_refs(r["violation"])
    if not admin_refs:
        continue
    payload = dict(r); payload["messages"] = [m for m in r["messages"] if m.get("role") != "admin"]
    x = cp.triage(payload)
    if x["_meta"]["intent"] != "approve" or len(x["draft_reply"]["cited"]) != 1:
        continue
    c = x["draft_reply"]["cited"][0]
    cat = x["category"]
    tot[cat] += 1; ok[cat] += c in admin_refs
    raw = cp.rules.parse_refs(r.get("rule_refs_raw") or "")
    has_raw = bool(raw)
    by_raw[has_raw] += 1; raw_ok[has_raw] += c in admin_refs
print("approve-черновик с одним пунктом: цитата совпала с пунктом админа")
for cat in sorted(tot): print(f"  {cat}: {ok[cat]}/{tot[cat]} = {ok[cat]/tot[cat]:.3f}")
print(f"  всего: {sum(ok.values())}/{sum(tot.values())} = {sum(ok.values())/sum(tot.values()):.3f}")
for k in (True, False): print(f"  игрок указал пункт в форме={k}: {raw_ok[k]}/{by_raw[k]}")
