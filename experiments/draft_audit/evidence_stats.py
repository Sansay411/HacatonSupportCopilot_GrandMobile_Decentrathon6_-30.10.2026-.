"""Статистики, на которых основаны два правила в drafts.py (пишет только агрегаты на экран).

1. Порог уверенности 0,7 для названия нарушения в запросе доказательств: доля названий, совпавших с собственной разметкой valid.
   Нужны reports/private/draft_audit/valid_after.jsonl (run_snapshot.py --tag after), data/labels/valid_gold.json, data/, models/.
2. Пункты 2.2 и 2.4, выбранные игроком: что ставили админы в одобренных жалобах train, если в тексте нет признаков темы.

    python experiments/draft_audit/evidence_stats.py
"""
from __future__ import annotations

import collections
import gzip
import json
import re

import common as C
from copilot.pipeline import Copilot
from copilot.rules import load


def naming_accuracy_by_confidence():
    gold = json.load(open(C.ROOT / "data" / "labels" / "valid_gold.json", encoding="utf-8"))
    rows = C.load_valid()
    cp = Copilot()
    order = sorted(range(len(rows)), key=lambda i: (rows[i].get("created_at") or "", i))
    conf, cat = {}, {}
    for i in order:
        r = cp.triage(C.player_payload(rows[i]))
        conf[rows[i]["ticket_id"]], cat[rows[i]["ticket_id"]] = r["confidence"], r["category"]
    B = {r["ticket_id"]: r for r in map(json.loads, open(C.PRIVATE / "valid_before.jsonl", encoding="utf-8"))}
    A = {r["ticket_id"]: r for r in map(json.loads, open(C.PRIVATE / "valid_after.jsonl", encoding="utf-8"))}
    bins = [(0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.01)]
    tab = collections.defaultdict(lambda: [0, 0])
    for tid, a in A.items():
        if a["intent"] == "need_evidence" and a["text"] != B[tid]["text"] and conf[tid] >= 0:
            for lo, hi in bins:
                if lo <= conf[tid] < hi:
                    tab[(lo, hi)][0] += 1
                    tab[(lo, hi)][1] += gold[tid]["category"] == cat[tid]
    print("категория совпала с собственной разметкой valid, по уверенности (среди тикетов с изменившимся запросом видео):")
    for k in bins:
        print(f"  {k}: {tab[k][1]}/{tab[k][0]}")


def topical_rule_overrides():
    rb = load(str(C.ROOT / "data" / "rules.json"))
    rows = [json.loads(x) for x in gzip.open(C.ROOT / "data" / "tickets_train.jsonl.gz", "rt", encoding="utf-8")]
    rows = [r for r in rows if r["kind"] == "complaint" and r.get("verdict") == "approved" and r.get("violation")]
    cues = {"2.2": r"пропаганд|18\+|порн|секс|наркот|лгбт|политик|суицид|нацизм|sex|porn",
            "2.4": r"расиз|нац(?:ия|ии|ист|ионал)|религ|негр|нег#|xenoph|ислам|мусульман|христиан|еврей|хохл|чурк"}
    print("пункт из формы игрока -> пункт админа (одобренные жалобы train):")
    for ref, rx in cues.items():
        tab = collections.defaultdict(collections.Counter)
        for r in rows:
            raw, adm = rb.parse_refs(r.get("rule_refs_raw") or ""), rb.parse_refs(r["violation"])
            if raw == [ref] and adm:
                text = " ".join(m.get("text", "") for m in r["messages"] if m.get("role", "player") == "player").lower()
                tab[bool(re.search(rx, text))][adm[0]] += 1
        for has_cue, c in sorted(tab.items()):
            print(f"  {ref}, признак темы в тексте={has_cue}: n={sum(c.values())}, {c.most_common(3)}")


if __name__ == "__main__":
    naming_accuracy_by_confidence()
    topical_rule_overrides()
