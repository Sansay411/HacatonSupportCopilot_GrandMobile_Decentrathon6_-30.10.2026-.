"""Полнота и точность поиска по базе знаний (copilot/kb.py) на train: вопросы игроков против маршрутов в ответах админов.

Gold для вопроса: в ответе админа на тот же репорт есть последний элемент маршрута записи базы знаний
(«Правительство», «Автошкола»…). Это то же происхождение, что у записей KB, поэтому метрика измеряет только
полноту шаблонов (морфология, порядок слов), а не новые знания. Train делится по хешу ticket_id на dev и test;
правки шаблонов смотрят только dev. Тексты не сохраняются, печатаются счётчики.

    python experiments/final_polish/kb_recall.py [--split dev|test|all] [--show-misses 0]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from copilot import kb  # noqa: E402


def split_of(tid: str) -> str:
    return "dev" if int(hashlib.md5(str(tid).encode()).hexdigest(), 16) % 2 == 0 else "test"


def admin_text(r: dict) -> str:
    return " ".join((m.get("text") or "") for m in r["messages"] if m.get("role") == "admin")


def player_text(r: dict) -> str:
    return "\n".join((m.get("text") or "") for m in r["messages"] if m.get("role", "player") == "player")


def targets() -> dict[str, re.Pattern]:
    out = {}
    for e in kb.KB:
        if e.path:
            out[e.key] = re.compile(re.escape(e.path.split(">")[-1].strip()), re.I)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all")
    ap.add_argument("--show-misses", type=int, default=0)
    a = ap.parse_args()
    tg = targets()
    with gzip.open(ROOT / "data" / "tickets_train.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    rows = [r for r in rows if r["kind"] == "report" and (a.split == "all" or split_of(r["ticket_id"]) == a.split)]
    per = collections.defaultdict(lambda: collections.Counter())
    false_hits = collections.Counter()
    n_hit_total = 0
    misses = []
    for r in rows:
        ans, q = admin_text(r), player_text(r)
        hit = kb.lookup(q, "ru")
        key = hit[1].key if hit else None
        n_hit_total += bool(hit)
        gold = [k for k, rx in tg.items() if rx.search(ans)]
        for k in gold:
            per[k]["gold"] += 1
            if key == k:
                per[k]["found"] += 1
            elif len(misses) < a.show_misses:
                misses.append((k, q[:120]))
        if key and key in tg and key not in gold:
            false_hits[key] += 1
    print(f"репортов: {len(rows)}, ответов базы знаний: {n_hit_total}")
    for k in tg:
        g, f_ = per[k]["gold"], per[k]["found"]
        print(f"  {k:<16} gold {g:>4}  найдено {f_:>4}  полнота {f_ / max(1, g):.2f}  срабатываний без маршрута в ответе админа: {false_hits[k]}")
    for k, q in misses:
        print("  MISS", k, "|", q)


if __name__ == "__main__":
    main()
